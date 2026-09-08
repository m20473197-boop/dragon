"""Persian text helpers: digit conversion, cooldown formatting, command
normalization and the shared reward card."""
from __future__ import annotations

_PERSIAN_DIGITS = "۰۱۲۳۴۵۶۷۸۹"

# Emoji used for every reward line, so a reward looks the same everywhere
# (chests, battles, admin grants). Display only — no amounts or rules here.
REWARD_EMOJI: dict[str, str] = {
    "obsidian": "🪨",
    "aether": "✨",
    "meat": "🥩",
    "fish": "🐟",
    "xp": "⭐",
}

# Stable order so rewards never shuffle between messages.
REWARD_ORDER: tuple[str, ...] = ("xp", "obsidian", "aether", "meat", "fish")

REWARD_TITLE = "🎉 جایزه گرفتی!"


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


def format_reward_lines(rewards: dict) -> list[str]:
    """«🪨 +۵۰۰» style lines for a {key: amount} mapping (zeros skipped)."""
    lines = []
    for key in REWARD_ORDER:
        amount = rewards.get(key, 0)
        if amount:
            suffix = " XP" if key == "xp" else ""
            lines.append(f"{REWARD_EMOJI[key]} +{to_fa(amount)}{suffix}")
    return lines


def reward_card(rewards: dict, title: str = REWARD_TITLE, who: str | None = None) -> str:
    """A short reward message::

        🎉 جایزه گرفتی!

        🪨 +۵۰۰
        ✨ +۳

    ``who`` adds a «👤 <name>» line (used when a group announcement needs to
    say who received the reward).
    """
    lines = [title, ""]
    if who:
        lines += [f"👤 {who}", ""]
    lines += format_reward_lines(rewards)
    return "\n".join(lines)
