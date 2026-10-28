"""The release playtest: its static checks, how the tour's findings join them,
and when its half of the final check settles for either method."""

import json
import unittest
from types import SimpleNamespace
from unittest import mock

from dazedtl.api.contracts.guided import PlaytestStatus
from dazedtl.api.contracts.validation import _close_contracts
from dazedtl.translation.playtest import Playtest, described
from pydantic import TypeAdapter

from tests.probe import Probe

# The checks import the engine's `util` package, which would clash with the
# fakes other tests install, so they run in their own interpreter.
checks = Probe("playtest_checks.py")


def report(review="waiting", **fields):
    return {
        "report": "r",
        "current": True,
        "played": True,
        "problems": [{"kind": "fit", "fix": "text-qa", "review": review}],
        "gaps": [],
        **fields,
    }


class PlaytestTests(unittest.TestCase):
    def test_checks_and_tour_find_what_text_qa_cannot(self):
        returncode, output = checks.result()
        self.assertEqual(returncode, 0, output)

    def test_text_problems_after_qa_send_either_method_to_its_next_round(self):
        for method in ("guided", "len"):
            text = {"qa": {"status": {"stage": "complete"}}}
            helper = Playtest(
                SimpleNamespace(
                    backend=SimpleNamespace(guided_text_state=lambda *_: text),
                    projects=SimpleNamespace(get=lambda _id: {"method": method}),
                ),
                SimpleNamespace(focus=lambda _id: "release"),
            )
            with (
                mock.patch.object(helper, "operation", return_value=None),
                mock.patch.object(
                    helper, "fixes", return_value={"file": "f", "in_game": False}
                ),
                mock.patch.object(helper, "layout", return_value=None),
                mock.patch.object(helper, "stops", return_value=[]),
            ):
                text["playtest"] = described(report(), False)
                status = helper.status("p", {})
                _close_contracts()
                TypeAdapter(PlaytestStatus).validate_json(
                    json.dumps(status), strict=True
                )
                self.assertEqual((status["waiting"], status["settled"]), (1, False))
                self.assertIn("run qa --prepare", status["next"], method)
                # QA's next round took the problem, so a play after its apply
                # settles the check.
                text["playtest"] = described(report("reviewing"), False)
                self.assertTrue(helper.status("p", {})["settled"], method)

    def test_the_final_check_settles_only_on_a_current_quiet_play(self):
        crash = {"kind": "crash", "fix": "game"}
        cases = {
            "nothing waits": (report("reviewing"), False, True),
            "a play runs": (report("reviewing"), True, False),
            "text waits for QA": (report(), False, False),
            "the game changed": (report(current=False), False, False),
            "no report": ({"current": False, "problems": [], "gaps": []}, False, False),
            "unreadable": (report("reviewing", unreadable="x"), False, False),
            "a crash stops it": (
                report(played=False, problems=[crash]),
                False,
                False,
            ),
            "it could not play, with nothing to fix": (
                report(played=False, problems=[]),
                False,
                True,
            ),
            "it played, a crash among its problems": (
                report(problems=[crash]),
                False,
                True,
            ),
        }
        for name, (state, running, expected) in cases.items():
            self.assertEqual(described(state, running)["settled"], expected, name)
        # Only a crash that kept the tour from playing stops the check, so
        # both methods' Playtest panels read Blocked for it and no other.
        stopping = [
            described(report(played=played, problems=[crash]), False)["stopping"]
            for played in (False, True)
        ]
        self.assertEqual(stopping, [1, 0])
        # A report the game outgrew holds no text for QA's next round.
        self.assertEqual(described(report(current=False), False)["waiting"], 0)
