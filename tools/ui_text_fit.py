#!/usr/bin/env python3
"""Fit Korean UI text to the Japanese retail label geometry.

The earlier UI builders sized Korean menu text against the *English* patch
canvas: ``draw_fitted_text`` simply shrank the face until the string fitted
the box.  Whenever an English label was shorter or taller than the Japanese
original, the Korean text inherited that wrong proportion, so menu glyphs
came out noticeably larger or smaller than the Japanese retail screen.

This module measures the Japanese retail label instead and reproduces its
ink height and vertical centre.  Width is only used as a ceiling: Korean is
shrunk solely when the natural Japanese-sized rendering would overflow the
canvas that the container's SCR header fixes for that label.

Nothing here writes to the container.  It only computes geometry, so the
tile-preservation, index-preservation, and audit guarantees of the callers
are untouched.
"""

from __future__ import annotations

from PIL import Image, ImageDraw, ImageFont


RENDERER_VERSION = "japanese-ink-matched-v1"

#: Pixels at or below this level count as canvas rather than glyph.  Atlas
#: pixels are 4-bit, so ``add00_tools.decode_i4`` expands level *n* to
#: ``n * 17``; 40 is "level 3 or brighter".  It deliberately sits above one
#: I4 step because :func:`japanese_ink_box` subtracts a *reconstructed*
#: background for the pill and bevel labels, and those reconstructions are
#: allowed to be one level off the retail art.
INK_THRESHOLD = 40

#: Probe padding, wide enough to absorb negative side bearings.
_PROBE_PADDING = 16


def japanese_ink_box(
    japanese: Image.Image,
    background: Image.Image | None = None,
    *,
    region: tuple[int, int, int, int] | None = None,
    threshold: int = INK_THRESHOLD,
) -> tuple[int, int, int, int] | None:
    """Bounding box of the Japanese label's ink inside ``region``.

    ``background`` is the reconstructed non-text art for the same label.
    Passing it removes bevels, pills and gradients from the measurement so
    only the glyphs remain.  ``None`` treats the canvas as plain black.
    """

    left, top, right, bottom = region or (0, 0, japanese.width, japanese.height)
    left = max(0, left)
    top = max(0, top)
    right = min(japanese.width, right)
    bottom = min(japanese.height, bottom)
    if right <= left or bottom <= top:
        return None
    view = japanese.crop((left, top, right, bottom)).convert("L")
    if background is not None:
        base = Image.new("L", view.size, 0)
        overlap = background.crop(
            (
                left,
                top,
                min(right, background.width),
                min(bottom, background.height),
            )
        )
        if overlap.width and overlap.height:
            base.paste(overlap.convert("L"), (0, 0))
        view = _absolute_difference(view, base)
    mask = view.point(lambda value: 255 if value > threshold else 0)
    box = mask.getbbox()
    if box is None:
        return None
    return (box[0] + left, box[1] + top, box[2] + left, box[3] + top)


def unique_ink_box(
    japanese: Image.Image,
    english: Image.Image,
    *,
    threshold: int = INK_THRESHOLD,
) -> tuple[int, int, int, int] | None:
    """Box of Japanese ink that the English view does not also carry.

    Bevels and underlines are identical in both patches, so what remains is
    the Japanese glyph run.  Labels whose Japanese and English strings are
    the same ASCII word leave nothing behind and return ``None``.
    """

    width = min(japanese.width, english.width)
    height = min(japanese.height, english.height)
    if width <= 0 or height <= 0:
        return None
    view = japanese.crop((0, 0, width, height)).convert("L")
    other = english.crop((0, 0, width, height)).convert("L")
    difference = _absolute_difference(view, other)
    mask = Image.new("L", view.size)
    mask.putdata(
        [
            255 if ink > threshold and delta > threshold else 0
            for ink, delta in zip(view.getdata(), difference.getdata())
        ]
    )
    return mask.getbbox()


def _absolute_difference(left: Image.Image, right: Image.Image) -> Image.Image:
    output = Image.new("L", left.size)
    output.putdata(
        [abs(a - b) for a, b in zip(left.getdata(), right.getdata())]
    )
    return output


