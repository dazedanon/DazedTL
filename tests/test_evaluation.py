"""Evaluation pricing, with no provider or pricing catalog."""

import unittest
from unittest.mock import patch

from util import evaluation


class EvaluationPricingTest(unittest.TestCase):
    def test_claude_rates_follow_each_model_not_an_older_id_it_starts_with(self):
        # Claude Sonnet 5.5 once got Sonnet 5's pinned rates, and catalog
        # models' cache reads cost 0.1x input whatever the model's own rate.
        catalog = {"inputAPICost": 2, "outputAPICost": 10}
        with patch.object(
            evaluation, "getPricingConfig", return_value=catalog
        ) as lookup:
            self.assertEqual(
                evaluation.pricing_for("claude-sonnet-5", "anthropic"),
                {"input": 1.0, "cached_input": 0.1, "output": 5.0},
            )
            lookup.assert_not_called()
            for model, cached in (
                ("claude-sonnet-5-5", 0.05),
                ("claude-fable-5-1", 0.025),
            ):
                self.assertEqual(
                    evaluation.pricing_for(model, "anthropic"),
                    {"input": 1.0, "cached_input": cached, "output": 5.0},
                )
            # Routes other than Anthropic's own API keep 0.1x reads.
            self.assertEqual(
                evaluation.pricing_for("claude-sonnet-5-5", "openai")["cached_input"],
                0.1,
            )


class EvaluationRequestTest(unittest.TestCase):
    def test_reply_limit_field_follows_the_engines_rule(self):
        # The legacy evaluation's translation and judge requests chose the
        # field by their own copies of the rule (settings/providers
        # completion_field): Kimi's API got max_tokens, which it deprecates,
        # and any address holding "api.openai.com" counted as OpenAI's.
        from util import evaluation_quality

        request = {
            "system": "Translate.",
            "user": "薬",
            "history": [],
            "glossary": "",
            "schema_line_count": 1,
        }
        for endpoint, execution, field in (
            ("https://api.openai.com/v1", "batch", "max_completion_tokens"),
            ("https://api.openai.com/v1", "live", "max_completion_tokens"),
            ("https://api.moonshot.ai/v1", "live", "max_completion_tokens"),
            ("https://proxy.example/api.openai.com/v1", "live", "max_tokens"),
            ("http://localhost:1234/v1", "live", "max_tokens"),
        ):
            with self.subTest(endpoint=endpoint, execution=execution):
                candidate = {
                    "provider": "openai",
                    "endpoint": endpoint,
                    "model": "kimi-k3",
                    "execution": execution,
                    "max_output_tokens": 4096,
                }
                params = evaluation._provider_params(candidate, request)
                self.assertEqual(params.get(field), 4096)
                self.assertEqual(
                    {"max_tokens", "max_completion_tokens"} & params.keys(), {field}
                )
                judge = evaluation_quality._judge_params(
                    {
                        **candidate,
                        "effort": None,
                        "prompts": {"defect": "Judge."},
                    },
                    "defect",
                    "Line.",
                )
                self.assertEqual(judge.get(field), 4096)
                self.assertEqual(
                    {"max_tokens", "max_completion_tokens"} & judge.keys(), {field}
                )


if __name__ == "__main__":
    unittest.main()
