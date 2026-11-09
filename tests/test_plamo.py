"""PLaMo 3 Translate's request format (compatibility/plamo) in both methods."""

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from dazedtl.compatibility import plamo
from dazedtl.settings.preferences import GENERATION_PARAMETERS

import tests.engine  # noqa: F401  # The engine's packages, importable as util.

GLOSSARY = (
    "Here are glossary entries with the approved spelling and translation.\n"
    "# Game Characters\n"
    "ミカ / ミカちゃん (Mika) - Female; heroine\n"
    "魔王 (Demon => Lord)\n"
    "\n"
    "Japanese SFX reference (contextual suggestions, not approved fixed translations).\n"
    "ドキドキ (Thump-thump)\n"
)


def template_errors(body):
    """What PLaMo 3 Translate's chat template refuses in a chat request, as
    LM Studio renders it: tools and response formats, a settings block that
    isn't one, messages that don't alternate user and assistant ending with
    a user message, and blank or reserved text."""
    errors = [key for key in ("tools", "response_format") if key in body]
    messages = body["messages"]
    first = messages[0]
    if first["role"] != "system":
        errors.append("no settings block")
    else:
        lines = first["content"].split("\n")
        if lines[0] != "[plamo-translate]":
            errors.append("settings header")
        for line in lines[1:]:
            if line == "---":
                break
            key, _, value = line.partition("=")
            if key not in {"target_lang", "source_lang", "glossary"} or not value:
                errors.append(f"setting {line}")
            if key == "glossary" and len(value.split("=>")) != 2:
                errors.append(f"glossary {line}")
    for index, message in enumerate(messages[1:]):
        if message["role"] != ("user" if index % 2 == 0 else "assistant"):
            errors.append(f"message {index + 1} is {message['role']}")
        if not message["content"].strip() or "<|plamo:" in message["content"]:
            errors.append(f"message {index + 1} text")
    if messages[-1]["role"] != "user":
        errors.append("ends with " + messages[-1]["role"])
    return errors


def completion(text, prompt=10, output=3):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=output),
    )


class Server:
    """A chat client's create that answers as PLaMo through LM Studio:
    400-like errors for what the template refuses, else each reply given."""

    def __init__(self, *replies):
        self.replies, self.bodies = list(replies), []

    def create(self, **body):
        self.bodies.append(body)
        errors = template_errors(body)
        if errors:
            raise AssertionError(f"PLaMo's template refuses this request: {errors}")
        return completion(self.replies.pop(0))


