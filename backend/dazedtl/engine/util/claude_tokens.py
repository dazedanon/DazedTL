"""Claude's own count of an estimate's input tokens, and what its cached
instructions cost.

Estimates count text with the GPT-4 encoder for every provider, but Claude's
tokenizer turns the same text into more tokens and Anthropic bills by its own
count. Its token-count endpoint is free and exact for one request, so a Claude
estimate counts each cached instruction prefix once and an evenly spread
sample of whole requests, then scales the approximate count of everything
after the prefix by what the sample measured.
"""

import json
import random
import time
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from types import SimpleNamespace
from typing import NamedTuple

import httpx

from util.provider_costs import cache_read_multiplier, cache_write_multiplier

# Smaller request sets are counted whole; a larger one's sample spans every
# file in queue order.
SAMPLES = 24
# Two round trips for a sample and its prefixes, which an estimate waits on;
# token counts have their own rate limit, far above this.
WORKERS = 16
# The request fields the endpoint counts; max_tokens and sampling settings are
# not input.
FIELDS = ("model", "system", "messages", "output_config", "thinking", "tools", "tool_choice")


# Statuses the Anthropic SDK retries, with its retry count and delays.
RETRIED = {408, 409, 429}
RETRIES = 2


def http_client(timeout):
    """The HTTP client counts go through."""
    return httpx.Client(timeout=timeout)


class CountClient:
    """Anthropic's token-count endpoint, called as the Anthropic SDK calls it
    but without importing the SDK, which takes seconds on Windows; ``count``
    uses it as ``client.messages.count_tokens(**fields).input_tokens``.
    *address* is the one *api_key* was set with, read as every Claude
    client reads one (batch_providers.anthropic_base_url)."""

    def __init__(self, api_key, address, *, timeout=30.0):
        from util.batch_providers import anthropic_base_url

        self.url = anthropic_base_url(address) + "/v1/messages/count_tokens"
        self.headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
        self.client = http_client(timeout)
        self.messages = self

    def count_tokens(self, **fields):
        for attempt in range(RETRIES + 1):
            try:
                response = self.client.post(self.url, headers=self.headers, json=fields)
            except httpx.TransportError:
                if attempt == RETRIES:
                    raise
            else:
                if not (
                    (response.status_code in RETRIED or response.status_code >= 500)
                    and attempt < RETRIES
                ):
                    response.raise_for_status()
                    return SimpleNamespace(input_tokens=int(response.json()["input_tokens"]))
            time.sleep(min(8.0, 0.5 * 2**attempt) * (1 - 0.25 * random.random()))
        raise RuntimeError("Claude's token count could not be read.")


class Count(NamedTuple):
    prefixes: dict  # cache key (see split) -> Claude tokens
    scale: float  # Claude tokens per approximate token after the prefix
    sampled: int


def _prefix_blocks(params):
    blocks = params.get("system") or []
    if isinstance(blocks, str):
        return []
    cut = next(
        (index + 1 for index, block in enumerate(blocks) if "cache_control" in block),
        0,
    )
    return blocks[:cut]


def _text(content):
    if isinstance(content, str):
        return content
    return "".join(block.get("text", "") for block in content or [] if isinstance(block, dict))


def cache_ttl(params):
    """The cache lifetime a request asks for, "5m" or "1h", or None when it
    caches nothing."""
    blocks = _prefix_blocks(params)
    if not blocks:
        return None
    control = blocks[-1].get("cache_control") or {}
    return "1h" if str(control.get("ttl", "")).lower() == "1h" else "5m"


def _prefix_fields(params):
    """What Anthropic caches up to a request's cache breakpoint: its tools and
    output format, which it renders before the instructions, and the system
    blocks."""
    fields = {"system": _prefix_blocks(params)}
    if params.get("tools"):
        fields["tools"] = params["tools"]
    output_format = (params.get("output_config") or {}).get("format")
    if output_format:
        fields["output_config"] = {"format": output_format}
    return fields


def split(params):
    """A request's cache key and the system text after its cached prefix.

    Requests share a cache entry only when their tools, output format and
    cached system blocks all match, so a translation request's entry differs
    for every line count its reply schema names. The key is "" when the
    request caches nothing.
    """
    blocks = params.get("system") or []
    if isinstance(blocks, str):
        return "", blocks
    cut = len(_prefix_blocks(params))
    if not cut:
        return "", _text(blocks)
    key = json.dumps(_prefix_fields(params), ensure_ascii=False, sort_keys=True)
    return key, _text(blocks[cut:])


