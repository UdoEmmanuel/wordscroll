"""
Renders the current display state as an RGBA video frame for NDI output.
Styling (font, colors, sizing, position, layout, margins, background,
shadow) comes from theme_store.py, so it stays in sync with the same theme
the HTML overlay (overlay/overlay.css + overlay.js) applies — one shared
source of truth instead of separately hardcoded constants in each place.
"""
from pathlib import Path
from typing import Optional

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

import theme_store

FRAME_WIDTH = 1920
FRAME_HEIGHT = 1080

_FONT_DIR = Path(r"C:\Windows\Fonts")

_SHADOW_PRESETS = {
    "none": None,
    "normal": {"offset": 3, "alpha": 220},
    "strong": {"offset": 5, "alpha": 255},
}

# Verse text auto-shrinks from the operator's chosen verseFontSize (treated
# as a ceiling, not a fixed size) down to this floor, in this step size,
# until the wrapped block fits the layout's target box — so a long verse
# doesn't overflow the frame and a short one still gets to use the full
# size the operator picked.
AUTO_FIT_MIN_SIZE = 16
AUTO_FIT_STEP = 2

_font_cache: dict[tuple[str, int], ImageFont.FreeTypeFont] = {}


def _font(path: Path, size: int) -> ImageFont.FreeTypeFont:
    key = (str(path), size)
    if key not in _font_cache:
        try:
            _font_cache[key] = ImageFont.truetype(str(path), size)
        except OSError:
            # Font file not present on this machine — degrade gracefully
            # rather than crashing the NDI render thread.
            _font_cache[key] = ImageFont.load_default(size=size)
    return _font_cache[key]


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return (int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16))


def _wrap_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if draw.textlength(candidate, font=font) <= max_width:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _fit_verse_font(
    draw: ImageDraw.ImageDraw, text: str, font_path: Path, max_size: int, max_width: int, max_height: int
):
    """Shrinks from max_size down to AUTO_FIT_MIN_SIZE until the wrapped
    block fits max_width x max_height, or the floor is hit (in which case
    the floor size is used regardless — better a slight overflow than
    unreadably tiny or an infinite loop)."""
    size = max_size
    while True:
        font = _font(font_path, size)
        lines = _wrap_text(draw, text, font, max_width)
        line_height = int(size * 1.35)
        block_height = line_height * len(lines)
        if block_height <= max_height or size <= AUTO_FIT_MIN_SIZE:
            return font, lines, line_height, block_height
        size = max(AUTO_FIT_MIN_SIZE, size - AUTO_FIT_STEP)


def render_blank_frame() -> np.ndarray:
    return np.zeros((FRAME_HEIGHT, FRAME_WIDTH, 4), dtype=np.uint8)