def ink_extent(
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    spacing: int = 0,
    align: str = "center",
    shadow: bool = False,
    threshold: int = INK_THRESHOLD,
) -> tuple[int, int, int, int] | None:
    """Ink box of ``text`` relative to the ``multiline_text`` draw origin.

    The optional 1 px drop shadow is included because it is part of the
    label's visible footprint, and the same ``threshold`` as the Japanese
    measurement is applied so both sides count the same kind of pixel.
    """

    lines = text.split("\n")
    size = getattr(font, "size", 16)
    width = _PROBE_PADDING * 2 + int((size + 4) * (max(len(line) for line in lines) + 2)) + 32
    height = _PROBE_PADDING * 2 + int((size + spacing + 8) * len(lines)) + 32
    probe = Image.new("L", (max(width, 32), max(height, 32)), 0)
    draw = ImageDraw.Draw(probe)
    if shadow:
        draw.multiline_text(
            (_PROBE_PADDING + 1, _PROBE_PADDING + 1),
            text,
            font=font,
            spacing=spacing,
            align=align,
            fill=255,
        )
    draw.multiline_text(
        (_PROBE_PADDING, _PROBE_PADDING),
        text,
        font=font,
        spacing=spacing,
        align=align,
        fill=255,
    )
    box = probe.point(lambda value: 255 if value > threshold else 0).getbbox()
    if box is None:
        return None
    return (
        box[0] - _PROBE_PADDING,
        box[1] - _PROBE_PADDING,
        box[2] - _PROBE_PADDING,
        box[3] - _PROBE_PADDING,
    )


def choose_font(
    font_path,
    text: str,
    *,
    region_size: tuple[int, int],
    target_height: int | None,
    spacing: int = 0,
    align: str = "center",
    shadow: bool = False,
    horizontal_margin: int = 2,
    vertical_slack: int = 0,
    maximum_font_size: int | None = None,
    minimum_font_size: int = 6,
) -> tuple[ImageFont.FreeTypeFont, int, tuple[int, int, int, int]]:
    """Pick the face whose ink height is closest to the Japanese label.

    ``target_height`` of ``None`` restores the historical behaviour of using
    the largest face that fits, which is the fallback for labels the
    Japanese container does not describe with the same canvas.
    ``vertical_slack`` is the number of scanlines withheld from the region,
    which bounds how many 8x8 tiles the tallest labels can consume.
    """

    region_width, region_height = region_size
    usable_width = region_width - horizontal_margin * 2
    usable_height = region_height - vertical_slack
    ceiling = maximum_font_size or min(64, region_height + 8)
    best: (
        tuple[int, int, ImageFont.FreeTypeFont, int, tuple[int, int, int, int]] | None
    ) = None
    for font_size in range(ceiling, minimum_font_size - 1, -1):
        font = ImageFont.truetype(str(font_path), font_size)
        box = ink_extent(text, font, spacing=spacing, align=align, shadow=shadow)
        if box is None:
            continue
        width = box[2] - box[0]
        height = box[3] - box[1]
        if width > usable_width or height > usable_height:
            continue
        if target_height is None:
            return font, font_size, box
        score = abs(height - target_height)
        # Ties go to the face that does not overshoot: Korean menu text that
        # is larger than the Japanese original is the defect being fixed,
        # and the smaller face also costs fewer atlas tiles.
        better = best is None or score < best[0]
        if not better and score == best[0]:
            better = height <= target_height < best[3]
        if better:
            best = (score, font_size, font, height, box)
        if best[0] == 0 and best[3] <= target_height:
            break
    if best is None:
        raise ValueError(
            f"cannot fit {text!r} into {region_size} "
            f"(usable {usable_width}x{usable_height}, "
            f"font sizes {minimum_font_size}..{ceiling})"
        )
    return best[2], best[1], best[4]


def place_ink(
    ink: tuple[int, int, int, int],
    region: tuple[int, int, int, int],
    *,
    align: str,
    horizontal_margin: int = 2,
    target_center_y: float | None = None,
    left_hint: int | None = None,
) -> tuple[int, int]:
    """Return the ``multiline_text`` origin that lands the ink where wanted."""

    left, top, right, bottom = region
    width = ink[2] - ink[0]
    height = ink[3] - ink[1]
    if align == "left":
        x = left + horizontal_margin
    elif align == "right":
        x = right - horizontal_margin - width
    elif align == "center":
        x = left + (right - left - width) // 2
    else:
        raise ValueError(f"unsupported text alignment: {align}")
    if left_hint is not None:
        x = max(left + horizontal_margin, min(left_hint, right - horizontal_margin - width))
    if target_center_y is None:
        y = top + (bottom - top - height) // 2
    else:
        y = int(round(target_center_y - height / 2))
    x = max(left, min(x, right - width))
    y = max(top, min(y, bottom - height))
    return x - ink[0], y - ink[1]