class PlamoFormatTest(unittest.TestCase):
    def test_a_run_on_plamo_3_translate_freezes_its_format_by_model_name(self):
        for protocol, model, expected in (
            ("openai", "plamo-3-translate-8b", True),
            ("openai", "pfnet/plamo-3-translate-0.8b", True),
            ("openai", "PLaMo-3-Translate-8B@q4_k_m", True),
            ("openai", "plamo-2-translate", False),
            ("openai", "my-plamo-3-translate-tuned", False),
            ("anthropic", "plamo-3-translate-8b", False),
            ("openai", "gpt-6.1-sol", False),
        ):
            with self.subTest(model=model, protocol=protocol):
                frozen = plamo.policies(protocol, model)
                self.assertEqual("requestFormat" in frozen, expected)
                # PLaMo can't follow the clarification a refusal retry sends.
                self.assertEqual("refusalRetry" in frozen, not expected)
        self.assertEqual(plamo.code("Chinese (Simplified)"), "zh-hans")
        self.assertEqual(plamo.code("Portuguese (Brazil)"), "pt")
        self.assertEqual(plamo.code("Japanese"), "ja")

    def test_each_line_goes_alone_with_its_terms_and_the_pairs_before_it(self):
        params = plamo.document(
            {"Line1": "[ミカ]: おはよう！", "Line2": "魔王が来た。", "Line3": "はい。"},
            model="plamo-3-translate-8b",
            source="Japanese",
            target="English",
            vocab_text=GLOSSARY,
            context=["前の行。", "その前。"],
            delivered=["The line before.", ""],
        )
        # SFX suggestions aren't approved terms, and a term the settings line
        # can't hold is left out.
        self.assertEqual(params["glossary"], [["ミカ", "Mika"], ["ミカちゃん", "Mika"]])
        server = Server("[Mika]: Morning!", "", "Yes.")
        result = plamo.send(params, server.create)
        self.assertEqual([template_errors(body) for body in server.bodies], [[]] * 3)
        first, second, third = server.bodies
        self.assertEqual(
            first["messages"][0]["content"],
            "[plamo-translate]\ntarget_lang=en\nsource_lang=ja\n"
            "glossary=ミカ => Mika\n---\nその前。",
        )
        self.assertEqual(first["temperature"], 0)
        self.assertEqual(
            [message["content"] for message in first["messages"][1:]],
            ["前の行。", "The line before.", "[ミカ]: おはよう！"],
        )
        self.assertNotIn("glossary=", second["messages"][0]["content"])
        # A blank reply stays for validation to reject but is never a pair.
        self.assertEqual(
            [message["content"] for message in third["messages"][1:]],
            [
                "前の行。",
                "The line before.",
                "[ミカ]: おはよう！",
                "[Mika]: Morning!",
                "はい。",
            ],
        )
        self.assertEqual(
            json.loads(result["text"]),
            {"Line1": "[Mika]: Morning!", "Line2": "", "Line3": "Yes."},
        )
        self.assertEqual(
            (result["prompt_tokens"], result["completion_tokens"]), (30, 9)
        )
        # At most PAIRS earlier pairs go with a line.
        many = plamo.document(
            {f"Line{n}": f"行{n}" for n in range(1, 14)},
            model="plamo-3-translate-8b",
            source="Japanese",
            target="English",
        )
        server = Server(*(f"Line {n}" for n in range(1, 14)))
        plamo.send(many, server.create)
        self.assertEqual(len(server.bodies[-1]["messages"]), 2 + 2 * plamo.PAIRS)
        with self.assertRaisesRegex(ValueError, "reserved"):
            plamo.document(
                {"Line1": "<|plamo:op|>"},
                model="plamo-3-translate-8b",
                source="Japanese",
                target="English",
            )

    def test_a_guided_request_reaches_plamo_as_its_lines_without_instructions(self):
        # translateAI's call on a retry: a correction note before the JSON
        # payload, instructions, the preceding source and its delivered
        # English, the matched glossary with the SFX reference. PLaMo would
        # translate any of the text that isn't a line.
        from dazedtl.compatibility.request_parameters import configure_builders
        from util import translation

        recorded = []
        server = Server("[Mika]: Wait!", "Fine.")
        client = SimpleNamespace(
            DEFAULT_MAX_RETRIES=2,
            chat=SimpleNamespace(completions=SimpleNamespace(create=server.create)),
        )
        payload = json.dumps(
            {"Line1": "[ミカ]: 待って！", "Line2": "いいよ。"},
            indent=4,
            ensure_ascii=False,
        )
        configure_builders(
            translation,
            GENERATION_PARAMETERS,
            recorded.append,
            max_output_tokens=512,
            request_format=plamo.POLICY,
        )
        plamo.configure(translation, plamo.POLICY)
        try:
            with (
                patch.object(translation, "openai", client),
                patch.dict(
                    os.environ,
                    {
                        "API_PROVIDER": "openai",
                        "api": "http://127.0.0.1:1234/v1",
                        "key": "",
                        "language": "English",
                    },
                ),
            ):
                response = translation.translateText(
                    "System prompt",
                    "IMPORTANT: Your previous attempt was incorrect.\n\n```json\n"
                    + payload
                    + "\n```",
                    ["前の行。"],
                    0.05,
                    "json",
                    "plamo-3-translate-8b",
                    2,
                    vocab_text=GLOSSARY,
                    context_kind=translation.CONTEXT_SOURCE,
                    request_instructions=["Reply with only the NPC's name"],
                    delivered_context=["The line before."],
                )
                estimate = translation.requestTokens(
                    "System prompt",
                    GLOSSARY,
                    "```json\n" + payload + "\n```",
                    ["前の行。"],
                    [],
                )
        finally:
            configure_builders(translation, None)
            plamo.configure(translation, None)
        sent = json.dumps(server.bodies, ensure_ascii=False)
        for text in ("IMPORTANT", "System prompt", "NPC", "Thump"):
            self.assertNotIn(text, sent)
        self.assertEqual(
            recorded[0]["lines"], {"Line1": "[ミカ]: 待って！", "Line2": "いいよ。"}
        )
        self.assertEqual(server.bodies[0]["max_tokens"], 128)
        self.assertEqual(
            translation.extractTranslation(response.choices[0].message.content, True),
            ["[Mika]: Wait!", "Fine."],
        )
        # The estimate counts the calls PLaMo's format sends, before any
        # English is delivered, not the JSON request's prompt.
        counted = plamo.document(
            recorded[0]["lines"],
            model="",
            source="Japanese",
            target="English",
            vocab_text=GLOSSARY,
            context=["前の行。"],
        )
        self.assertEqual(
            estimate[0], translation.approximate_tokens(plamo.sent_text(counted))
        )

    def test_an_assistant_led_request_maps_plamos_replies_back_to_its_units(self):
        from dazedtl.compatibility.translation import (
            TranslationProvider,
            request_payload,
        )
        from dazedtl.translation.requests import (
            delivered_params,
            from_provider,
            logical_request,
            sent_text,
        )

        request = logical_request(
            {"id": "scene", "sources": {"u1": "[ミカ]: はい。", "u2": "いいえ。"}},
            {
                "user": "Lines:",
                "system": "Translate.",
                "glossary": GLOSSARY,
                "sfx_reference": "",
                "preceding_japanese_source_context": ["前の行。"],
                "request_instructions": "Keep it short.",
            },
        )
        configuration = {
            "requestFormat": plamo.POLICY,
            "protocol": "openai",
            "provider": "lmstudio",
            "mode": "live",
            "model": "plamo-3-translate-8b",
        }
        params = request_payload(request, configuration)
        self.assertEqual(params["lines"], {"u1": "[ミカ]: はい。", "u2": "いいえ。"})
        self.assertEqual(sent_text(params), plamo.sent_text(params))
        params = delivered_params(params, ["The line before."], request["context"])
        provider = object.__new__(TranslationProvider)
        server = Server("[Mika]: Yes.", "No.")
        provider.client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=server.create))
        )
        result = provider.live(params)
        self.assertEqual(
            server.bodies[0]["messages"][1:3],
            [
                {"role": "user", "content": "前の行。"},
                {"role": "assistant", "content": "The line before."},
            ],
        )
        self.assertNotIn("Keep it short", json.dumps(server.bodies, ensure_ascii=False))
        self.assertEqual(
            json.loads(from_provider(request, configuration, result["text"])),
            {"u1": "[Mika]: Yes.", "u2": "No."},
        )
        with self.assertRaisesRegex(ValueError, "request format"):
            request_payload(request, {**configuration, "mode": "batch"})


if __name__ == "__main__":
    unittest.main()