def render_display_frame(reference: str, translation: str, text: str, theme: Optional[dict] = None) -> np.ndarray:
    """Returns an RGBA numpy array (FRAME_HEIGHT, FRAME_WIDTH, 4).

    `theme` defaults to the current persisted theme; callers that just
    updated the theme (main.py's /theme endpoint) can pass the fresh dict
    directly to re-render the current display without an extra disk read.
    """
    if theme is None:
        theme = theme_store.get()

    img = Image.new("RGBA", (FRAME_WIDTH, FRAME_HEIGHT), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    font_entry = theme_store.font_entry(theme["fontFamily"])
    font_path = _FONT_DIR / font_entry["ttf"]
    verse_color = (*_hex_to_rgb(theme["verseColor"]), 255)
    ref_color = (*_hex_to_rgb(theme["referenceColor"]), 255)

    layout = theme_store.layout_entry(theme["layout"])
    font_boost = layout["fontBoost"]
    # Auto-fit only ever shrinks from this starting ceiling, never grows past
    # it — the layout's fontBoost raises the ceiling so "Full Frame" reads
    # as prominent by default rather than needing an unusually long verse to
    # ever fill the bigger box. Reference text scales the same way so it
    # doesn't look tiny next to a boosted verse.
    ref_font = _font(font_path, round(theme["referenceFontSize"] * font_boost))
    pad_x = round(theme["verseMarginX"] * layout["paddingMultiplier"])
    pad_y = round(theme["verseMarginY"] * layout["paddingMultiplier"])
    ref_gap = round(theme["referenceMargin"] * layout["paddingMultiplier"])

    max_text_width = int(FRAME_WIDTH * layout["maxWidthFraction"]) - 2 * pad_x
    max_verse_height = (
        int(FRAME_HEIGHT * layout["maxHeightFraction"]) - 2 * pad_y - ref_gap - ref_font.size
    )
    verse_font, lines, line_height, verse_block_height = _fit_verse_font(
        draw, text, font_path, round(theme["verseFontSize"] * font_boost), max_text_width, max_verse_height
    )

    ref_label = f"{reference} ({translation})"
    block_height = verse_block_height + ref_gap + ref_font.size

    margin = int(FRAME_HEIGHT * layout["marginFraction"])
    position = theme["textPosition"]
    if position == "top":
        block_top = margin
    elif position == "center":
        block_top = (FRAME_HEIGHT - block_height) // 2
    else:  # "bottom"
        block_top = FRAME_HEIGHT - margin - block_height

    if theme["referencePlacement"] == "above":
        ref_y = block_top
        verse_y_start = block_top + ref_font.size + ref_gap
    else:  # "below"
        verse_y_start = block_top
        ref_y = block_top + verse_block_height + ref_gap

    shadow = _SHADOW_PRESETS.get(theme["shadowIntensity"])

    align = theme["textAlign"]
    if align == "left":
        block_width = max((draw.textlength(line, font=verse_font) for line in lines), default=0)
        block_width = max(block_width, draw.textlength(ref_label.upper(), font=ref_font))
        block_x = (FRAME_WIDTH - block_width) / 2
    else:
        block_x = None  # per-line centering, computed below

    if theme["backgroundStyle"] in ("box", "image"):
        if layout["fullBleed"]:
            # Spans (almost) the entire frame regardless of text length —
            # a full-bleed card, not a box hugging the text.
            bleed_margin_x = int(FRAME_WIDTH * layout["marginFraction"])
            bleed_margin_y = int(FRAME_HEIGHT * layout["marginFraction"])
            box_rect = (bleed_margin_x, bleed_margin_y, FRAME_WIDTH - bleed_margin_x, FRAME_HEIGHT - bleed_margin_y)
        elif align == "left":
            left = block_x - pad_x
            right = block_x + block_width + pad_x
            box_rect = (left, block_top - pad_y, right, block_top + block_height + pad_y)
        else:
            widest = max((draw.textlength(line, font=verse_font) for line in lines), default=0)
            widest = max(widest, draw.textlength(ref_label.upper(), font=ref_font))
            left = (FRAME_WIDTH - widest) / 2 - pad_x
            right = (FRAME_WIDTH + widest) / 2 + pad_x
            box_rect = (left, block_top - pad_y, right, block_top + block_height + pad_y)

        if theme["backgroundStyle"] == "image" and theme.get("backgroundImage"):
            try:
                box_w = max(1, int(box_rect[2] - box_rect[0]))
                box_h = max(1, int(box_rect[3] - box_rect[1]))
                src = Image.open(theme_store.THEME_ASSETS_DIR / theme["backgroundImage"]).convert("RGBA")
                fitted = ImageOps.fit(src, (box_w, box_h), method=Image.LANCZOS)
                scrim = Image.new("RGBA", (box_w, box_h), (0, 0, 0, int(theme["backgroundOpacity"] * 255)))
                # alpha_composite does real alpha blending of the scrim over the
                # fitted image. A plain Image.paste(scrim, ..., mask) here (as
                # before) would ignore the fitted image entirely wherever the
                # mask allows — paste() overwrites with the source's raw RGBA
                # rather than blending by the source's own alpha, so it erased
                # the photo underneath even at 0% scrim opacity.
                composited = Image.alpha_composite(fitted, scrim)
                mask = Image.new("L", (box_w, box_h), 0)
                ImageDraw.Draw(mask).rounded_rectangle((0, 0, box_w, box_h), radius=16, fill=255)
                paste_xy = (int(box_rect[0]), int(box_rect[1]))
                img.paste(composited, paste_xy, mask)
            except (OSError, FileNotFoundError):
                pass  # missing/corrupt image — skip the background, text still renders
        else:
            bg_rgba = (*_hex_to_rgb(theme["backgroundColor"]), int(theme["backgroundOpacity"] * 255))
            draw.rounded_rectangle(box_rect, radius=16, fill=bg_rgba)

    y = verse_y_start
    for line in lines:
        w = draw.textlength(line, font=verse_font)
        x = block_x if align == "left" else (FRAME_WIDTH - w) / 2
        if shadow:
            draw.text((x + shadow["offset"], y + shadow["offset"]), line, font=verse_font, fill=(0, 0, 0, shadow["alpha"]))
        draw.text((x, y), line, font=verse_font, fill=verse_color)
        y += line_height

    ref_text = ref_label.upper()
    ref_w = draw.textlength(ref_text, font=ref_font)
    ref_x = block_x if align == "left" else (FRAME_WIDTH - ref_w) / 2
    if shadow:
        draw.text((ref_x + shadow["offset"], ref_y + shadow["offset"]), ref_text, font=ref_font, fill=(0, 0, 0, shadow["alpha"]))
    draw.text((ref_x, ref_y), ref_text, font=ref_font, fill=ref_color)

    return np.array(img)
