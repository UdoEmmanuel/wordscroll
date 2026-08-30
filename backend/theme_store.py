"""
Disk-persisted (backend/data/theme.json) display theme — how the verse
display looks on the NDI output and HTML overlay (font, colors, sizing,
position, background, shadow). One shared source of truth for both render
paths, via FONT_REGISTRY below (Pillow needs a .ttf file path; the overlay
just needs a CSS font-family name).
"""
from typing import Optional

import json_store

_FILENAME = "theme.json"

THEME_ASSETS_DIR = json_store.DATA_DIR / "theme_assets"
THEME_ASSETS_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_FONT_KEY = "segoe-ui-bold"
DEFAULT_LAYOUT_KEY = "lower-third"

# "lower-third" reproduces today's exact hardcoded constants (0.78 width
# fraction, 8% frame margin, 40px padding at the default verseMargin) so
# shipping this causes zero visual change to existing themes. "full-frame"
# is a much larger, more prominent centered card.
LAYOUT_PRESETS: dict[str, dict] = {
    "lower-third": {
        "label": "Lower Third",
        "maxWidthFraction": 0.78,
        "maxHeightFraction": 0.42,
        "paddingMultiplier": 1.0,
        "marginFraction": 0.08,
        "fontBoost": 1.0,
        # The background box hugs the text tightly (sized to the widest
        # line), like a caption card — not a full-bleed background.
        "fullBleed": False,
    },
    "full-frame": {
        "label": "Full Frame",
        "maxWidthFraction": 0.90,
        "maxHeightFraction": 0.82,
        "paddingMultiplier": 1.3,
        "marginFraction": 0.03,
        # Auto-fit only ever *shrinks* text down from its starting ceiling
        # (never grows it) — without this boost, a short verse at the
        # operator's normal font size would leave "Full Frame" looking just
        # like "Lower Third" with extra padding, never actually filling the
        # frame. This raises the ceiling substantially so Full Frame reads
        # as genuinely prominent by default, while auto-fit still shrinks
        # it back down for a long verse.
        "fontBoost": 2.0,
        # Unlike "lower-third", the background spans (almost) the entire
        # frame regardless of text length — a full-bleed card, not a box
        # hugging the text — so it never looks like a small caption with
        # black space around it. The text is then large and centered
        # within that full-bleed area.
        "fullBleed": True,
    },
}

# Windows-only (NFR-3) curated font list. Pillow needs an actual file under
# C:\Windows\Fonts; the overlay just needs a CSS font-family name — kept
# together here so nothing can drift out of sync between the two renderers.
FONT_REGISTRY: dict[str, dict] = {
    "segoe-ui-bold": {
        "label": "Segoe UI Bold",
        "ttf": "segoeuib.ttf",
        "cssFamily": "'Segoe UI', system-ui, sans-serif",
        "cssWeight": 700,
    },
    "segoe-ui": {
        "label": "Segoe UI",
        "ttf": "segoeui.ttf",
        "cssFamily": "'Segoe UI', system-ui, sans-serif",
        "cssWeight": 400,
    },
    "arial-bold": {
        "label": "Arial Bold",
        "ttf": "arialbd.ttf",
        "cssFamily": "Arial, sans-serif",
        "cssWeight": 700,
    },
    "calibri-bold": {
        "label": "Calibri Bold",
        "ttf": "calibrib.ttf",
        "cssFamily": "Calibri, sans-serif",
        "cssWeight": 700,
    },
    "georgia-bold": {
        "label": "Georgia Bold",
        "ttf": "georgiab.ttf",
        "cssFamily": "Georgia, serif",
        "cssWeight": 700,
    },
    "times-new-roman-bold": {
        "label": "Times New Roman Bold",
        "ttf": "timesbd.ttf",
        "cssFamily": "'Times New Roman', serif",
        "cssWeight": 700,
    },
    "trebuchet-bold": {
        "label": "Trebuchet MS Bold",
        "ttf": "trebucbd.ttf",
        "cssFamily": "'Trebuchet MS', sans-serif",
        "cssWeight": 700,
    },
    "verdana-bold": {
        "label": "Verdana Bold",
        "ttf": "verdanab.ttf",
        "cssFamily": "Verdana, sans-serif",
        "cssWeight": 700,
    },
}

