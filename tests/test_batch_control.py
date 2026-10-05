"""Cancel and partial-result recovery must never destroy receipts or resubmit."""

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import Mock, patch

from dazedtl.compatibility import batch_control, process_view, request_scope
from dazedtl.storage import write_json
from dazedtl.translation.files import read_json


class BatchControlTests(unittest.TestCase):
    def test_cancel_binds_provider_request_scope_and_retains_every_local_artifact(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            batch = {
                "id": "paid",
                "provider": "openai",
                "key_name": "original-account",
                "custom_ids": {"one": "key-one"},
            }
            write_json(root / "log/batch_history.json", {"batches": [batch]})
            write_json(
                root / "log/batch_state.json",
                {"status": "submitted", "batches": [batch]},
            )
            write_json(
                root / "log/batch_requests.json",
                {"key-one": {"payload": '{"Line1":"薬"}', "params": {}}},
            )
            before = {
                path: path.read_bytes() for path in root.rglob("*") if path.is_file()
            }
            provider = Mock()
            provider.status.return_value = {"api_status": "in_progress"}
            provider.cancel.return_value = {"id": "paid", "status": "cancelling"}
            resolve = Mock(
                return_value={
                    "secret": "fixture",
                    "endpoint": "https://fixture.invalid",
                    "organization": "",
                }
            )
            with patch.object(
                batch_control, "TranslationProvider", return_value=provider
            ) as create:
                with self.assertRaises(ValueError):
                    batch_control.cancel(
                        root, "foreign", batch_control.binding(batch), resolve
                    )
                with self.assertRaises(ValueError):
                    batch_control.cancel(root, "paid", "changed-scope", resolve)
                create.assert_not_called()
                result = batch_control.cancel(
                    root, "paid", batch_control.binding(batch), resolve
                )
                self.assertTrue(result["requested"])
                resolve.assert_called_once_with(batch)
                provider.cancel.assert_called_once_with("paid")
                provider.client.close.assert_called_once()
                for status in ("completed", "cancelled", "cancelling"):
                    provider.status.return_value = {"api_status": status}
                    self.assertFalse(
                        batch_control.cancel(
                            root, "paid", batch_control.binding(batch), resolve
                        )["requested"]
                    )
                self.assertEqual(provider.cancel.call_count, 1)
            self.assertEqual(
                before,
                {path: path.read_bytes() for path in root.rglob("*") if path.is_file()},
            )
            provider.submit.assert_not_called()
            provider.live.assert_not_called()
            batch["provider"] = "openrouter"
            write_json(root / "log/batch_history.json", {"batches": [batch]})
            with patch.object(batch_control, "TranslationProvider") as create:
                with self.assertRaisesRegex(
                    ValueError, "does not expose Batch cancellation"
                ):
                    batch_control.cancel(
                        root, "paid", batch_control.binding(batch), resolve
                    )
                create.assert_not_called()

    def test_terminal_collection_keeps_paid_successes_and_releases_only_proven_unsuccessful_requests(
        self,
    ):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            batch = {
                "id": "paid",
                "provider": "openai",
                "custom_ids": {"one": "key-one", "two": "key-two"},
            }
            write_json(root / "log/batch_history.json", {"batches": [batch]})
            write_json(
                root / "log/batch_state.json",
                {
                    "status": "partially_submitted",
                    "batches": [batch],
                    "run_id": "original",
                },
            )
            queue = {
                key: {
                    "payload": '{"Line1":"' + text + '"}',
                    "params": {},
                    "dazedtl_sources": [key],
                    "dazedtl_file": "Items.json",
                }
                for key, text in [
                    ("key-one", "薬"),
                    ("key-two", "毒"),
                    ("unsent", "盾"),
                ]
            }
            write_json(root / "log/batch_requests.json", queue)
            frozen = {
                path: path.read_bytes() for path in root.rglob("*") if path.is_file()
            }
            provider = Mock()
            provider.status.return_value = {"api_status": "cancelling"}
            provider.collect_terminal.return_value = (
                {"key-one": {"text": '{"Line1":"Medicine"}'}},
                ["two"],
                {"input_tokens": 5, "output_tokens": 2},
            )
            resolve = lambda _: {
                "secret": "fixture",
                "endpoint": "https://fixture.invalid",
                "organization": "",
            }
            with patch.object(
                batch_control, "TranslationProvider", return_value=provider
            ):
                with self.assertRaisesRegex(ValueError, "still working"):
                    batch_control.collect(root, resolve)
                self.assertEqual(
                    frozen,
                    {
                        path: path.read_bytes()
                        for path in root.rglob("*")
                        if path.is_file()
                    },
                )
                provider.collect_terminal.assert_not_called()
                provider.status.return_value = {
                    "api_status": "cancelled",
                    "counts": {
                        "succeeded": 1,
                        "canceled": 1,
                        "processing": 0,
                        "errored": 0,
                        "expired": 0,
                    },
                }
                self.assertEqual(batch_control.collect(root, resolve)["received"], 1)
                self.assertEqual(
                    (root / "log/batch_requests.json").read_bytes(),
                    frozen[root / "log/batch_requests.json"],
                )
                self.assertEqual(
                    read_json(root / "log/batch_state.json")["status"], "fetched"
                )
                rows = list(
                    request_scope.requests(
                        root, {"mode": "batch", "dazedtl_submission_intent": True}
                    )
                )
                self.assertEqual(
                    [row["state"] for row in rows], ["received", "failed", "queued"]
                )
                summary = process_view.summary(root, {"mode": "batch"})
                self.assertTrue(summary["resultsCollected"])
                self.assertEqual(summary["batches"][0]["total"], 2)
                self.assertEqual(summary["batches"][0]["status"], "cancelled")
                # Repeated collection may re-read; it cannot rewrite a different
                # saved response or turn a download into another paid request.
                batch_control.collect(root, resolve)
                saved = (root / "log/batch_results.json").read_bytes()
                provider.collect_terminal.return_value = (
                    {"key-one": {"text": "Different paid response"}},
                    [],
                    {},
                )
                with self.assertRaisesRegex(ValueError, "conflict"):
                    batch_control.collect(root, resolve)
                self.assertEqual((root / "log/batch_results.json").read_bytes(), saved)
            provider.submit.assert_not_called()
            provider.live.assert_not_called()
            provider.cancel.assert_not_called()
