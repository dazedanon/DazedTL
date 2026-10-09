"""Notices work that stops making progress, so a hang leaves a diagnostic."""

import sys
import threading
import time
from contextlib import suppress


class Watchdog:
    """Watches the thread that creates it for work that goes quiet.

    ``report(state, label, seconds, frame)`` receives "stalled" with the
    watched thread's current frame once a quiet period reaches ``threshold``
    seconds, then "resumed" with the period's length at the next progress or
    when the work ends. Each quiet period reports once and each piece of work
    at most ``limit`` times, so slow work cannot fill the bounded diagnostics.
    A failing report never reaches the work.
    """

    def __init__(self, threshold, report, limit=3):
        self.threshold = threshold
        self.report = report
        self.limit = limit
        self.thread = threading.get_ident()
        self.condition = threading.Condition()
        self.label = None
        self.since = 0.0
        self.stalled = False
        self.reports = 0
        threading.Thread(target=self._watch, name="watchdog", daemon=True).start()

    def busy(self, label):
        """Starts watching a piece of work."""
        with self.condition:
            self._resume()
            self.label, self.since, self.reports = label, time.monotonic(), 0
            self.condition.notify()

    def beat(self):
        """Records progress on the current work."""
        with self.condition:
            self._resume()
            self.since = time.monotonic()

    def idle(self):
        """Stops watching until the next piece of work."""
        with self.condition:
            self._resume()
            self.label = None

    def _resume(self):
        if self.stalled:
            self.stalled = False
            with suppress(Exception):
                self.report("resumed", self.label, time.monotonic() - self.since, None)
            self.condition.notify()

    def _watch(self):
        with self.condition:
            while True:
                if self.label is None or self.stalled or self.reports >= self.limit:
                    self.condition.wait()
                    continue
                remaining = self.since + self.threshold - time.monotonic()
                if remaining > 0:
                    self.condition.wait(remaining)
                    continue
                self.stalled = True
                self.reports += 1
                # Reported while holding the condition, so "resumed" follows it.
                with suppress(Exception):
                    self.report(
                        "stalled",
                        self.label,
                        time.monotonic() - self.since,
                        sys._current_frames().get(self.thread),
                    )