# Reproduces today's hardcoded display_renderer.py / overlay.css look exactly
# — shipping this causes zero visual change until the operator customizes it.
DEFAULT_THEME = {
    "fontFamily": DEFAULT_FONT_KEY,
    "verseColor": "#ffffff",
    "referenceColor": "#ffd166",
    "verseFontSize": 54,
    "referenceFontSize": 30,
    "textPosition": "bottom",
    "textAlign": "center",
    "referencePlacement": "above",
    "backgroundStyle": "none",
    "backgroundColor": "#000000",
    "backgroundOpacity": 0.6,
    "backgroundImage": None,
    "layout": "full-frame",
    "verseMarginX": 5,
    "verseMarginY": 5,
    "referenceMargin": 5,
    "shadowIntensity": "normal",
}

_loaded = json_store.load(_FILENAME, {})
# Filtered to known keys so a field removed in a later schema version (e.g.
# verseMargin -> verseMarginX/verseMarginY) doesn't linger forever in the
# persisted file or in API responses.
_theme: dict = {**DEFAULT_THEME, **{k: v for k, v in _loaded.items() if k in DEFAULT_THEME}}


def get() -> dict:
    return dict(_theme)


def update(patch: dict) -> dict:
    for key, value in patch.items():
        if key not in DEFAULT_THEME or value is None:
            continue
        if key == "backgroundImage" and value == "":
            # "" is the clear-image sentinel — Pydantic's exclude_none can't
            # send a real None through a PATCH-style update, so the Electron
            # side sends "" to mean "remove the background image".
            value = None
        _theme[key] = value
    json_store.save(_FILENAME, _theme)
    return dict(_theme)


def reset() -> dict:
    _theme.clear()
    _theme.update(DEFAULT_THEME)
    json_store.save(_FILENAME, _theme)
    return dict(_theme)


def fonts() -> list[dict]:
    # Includes cssFamily/cssWeight (not just key/label) so the Electron
    # settings UI can compute a live preview theme client-side without
    # duplicating FONT_REGISTRY by hand.
    return [
        {"key": key, "label": entry["label"], "cssFamily": entry["cssFamily"], "cssWeight": entry["cssWeight"]}
        for key, entry in FONT_REGISTRY.items()
    ]


def font_entry(font_family_key: str) -> dict:
    return FONT_REGISTRY.get(font_family_key, FONT_REGISTRY[DEFAULT_FONT_KEY])


def layout_entry(layout_key: str) -> dict:
    return LAYOUT_PRESETS.get(layout_key, LAYOUT_PRESETS[DEFAULT_LAYOUT_KEY])


def _hex_to_rgba_css(hex_color: str, opacity: float) -> str:
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i : i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r}, {g}, {b}, {opacity})"


def for_overlay(theme: Optional[dict] = None) -> dict:
    """The stored theme plus derived, browser-ready CSS fields — so the
    overlay (overlay.js) never needs its own copy of FONT_REGISTRY/
    LAYOUT_PRESETS just to turn a key into actual CSS values."""
    if theme is None:
        theme = get()
    font = font_entry(theme["fontFamily"])
    layout = layout_entry(theme["layout"])
    return {
        **theme,
        "_fontCss": font["cssFamily"],
        "_fontWeight": font["cssWeight"],
        "_bgRgba": _hex_to_rgba_css(theme["backgroundColor"], theme["backgroundOpacity"]),
        "_scrimRgba": f"rgba(0, 0, 0, {theme['backgroundOpacity']})",
        "_bgImageUrl": f"/theme-assets/{theme['backgroundImage']}" if theme.get("backgroundImage") else None,
        "_layoutMaxWidthFraction": layout["maxWidthFraction"],
        "_layoutMaxHeightFraction": layout["maxHeightFraction"],
        "_layoutPaddingMultiplier": layout["paddingMultiplier"],
        "_layoutMarginFraction": layout["marginFraction"],
        "_layoutFontBoost": layout["fontBoost"],
        "_layoutFullBleed": layout["fullBleed"],
    }
