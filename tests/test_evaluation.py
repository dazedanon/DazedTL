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


if __name__ == "__main__":
    unittest.main()
