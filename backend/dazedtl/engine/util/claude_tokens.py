"""Claude's own count of an estimate's input tokens.

Estimates count text with the GPT-4 encoder for every provider, but Claude's
tokenizer turns the same text into more tokens and Anthropic bills by its own
count. Its token-count endpoint is free and exact for one request, so a Claude
estimate counts each cached instruction prefix once and an evenly spread
sample of whole requests, then scales the approximate count of everything
after the prefix by what the sample measured.
"""

import os
import random
import time
from concurrent.futures import FIRST_EXCEPTION, ThreadPoolExecutor, wait
from types import SimpleNamespace
from typing import NamedTuple

import httpx

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
    uses it as ``client.messages.count_tokens(**fields).input_tokens``."""

    def __init__(self, api_key, base_url=None, *, timeout=30.0):
        base = (base_url or os.environ.get("ANTHROPIC_BASE_URL") or "https://api.anthropic.com")
        base = base.strip().rstrip("/")
        if base.endswith("/v1"):
            base = base[:-3]
        self.url = base + "/v1/messages/count_tokens"
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
    prefixes: dict  # cached prefix text -> Claude tokens
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


def split(params):
    """A request's cached system prefix and the system text after it."""
    blocks = params.get("system") or []
    if isinstance(blocks, str):
        return "", blocks
    cut = len(_prefix_blocks(params))
    return _text(blocks[:cut]), _text(blocks[cut:])


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
            "system": _prefix_blocks(first[prefix]),
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


def input_tokens(client, requests, count_text):
    """Claude's estimated input for whole requests, or None when it can't count them."""
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
    return sum(counted.prefixes[split(params)[0]] for params in requests) + round(
        counted.scale * sum(approximate)
    )
