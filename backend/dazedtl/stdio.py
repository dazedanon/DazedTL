"""Keeps a process's input pipe away from the processes it starts."""

import os


def private_stdin():
    """Moves standard input to a descriptor that children cannot inherit.

    A child receives the standard input handle unless told otherwise, and on
    Windows its startup blocks while another process waits to read that pipe,
    which froze every per-file translation worker until the next command
    arrived. Standard input becomes the null device; the returned stream keeps
    reading the original pipe.
    """
    channel = os.fdopen(os.dup(0), "r", encoding="utf-8")
    null = os.open(os.devnull, os.O_RDONLY)
    os.dup2(null, 0)
    os.close(null)
    return channel
