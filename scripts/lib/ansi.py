"""Tiny ANSI helpers for gate output. No external deps."""

from __future__ import annotations

import sys

_RESET = "\033[0m"
_GREEN = "\033[1;32m"
_RED = "\033[1;31m"
_YELLOW = "\033[1;33m"
_BLUE = "\033[1;34m"
_BOLD = "\033[1m"
_DIM = "\033[2m"


def _isatty() -> bool:
    return sys.stdout.isatty()


def _wrap(s: str, code: str) -> str:
    if not _isatty():
        return s
    return f"{code}{s}{_RESET}"


def ok(msg: str) -> None:
    print(_wrap("✓", _GREEN), msg)


def fail(msg: str) -> None:
    print(_wrap("✗", _RED), msg, file=sys.stderr)


def warn(msg: str) -> None:
    print(_wrap("!", _YELLOW), msg)


def info(msg: str) -> None:
    print(_wrap("•", _BLUE), msg)


def header(msg: str) -> None:
    print()
    print(_wrap(msg, _BOLD))


def dim(msg: str) -> str:
    return _wrap(msg, _DIM)
