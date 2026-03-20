"""Qualytics ASCII logo."""

from rich.text import Text

# Column where the Q icon ends and the wordmark begins.
_SPLIT = 18

# fmt: off
# Wordmark traced from official logo, compact half-block rendering.
_LINES = [
    "   ▄████▀ ▄██▄                          ▄                 ▄     ▄",
    "  ██▀       ▀██                         ██                ██    ▀▀",
    " ██           ██  ██     ██   ▄████▄██  ██  ██      ██  ██████  ██   ▄██▀▀██▄   ▄█████▄",
    " ██           ██  ██     ██  ██     ██  ██   ██    ██     ██    ██  ██      ▀▀  ██▄▄▄",
    "  ██▄       ▄██   ██     ██  ██     ██  ██    ██▄▄██      ██    ██  ██      ▄▄    ▀▀▀██",
    "   ▀██████████▄▄  ▀█████▀██   ▀████▀██  ██     ▄█▀        ██    ██   ▀██▄▄██▀   ▀█████▀",
    "                                              ▄█▀",
    "                                              ▀▀",
]
# fmt: on

# Qualytics brand color
BRAND = "#FF9933"


def logo_lines() -> list[Text]:
    """Return the logo as a list of Rich Text objects with two-tone coloring."""
    result = []
    for line in _LINES:
        t = Text(line)
        t.stylize(f"bold {BRAND}", 0, _SPLIT)
        t.stylize("bold", _SPLIT)
        result.append(t)
    return result
