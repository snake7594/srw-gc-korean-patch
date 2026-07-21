#!/usr/bin/env python3
"""Redraw the Korean runtime glyphs of SRW GC's font.pak with a different TTF.

Unlike build_translation_codebook_font.py this tool never re-derives the
character -> code assignment.  It takes an already published codebook as the
authority, re-renders only the 162-byte pixel payload of each referenced
record, and refuses to run if any record's two-byte storage key disagrees with
the codebook.  The character -> code mapping therefore cannot drift, which is
what keeps previously built add00/add01/add02/bpilot/Start.dol text valid.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from srw_gc_font_codec import (
    build_font_pak,
    parse_inner_entries,
    read_font_pak,
    read_font_pak_bytes,
)

RECORD_SIZE = 164
PIXEL_BYTES = 162
CELL = 18


def pack_pixels(pixels: list[int]) -> bytes:
    if len(pixels) != CELL * CELL or any(value < 0 or value > 4 for value in pixels):
        raise ValueError("glyph must be 18x18 with palette values 0..4")
    return bytes(
        pixels[index] | (pixels[index + 1] << 4) for index in range(0, len(pixels), 2)
    )


def unpack_pixels(record_pixels: bytes) -> list[int]:
    pixels: list[int] = []
    for value in record_pixels:
        pixels.extend((value & 0x0F, value >> 4))
    return pixels


def quantise(image: Image.Image) -> list[int]:
    return [min(4, (value * 4 + 127) // 255) for value in image.getdata()]


def render_glyph(character: str, font: ImageFont.FreeTypeFont, offset) -> list[int]:
    image = Image.new("L", (CELL, CELL), 0)
    ImageDraw.Draw(image).text(offset, character, font=font, fill=255)
    pixels = quantise(image)
    if not any(pixels):
        raise RuntimeError(f"empty glyph for U+{ord(character):04X} ({character})")
    return pixels


def ink_bbox(pixels: list[int]):
    columns = [index % CELL for index, value in enumerate(pixels) if value]
    rows = [index // CELL for index, value in enumerate(pixels) if value]
    if not columns:
        return None
    return min(columns), min(rows), max(columns), max(rows)


def clipped(character: str, font: ImageFont.FreeTypeFont, offset) -> bool:
    """True when ink would fall outside the cell (measured on a padded canvas)."""
    pad = 24
    canvas = Image.new("L", (CELL + 2 * pad, CELL + 2 * pad), 0)
    ImageDraw.Draw(canvas).text((offset[0] + pad, offset[1] + pad), character, font=font, fill=255)
    box = canvas.point(lambda value: 255 if value >= 32 else 0).getbbox()
    if box is None:
        return True
    left, top, right, bottom = box
    return left < pad or top < pad or right > pad + CELL or bottom > pad + CELL


def write_preview(glyphs: list[list[int]], output: Path, scale: int = 1) -> None:
    columns = 36
    rows = (len(glyphs) + columns - 1) // columns
    image = Image.new("L", (columns * 20, rows * 20), 0)
    for index, pixels in enumerate(glyphs):
        glyph = Image.new("L", (CELL, CELL))
        glyph.putdata([value * 63 for value in pixels])
        image.paste(glyph, ((index % columns) * 20 + 1, (index // columns) * 20 + 1))
    if scale != 1:
        image = image.resize((image.width * scale, image.height * scale), Image.NEAREST)
    image.save(output)


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--original-pak", type=Path, required=True)
    parser.add_argument("--codebook", type=Path, required=True, help="published codebook CSV (authority)")
    parser.add_argument("--font", type=Path, required=True)
    parser.add_argument("--font-size", type=int, required=True)
    parser.add_argument("--offset-x", type=int, default=0)
    parser.add_argument("--offset-y", type=int, default=0)
    parser.add_argument("--glyph-source-label", default=None)
    parser.add_argument("--compare-pak", type=Path, default=None, help="previous build, for slot diffing")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.output.exists():
        raise RuntimeError(f"output directory already exists: {args.output}")

    offset = (args.offset_x, args.offset_y)
    label = args.glyph_source_label or f"rendered_{args.font.stem.lower()}_{args.font_size}"

    with args.codebook.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = list(reader.fieldnames or [])
        rows = list(reader)
    for column in ("target", "code", "file", "index", "storage_code"):
        if column not in fieldnames:
            raise RuntimeError(f"codebook is missing the {column} column")

    original = read_font_pak(args.original_pak)
    entries = {entry.name: entry for entry in parse_inner_entries(original.decompressed)}
    inner = bytearray(original.decompressed)

    font = ImageFont.truetype(str(args.font), args.font_size)
    seen_slots: set[tuple[str, int]] = set()
    seen_targets: set[str] = set()
    glyphs: list[list[int]] = []
    touched: list[tuple[int, int]] = []
    clipped_targets: list[str] = []
    metrics = []

    for row in rows:
        target = row["target"]
        if len(target) != 1:
            raise RuntimeError(f"codebook target is not a single character: {target!r}")
        if target in seen_targets:
            raise RuntimeError(f"duplicate codebook target {target}")
        seen_targets.add(target)
        file_name = row["file"]
        index = int(row["index"])
        if (file_name, index) in seen_slots:
            raise RuntimeError(f"duplicate codebook slot {file_name}#{index}")
        seen_slots.add((file_name, index))

        entry = entries[file_name]
        position = entry.offset + index * RECORD_SIZE
        if position + RECORD_SIZE > entry.offset + entry.size:
            raise RuntimeError(f"slot {file_name}#{index} is outside the member")
        storage = int.from_bytes(inner[position : position + 2], "big")
        expected = int(row["storage_code"], 16)
        if storage != expected:
            raise RuntimeError(
                f"storage guard mismatch for {target}: codebook 0x{expected:04X}, pak 0x{storage:04X}"
            )

        pixels = render_glyph(target, font, offset)
        if clipped(target, font, offset):
            clipped_targets.append(target)
        box = ink_bbox(pixels)
        metrics.append((sum(1 for value in pixels if value), box))
        inner[position + 2 : position + RECORD_SIZE] = pack_pixels(pixels)
        touched.append((position + 2, position + RECORD_SIZE))
        glyphs.append(pixels)

    if clipped_targets:
        raise RuntimeError(
            f"{len(clipped_targets)} glyphs are clipped by the 18x18 cell: "
            + "".join(clipped_targets[:40])
        )

    # Every byte that differs from the original must belong to a rewritten record.
    allowed = bytearray(len(inner))
    for start, end in touched:
        for position in range(start, end):
            allowed[position] = 1
    stray = [
        position
        for position in range(len(inner))
        if inner[position] != original.decompressed[position] and not allowed[position]
    ]
    if stray:
        raise RuntimeError(f"{len(stray)} bytes changed outside the codebook records")

    slot_diff = None
    if args.compare_pak:
        previous = read_font_pak(args.compare_pak)
        if len(previous.decompressed) != len(original.decompressed):
            raise RuntimeError("comparison pak has a different payload size")
        previous_records = {
            (position - 2) // RECORD_SIZE
            for position in range(len(previous.decompressed))
            if previous.decompressed[position] != original.decompressed[position]
        }
        new_records = {
            (position - 2) // RECORD_SIZE
            for position in range(len(inner))
            if inner[position] != original.decompressed[position]
        }
        slot_diff = {
            "records_changed_by_previous_build": len(previous_records),
            "records_changed_by_this_build": len(new_records),
            "identical_record_set": sorted(previous_records) == sorted(new_records),
        }
        if not slot_diff["identical_record_set"]:
            raise RuntimeError("this build touches a different record set than the comparison pak")

    built = build_font_pak(original, bytes(inner))
    verified = read_font_pak_bytes(built)
    if verified.decompressed != bytes(inner):
        raise RuntimeError("rebuilt font PAK round-trip mismatch")

    args.output.mkdir(parents=True)
    (args.output / "font.pak").write_bytes(built)

    # 1) byte-identical copy of the authority codebook (drop-in for the pipeline)
    (args.output / "korean_codebook.csv").write_bytes(args.codebook.read_bytes())
    # 2) annotated copy recording the new glyph provenance
    annotated_rows = [dict(row, glyph_source=label) for row in rows]
    with (args.output / "korean_codebook_annotated.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(annotated_rows)

    write_preview(glyphs, args.output / "codebook_preview.png")
    write_preview(glyphs, args.output / "codebook_preview_x4.png", scale=4)

    ink = [item[0] for item in metrics]
    boxes = [item[1] for item in metrics]
    report = {
        "tool": "rerender_codebook_font.py",
        "authority_codebook": str(args.codebook.resolve()),
        "authority_codebook_sha256": sha256_bytes(args.codebook.read_bytes()),
        "original_pak": str(args.original_pak.resolve()),
        "original_pak_size": args.original_pak.stat().st_size,
        "font_file": str(args.font.resolve()),
        "font_sha256": sha256_bytes(args.font.read_bytes()),
        "font_size": args.font_size,
        "draw_position": list(offset),
        "glyph_source_label": label,
        "glyphs_rendered": len(glyphs),
        "empty_glyphs": 0,
        "clipped_glyphs": 0,
        "font_members_touched": sorted({row["file"] for row in rows}),
        "mean_ink_pixels": round(sum(ink) / len(ink), 2),
        "min_ink_pixels": min(ink),
        "min_left_margin": min(box[0] for box in boxes),
        "min_top_margin": min(box[1] for box in boxes),
        "min_right_margin": min(CELL - 1 - box[2] for box in boxes),
        "min_bottom_margin": min(CELL - 1 - box[3] for box in boxes),
        "max_glyph_width": max(box[2] - box[0] + 1 for box in boxes),
        "max_glyph_height": max(box[3] - box[1] + 1 for box in boxes),
        "slot_diff_vs_compare_pak": slot_diff,
        "built_pak_size": len(built),
        "built_pak_sha256": sha256_bytes(built),
        "decompressed_size": len(inner),
        "decompressed_sha256": sha256_bytes(bytes(inner)),
        "fits_original_slot": len(built) <= args.original_pak.stat().st_size,
    }
    (args.output / "build_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
