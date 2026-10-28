#!/usr/bin/env python3
"""Check DazedTL's thinking effort table against the providers' real APIs.

Sends one short request for every row of the table (backend/dazedtl/settings/
effort.py): each model once without an effort, as runs that leave it to the
provider send, and once at each level the table says it takes, written as
runs write it. It reports each request as accepted, refused with the
provider's reason, or failed, and any default a reply names that differs from
the table, so the table can be corrected and its confirmed dates set.

Keys come only from the environment, one per provider (KEYS below); a
provider without one is skipped. Without --confirm it prints the planned
requests and their cost cap and sends nothing. It never reads the app's
saved keys and never prints a key. Run it with the setup's Python:

    .venv/bin/python scripts/effort_check.py [--provider NAME] [--confirm]
"""

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
from dazedtl.settings import effort, providers

KEYS = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "gemini": "GEMINI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "kimi": "MOONSHOT_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}
# The cap assumes no request reads more input tokens, and no model charges
# more per million tokens, than these.
INPUT_TOKENS = 100
INPUT_RATE = 30
OUTPUT_RATE = 200


def plan(only):
    """The rows to send, by provider: (model, levels, default, confirmed)."""
    rows = {}
    for provider, model, levels, default, confirmed in effort.table():
        if not only or provider in only:
            rows.setdefault(provider, []).append((model, levels, default, confirmed))
    return rows


def connection(provider, key):
    definition = providers.PROVIDERS[provider]
    return {
        "provider": provider,
        "protocol": definition["protocol"],
        "endpoint": "",
        "secret": key,
        "keyless": False,
        "organization": "",
    }


def main(argv=None, environ=None, out=sys.stdout):
    environ = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(
        description="Send one short request per row of DazedTL's thinking effort table."
    )
    parser.add_argument(
        "--provider",
        action="append",
        choices=sorted(KEYS),
        help="Check only this provider's rows; repeat for more.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Send the planned requests. Without it nothing is sent.",
    )
    args = parser.parse_args(argv)

    def say(text=""):
        print(text, file=out, flush=True)

    rows = plan(set(args.provider or ()))
    sending = {
        provider: models
        for provider, models in rows.items()
        if environ.get(KEYS[provider], "").strip()
    }
    count = sum(
        1 + len(levels) for models in sending.values() for _model, levels, *_ in models
    )
    say(
        f"Each request asks {providers.CHECK_PROMPT!r} with its reply, thinking "
        f"included, cut off at {providers.CHECK_TOKENS} tokens: once with no "
        "effort, then once at each level the table lists."
    )
    for provider, models in rows.items():
        key = KEYS[provider]
        say()
        say(
            f"{provider}: {len(models)} models, with {key}"
            if provider in sending
            else f"{provider}: skipped, {key} is not set"
        )
        for model, levels, default, confirmed in models:
            listed = ", ".join(["no effort", *levels])
            say(
                f"  {model}: {listed}; default {default or 'unknown'}; "
                f"confirmed {confirmed or 'never'}"
            )
    cap = (
        count * (INPUT_TOKENS * INPUT_RATE + providers.CHECK_TOKENS * OUTPUT_RATE) / 1e6
    )
    say()
    say(
        f"Cost cap: {count} requests x ({INPUT_TOKENS} input + "
        f"{providers.CHECK_TOKENS} output tokens) at up to ${INPUT_RATE} input "
        f"and ${OUTPUT_RATE} output per million tokens = ${cap:.2f}. "
        "Refused requests are not billed."
    )
    if not args.confirm:
        say("Nothing was sent. Run again with --confirm to send these requests.")
        return 0
    if not count:
        say("Nothing to send: set the key of each provider to check.")
        return 1

    refused, failed, defaults, confirmed = [], [], [], []
    for provider, models in sending.items():
        server = connection(provider, environ[KEYS[provider]].strip())
        for model, levels, default, _date in models:
            outcomes = []
            for level in (None, *levels):
                result = providers.check_effort(server, model, level)
                name = level or "no effort"
                outcomes.append(result["status"])
                say(f"{provider} {model} {name}: {result['message']}")
                if result["status"] == "refused":
                    refused.append(f"{provider} {model} {name}: {result['message']}")
                elif result["status"] == "failed":
                    failed.append(f"{provider} {model} {name}: {result['message']}")
                elif level is None and result.get("applied") not in (None, default):
                    defaults.append(
                        f"{provider} {model}: the reply names {result['applied']}, "
                        f"the table {default or 'no default'}"
                    )
            if all(status == "accepted" for status in outcomes):
                confirmed.append(f"{provider} {model}")

    say()
    say(f"Refused ({len(refused)}): the table lists levels these refuse.")
    for line in refused:
        say("  " + line)
    say(f"Failed ({len(failed)}): these could not say, so their rows stay unconfirmed.")
    for line in failed:
        say("  " + line)
    say(
        f"Defaults that differ ({len(defaults)}): most replies name none, "
        "so the table's defaults stay as each provider documents them."
    )
    for line in defaults:
        say("  " + line)
    today = datetime.now(UTC).date().isoformat()
    say(
        f"Confirmed ({len(confirmed)}): set each row's date to {today} in "
        "backend/dazedtl/settings/effort.py."
    )
    for line in confirmed:
        say("  " + line)
    if any(provider == "openrouter" for provider in sending):
        say(
            "OpenRouter maps a level a model doesn't list to the nearest one it "
            "does, so its accepted rows confirm only that the request is taken."
        )
    return 0 if not refused and not failed else 1


if __name__ == "__main__":
    sys.exit(main())
