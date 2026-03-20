"""Qualytics ASCII logo."""

from rich.text import Text

# Column where the Q icon ends and the wordmark begins.
_SPLIT = 18

# fmt: off
# Wordmark traced from official logo, compact half-block rendering.
_LINES = [
    "   ▄█████ ▄██▄                          ▄                 ▄     ▄",
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

# Horizontal gradient stops for the Q icon (left → right).
# #B83200 → #F96719 → brand → near-white to suggest fade into terminal default.
_STOPS = [
    (0xB8, 0x32, 0x00),  # #B83200
    (0xF9, 0x67, 0x19),  # #F96719
    (0xFF, 0x99, 0x33),  # #FF9933 (brand)
    (0xFF, 0xCC, 0x88),  # light warm tone – bridges brand to default
]


def _gradient_color(t: float) -> str:
    """Map t (0..1) to a color along the multi-stop gradient."""
    if t <= 0:
        r, g, b = _STOPS[0]
    elif t >= 1:
        r, g, b = _STOPS[-1]
    else:
        # Scale t to the number of segments.
        seg = t * (len(_STOPS) - 1)
        i = int(seg)
        f = seg - i
        a, b_ = _STOPS[i], _STOPS[min(i + 1, len(_STOPS) - 1)]
        r = int(a[0] + (b_[0] - a[0]) * f)
        g = int(a[1] + (b_[1] - a[1]) * f)
        b = int(a[2] + (b_[2] - a[2]) * f)
    return f"#{r:02x}{g:02x}{b:02x}"


def logo_lines() -> list[Text]:
    """Return the logo with a horizontal gradient on the Q icon.

    Q icon: left-to-right #B83200 → #F96719 → #FF9933 → light warm tone.
    Wordmark: terminal default foreground.
    """
    result = []
    for line in _LINES:
        t = Text(line)
        for col in range(min(_SPLIT, len(line))):
            color = _gradient_color(col / max(_SPLIT - 1, 1))
            t.stylize(f"bold {color}", col, col + 1)
        result.append(t)
    return result
