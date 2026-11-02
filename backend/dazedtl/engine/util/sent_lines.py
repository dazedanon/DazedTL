"""The lines a plain engine module sends in one request list, each with the
place its reply goes.

A module (Text, Tyrano, Kirikiri, Lune, YU-RIS, Regex, CSV, WOLF RPG 2,
JSON, RPG Maker plugin) walks its file once. For each line to translate it
calls SentLines.send with the text, the speaker who says it and a function
that writes the reply where the text came from; SentLines.lines is the
request list; SentLines.write hands each reply to its line's function. A module therefore never walks its file a second
time to find where its replies go, which is how a second walk came to
disagree with the first about which lines it had sent and moved each later
reply to the line after its own.

Its rules hold for every module on it:

* Text of spaces alone sends nothing and takes no reply.
* A line said by a speaker is sent as ``[Speaker]: line`` (util/speakers
  to_prefixed), and its reply is written without that label.
* Replies go to the lines in the order they were sent, by util/translation
  reply_to_write: a reply list of another length writes nothing and counts
  as the file's mismatch, and a reply that came back as its line was sent
  keeps the line's source text, where the reply would be written over it.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import NamedTuple

from util.speakers import strip_speaker_prefix, to_prefixed
from util.translation import reply_to_write


class _Sent(NamedTuple):
    line: str
    speaker: str
    write: Callable[[str], None]


class SentLines:
    """The lines one request list sends and where each reply goes.

    *unlabel(reply, speaker)* reads a reply without the label its line was
    sent with: strip_speaker_prefix unless the module reads labels its own
    way, or None for a list whose replies are written as they come, such as
    choices sent without speakers.

    *over_source* is False for a module that writes each reply beside its
    line's source text rather than over it, such as to CSV's target column:
    a reply that came back as sent is then written as well, since what it
    replaces is not the source."""

    def __init__(
        self,
        unlabel: Callable[[str, str], str] | None = strip_speaker_prefix,
        over_source: bool = True,
    ):
        self._sent: list[_Sent] = []
        self._unlabel = unlabel
        self._over_source = over_source

    def send(self, text: str, write: Callable[[str], None], speaker: str = "") -> None:
        """Sends *text*, said by *speaker*, and gives its reply to *write*.
        Text of spaces alone sends nothing, so it takes no reply."""
        if text.strip():
            self._sent.append(_Sent(to_prefixed(speaker, text), speaker, write))

    @property
    def lines(self) -> list[str]:
        """The request list, in the order the lines were sent."""
        return [sent.line for sent in self._sent]

    def __len__(self) -> int:
        return len(self._sent)

    def write(self, replies: list[str], mismatches: list, lock, filename: str) -> bool:
        """Writes each reply, without its line's label, where its line came
        from, and whether it wrote: a reply list of another length writes
        nothing, and *filename* joins the module's *mismatches* under its
        *lock* (reply_to_write)."""
        kept = reply_to_write(replies, self.lines, mismatches, lock, filename)
        if kept is None:
            return False
        for sent, written, reply in zip(self._sent, kept, replies):
            if written is None and self._over_source:
                continue
            if self._unlabel is not None:
                reply = self._unlabel(reply, sent.speaker)
            sent.write(reply)
        return True
