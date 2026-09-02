"""Measure WCAG contrast for both palettes.

Written because this project has twice shipped colours that looked fine and
failed AA -- a medium at 2.89:1, and two difficulty hues 3 degrees apart.
Numbers on the artboard must be measured, not asserted.
"""

from __future__ import annotations


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(hex_colour: str) -> float:
    h = hex_colour.lstrip("#")
    r, g, b = (int(h[i : i + 2], 16) / 255 for i in (0, 2, 4))
    return 0.2126 * _lin(r) + 0.7152 * _lin(g) + 0.0722 * _lin(b)


def ratio(fg: str, bg: str) -> float:
    a, b = luminance(fg), luminance(bg)
    lo, hi = sorted((a, b))
    return (hi + 0.05) / (lo + 0.05)


LIGHT = {
    "paper": "#f2efe4", "paper2": "#fbf9f2", "ink": "#1b1a17", "ink2": "#413d35",
    "mute": "#6f6858", "blue": "#2b4a8b", "oranget": "#b03c12",
    "easy": "#3f6b3a", "med": "#8a6410", "hard": "#9c3520",
}
DARK = {
    "paper": "#171612", "paper2": "#211f19", "ink": "#f1ede1", "ink2": "#c9c3b3",
    "mute": "#8e8776", "blue": "#89a9e4", "oranget": "#ff9d75",
    "easy": "#8fc088", "med": "#e0b45a", "hard": "#e69182",
}
FG = ["ink", "ink2", "mute", "blue", "oranget", "easy", "med", "hard"]


def report() -> None:
    for name, pal in (("LIGHT", LIGHT), ("DARK", DARK)):
      print(f"\n=== {name} ===")
      for surface in ("paper", "paper2"):
          print(f"  on {surface} {pal[surface]}")
          for key in FG:
              r = ratio(pal[key], pal[surface])
              # 4.5 is AA for body text; 3.0 is AA for large text and graphics.
              flag = "OK " if r >= 4.5 else ("lg " if r >= 3.0 else "FAIL")
              print(f"    {flag} {key:<8} {pal[key]}  {r:5.2f}:1")
      # The knockout block inverts: paper-coloured text on the blue.
      print(f"  knockout: {pal['paper2']} on {pal['blue']} = "
            f"{ratio(pal['paper2'], pal['blue']):.2f}:1")


if __name__ == "__main__":
    report()
