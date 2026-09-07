"""Persian text helpers: digit conversion, cooldown formatting, command
normalization."""
from __future__ import annotations

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"


def to_fa(number: int | str) -> str:
    """Convert Latin digits in ``number`` to Persian digits."""
    return "".join(
        _PERSIAN_DIGITS[int(ch)] if ch.isdigit() else ch for ch in str(number)
    )


def format_remaining(seconds: int) -> str:
    """Human-friendly Persian cooldown, e.g. «۵ دقیقه و ۲۰ ثانیه»."""
    seconds = max(0, int(seconds))
    if seconds < 60:
        return f"{to_fa(seconds)} ثانیه"
    minutes, secs = divmod(seconds, 60)
    if secs == 0:
        return f"{to_fa(minutes)} دقیقه"
    return f"{to_fa(minutes)} دقیقه و {to_fa(secs)} ثانیه"


def normalize_command(text: str | None) -> str:
    """Normalize incoming text for command matching.

    * strips whitespace
    * turns the Persian semi-space (نیم‌فاصله, U+200C) into a regular space,
      so «تخم‌ها» and «تخم ها» both match
    * collapses repeated spaces
    """
    if not text:
        return ""
    return " ".join(text.replace("\u200c", " ").split())