def cached_text(params):
    """The text of a request's cached prefix, for an approximate count."""
    fields = _prefix_fields(params)
    return _text(fields["system"]) + "".join(
        json.dumps(fields[name], ensure_ascii=False)
        for name in ("tools", "output_config")
        if name in fields
    )


class Cache(NamedTuple):
    """Requests' cached prefixes, in tokens and as regular input tokens."""

    cached: int  # every request's cached prefix
    writes: int  # written once per cache key, when every later request reuses it
    reads: int  # then read by those later requests
    reused: float  # the cached prefixes priced as input when reused that way
    unreused: float  # priced as input when no request reuses one
    keys: int  # the cache keys (see split) the requests write


def cache(requests, provider, model, count_text, counted=None):
    """What the requests' cached prefixes cost, from every request that shares
    a cache key reusing it to none doing so.

    A Batch runs its requests independently and largely at once, and an
    entry is readable only once the request writing it has started to
    answer, so any request may write its prefix again instead of reading it.
    Each cache key (see split) counts once: Claude's count of it in
    ``counted`` (the Count or Inputs of these requests) when there is one,
    else ``count_text`` of its cached_text. Estimates reach this through
    util.translation.claude_prompt_cache, which names the approximate count.
    """
    groups = {}
    for params in requests:
        key = split(params)[0]
        if not key:
            continue
        group = groups.get(key)
        if group is None:
            tokens = (
                counted.prefixes[key]
                if counted is not None
                else count_text(cached_text(params))
            )
            group = groups[key] = [0, cache_ttl(params), tokens]
        group[0] += 1
    read = cache_read_multiplier(provider, model)
    cached = writes = reads = 0
    reused = unreused = 0.0
    for count, ttl, tokens in groups.values():
        write = cache_write_multiplier(provider, model, ttl)
        cached += tokens * count
        writes += tokens
        reads += tokens * (count - 1)
        reused += tokens * (write + (count - 1) * read)
        unreused += tokens * count * write
    return Cache(cached, writes, reads, reused, unreused, len(groups))


def spread(total, limit=SAMPLES):
    """Indexes of a repeatable, evenly spread sample."""
    if total <= limit:
        return list(range(total))
    return [round(index * (total - 1) / (limit - 1)) for index in range(limit)]


def count(client, requests, approximate):
    """Claude's count of each cached prefix and its scale for the rest.

    ``approximate`` holds each request's approximate token count after its
    prefix. Any failed count raises its error, so an estimate never mixes
    Claude's count with the approximate one.
    """
    if not requests:
        return None
    first = {}
    for params in requests:
        first.setdefault(split(params)[0], params)
    prefixes = [prefix for prefix in first if prefix]
    sample = spread(len(requests))
    jobs = [
        {
            "model": first[prefix]["model"],
            **_prefix_fields(first[prefix]),
            "messages": [{"role": "user", "content": "x"}],
        }
        for prefix in prefixes
    ] + [requests[index] for index in sample]

    def counted(params):
        fields = {key: params[key] for key in FIELDS if key in params}
        return int(client.messages.count_tokens(**fields).input_tokens)

    with ThreadPoolExecutor(min(WORKERS, len(jobs))) as pool:
        futures = [pool.submit(counted, params) for params in jobs]
        wait(futures, return_when=FIRST_EXCEPTION)
        failure = next(
            (future.exception() for future in futures if future.done() and future.exception()),
            None,
        )
        if failure is not None:
            # An unreachable endpoint fails every count; don't wait on the rest.
            pool.shutdown(cancel_futures=True)
            raise failure
        counts = [future.result() for future in futures]
    exact = {"": 0, **dict(zip(prefixes, counts))}
    measured = sum(
        max(0, whole - exact[split(requests[index])[0]])
        for index, whole in zip(sample, counts[len(prefixes):])
    )
    base = sum(approximate[index] for index in sample)
    return Count(exact, measured / base if base else 1.0, len(sample))


class Inputs(NamedTuple):
    total: int  # the requests' input tokens
    prefixes: dict  # cache key (see split) -> Claude tokens


def input_tokens(client, requests, count_text):
    """Claude's estimated input for whole requests and its count of each
    cached prefix, or None when it can't count them."""
    approximate = [
        count_text(split(params)[1])
        + count_text("\n".join(_text(message["content"]) for message in params.get("messages", [])))
        + 8
        for params in requests
    ]
    try:
        counted = count(client, requests, approximate)
    except Exception:
        return None
    if counted is None:
        return None
    total = sum(counted.prefixes[split(params)[0]] for params in requests) + round(
        counted.scale * sum(approximate)
    )
    return Inputs(total, counted.prefixes)
