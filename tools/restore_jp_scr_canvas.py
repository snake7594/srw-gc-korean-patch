#!/usr/bin/env python3
"""Restore Japanese retail canvas dimensions on translated add00 SCR blocks.

Every UI ``SCR`` block in the pre-UI Korean base is byte-identical to the
English fan patch, so its declared canvas (``width``/``height`` in tiles at
offsets 4 and 8) is the *English* label geometry.  The patch is applied to
the Japanese retail ISO, whose menus were laid out around the Japanese
canvases, and 173 of the 381 translated block-518 labels are therefore drawn
into a box the Japanese game never used.  Where the English label was the
shorter word the box is too narrow, so ``ui_text_fit`` has to shrink Korean
far below the Japanese ink height.

This tool rewrites the declared canvas of the affected ``SCR`` blocks back to
the Japanese retail value before any Korean is rendered.  The block payload
is resized to ``align32(32 + 2 * width * height)`` accordingly and the outer
absolute-offset table is recomputed, exactly as the atlas-growth path in
``repack_preserve_indices.py`` already does.

Selection is deliberately conservative.  A label is restored only when all of
these hold:

* the Japanese canvas differs from the current one,
* both canvases have the same height (a differing height means the English
  patch rebuilt the block into different artwork),
* the label is a plain black canvas (``decoration`` resolves to ``none``), so
  no bevel or pill art has to be reconstructed on a wider canvas,
* the resolved alignment is ``center``, and
* rendering Korean on the Japanese canvas does **not** reduce its ink height.

The last rule matters because the Japanese box is sometimes *narrower*: the
retail label is a single kanji (``機``, ``空``, ``陸``, ``宇``) where Korean
needs two syllables.  Restoring those would shrink text that is currently
correct, so they keep the canvas that ships today.

Existing tile entries are copied row by row into the new canvas and any new
column is filled with tile 0.  Every restored SCR is fully re-rendered by
``repack_direct_scr_atlas.py`` downstream, so the copied entries only keep
the intermediate container self-consistent.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
from pathlib import Path

import PIL
from PIL import features

TOOLS_DIR = Path(__file__).resolve().parent
REPOSITORY_DIR = TOOLS_DIR.parent
sys.path.insert(0, str(TOOLS_DIR))
import add00_tools  # noqa: E402

import repack_direct_scr_atlas as direct  # noqa: E402
from extract_scr_atlas import render_direct  # noqa: E402
from repack_preserve_indices import rebuild_container  # noqa: E402
from ui_text_fit import RENDERER_VERSION, japanese_ink_box  # noqa: E402


LOCAL_FONT_DIR = (
    Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Windows" / "Fonts"
    if os.environ.get("LOCALAPPDATA")
    else Path(".")
)
FONT_FILENAME = "NanumSquareNeo-cBd.ttf"
DEFAULT_FONT = LOCAL_FONT_DIR / FONT_FILENAME
FONT_SHA256 = "4749FA5691157CF56A59D297B45E88894A646846048018CD7A4117FFB2869767"


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest().upper()


def aligned_length(width: int, height: int) -> int:
    raw = 32 + 2 * width * height
    alignment = add00_tools.ALIGNMENT
    return (raw + alignment - 1) // alignment * alignment


def resize_scr(block: bytes, width: int, height: int) -> bytes:
    """Return ``block`` with a new declared canvas, keeping row content."""

    if block[:4] != b"SCR\0":
        raise ValueError("block is not an SCR tile map")
    old_width, old_height = struct.unpack_from(">II", block, 4)
    stored = (len(block) - 32) // 2
    old_entries = struct.unpack_from(f">{stored}H", block, 32)
    entries = [0] * (width * height)
    for row in range(min(height, old_height)):
        for column in range(min(width, old_width)):
            entries[row * width + column] = old_entries[row * old_width + column]
    header = bytearray(block[:32])
    struct.pack_into(">II", header, 4, width, height)
    payload = bytearray(struct.pack(f">{len(entries)}H", *entries))
    payload.extend(bytes(aligned_length(width, height) - 32 - len(payload)))
    result = bytes(header) + bytes(payload)
    if len(result) != aligned_length(width, height):
        raise AssertionError("resized SCR length is not 0x20 aligned")
    return result


def ink_ratio(size, text, japanese_box) -> float:
    try:
        _, _, metrics = direct.render_korean(size, text, "center", None, japanese_box, None, 0)
    except ValueError:
        return 0.0
    target = metrics["japanese_ink_height"]
    if not target:
        return 0.0
    return metrics["korean_ink_height"] / target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path, help="pre-UI Japanese-base add00")
    parser.add_argument("output", type=Path, help="canvas-restored add00")
    parser.add_argument("--japanese", type=Path, required=True, help="Japanese retail add00")
    parser.add_argument("--english", type=Path, required=True, help="English patch add00")
    parser.add_argument("--bitmap", type=int, default=518)
    parser.add_argument(
        "--large-mapping",
        type=Path,
        default=REPOSITORY_DIR / "data" / "ui_block518_ko.json",
    )
    parser.add_argument("--font", type=Path, default=DEFAULT_FONT)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args(argv)

    font = args.font.expanduser().resolve()
    source_path = args.source.expanduser().resolve()
    japanese_path = args.japanese.expanduser().resolve()
    english_path = args.english.expanduser().resolve()
    mapping_path = args.large_mapping.expanduser().resolve()
    output_path = args.output.expanduser().resolve()
    report_path = args.report.expanduser().resolve()
    protected = {source_path, japanese_path, english_path, mapping_path, font}
    if output_path in protected or report_path in protected or report_path == output_path:
        raise ValueError("refusing to overwrite an input with the output or report")
    if output_path.exists() or report_path.exists():
        raise FileExistsError("output and report paths must not already exist")

    actual_font_sha256 = sha256(font.read_bytes())
    if actual_font_sha256 != FONT_SHA256:
        raise ValueError(f"{FONT_FILENAME} font hash drift: {actual_font_sha256}")
    direct.FONT = font

    source = add00_tools.parse_container(source_path)
    japanese = add00_tools.parse_container(japanese_path)
    english = add00_tools.parse_container(english_path)
    if not (len(source.blocks) == len(japanese.blocks) == len(english.blocks)):
        raise ValueError("container block counts differ")
    identity, _ = rebuild_container(list(source.blocks))
    if identity != source.source:
        raise RuntimeError("source container cannot be rebuilt byte-identically")

    japanese_atlas = add00_tools.decode_i4(japanese.blocks[args.bitmap])
    english_atlas = add00_tools.decode_i4(english.blocks[args.bitmap])
    source_atlas = add00_tools.decode_i4(source.blocks[args.bitmap])

    document = json.loads(mapping_path.read_text(encoding="utf-8"))
    if document.get("schema") != "srw-gc-ui-block518-ko-v1":
        raise ValueError(f"unsupported mapping schema: {mapping_path}")
    records = {int(row["block_index"]): row for row in document["records"]}

    blocks = list(source.blocks)
    restored: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    for index in sorted(records):
        row = records[index]
        korean = str(row["korean"]).strip()
        block = source.blocks[index]
        if block[:4] != b"SCR\0":
            raise ValueError(f"mapped block {index} is not an SCR")
        current = struct.unpack_from(">II", block, 4)
        target = struct.unpack_from(">II", japanese.blocks[index], 4)
        record = {
            "block_index": index,
            "korean": korean,
            "current_tiles": list(current),
            "japanese_tiles": list(target),
        }
        if current == target:
            skipped.append({**record, "reason": "already_japanese"})
            continue
        if current[1] != target[1]:
            skipped.append({**record, "reason": "different_artwork_height"})
            continue
        if block[12:32] != japanese.blocks[index][12:32]:
            skipped.append({**record, "reason": "scr_header_field_drift"})
            continue

        japanese_view, _ = render_direct(japanese_atlas, japanese.blocks[index])
        english_view, _ = render_direct(english_atlas, english.blocks[index])
        source_view, _ = render_direct(source_atlas, block)
        decoration_pixels = sum(
            value != 0
            for value in direct.common_bottom_decoration(english_view, japanese_view).getdata()
        )
        explicit_decoration = "decoration" in row and str(row["decoration"]) != "auto"
        mode = (
            str(row["decoration"])
            if explicit_decoration
            else ("common_bottom" if decoration_pixels else "none")
        )
        if mode != "none":
            skipped.append({**record, "reason": "decorated_canvas"})
            continue
        explicit_align = "align" in row and str(row["align"]) != "auto"
        align = str(row["align"]) if explicit_align else "center"
        if align != "center":
            skipped.append({**record, "reason": "non_center_align"})
            continue

        box = japanese_ink_box(japanese_view, None)
        if box is None:
            skipped.append({**record, "reason": "japanese_label_has_no_ink"})
            continue
        before = ink_ratio(source_view.size, korean, box)
        after = ink_ratio(japanese_view.size, korean, box)
        if after < before - 1e-9:
            skipped.append(
                {
                    **record,
                    "reason": "would_shrink_korean",
                    "ratio_before": round(before, 4),
                    "ratio_after": round(after, 4),
                }
            )
            continue

        blocks[index] = resize_scr(block, *target)
        restored.append(
            {
                **record,
                "japanese_ink_height": box[3] - box[1],
                "ratio_before": round(before, 4),
                "ratio_after": round(after, 4),
                "old_block_length": len(block),
                "new_block_length": len(blocks[index]),
            }
        )

    built, offsets = rebuild_container(blocks)
    verified = add00_tools.parse_container(built)
    if verified.offsets != offsets:
        raise RuntimeError("rebuilt offset table failed to parse")
    restored_indices = {int(row["block_index"]) for row in restored}
    changed = [
        index
        for index, (before, after) in enumerate(zip(source.blocks, verified.blocks))
        if before != after
    ]
    if sorted(restored_indices) != changed:
        raise RuntimeError(f"changed-block guard failed: {sorted(set(changed) ^ restored_indices)}")
    for index in restored_indices:
        block = verified.blocks[index]
        if block[:4] != b"SCR\0" or block[:4] + block[12:32] != (
            japanese.blocks[index][:4] + japanese.blocks[index][12:32]
        ):
            raise RuntimeError(f"restored SCR {index} header drifted")
        if struct.unpack_from(">II", block, 4) != struct.unpack_from(
            ">II", japanese.blocks[index], 4
        ):
            raise RuntimeError(f"restored SCR {index} canvas is not the Japanese value")
        if len(block) != len(japanese.blocks[index]):
            raise RuntimeError(f"restored SCR {index} length differs from Japanese retail")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("xb") as handle:
        handle.write(built)

    report = {
        "schema": "srw-gc-add00-jp-scr-canvas-restore-v1",
        "status": "pass",
        "source": str(source_path),
        "source_sha256": sha256(source.source),
        "japanese_reference": str(japanese_path),
        "japanese_reference_sha256": sha256(japanese.source),
        "english_reference": str(english_path),
        "english_reference_sha256": sha256(english.source),
        "mapping": str(mapping_path),
        "mapping_sha256": sha256(mapping_path.read_bytes()),
        "font": {"path": str(font), "sha256": actual_font_sha256},
        "renderer": {
            "pillow": PIL.__version__,
            "freetype": features.version("freetype2"),
            "text_fit": RENDERER_VERSION,
        },
        "output": str(output_path),
        "output_sha256": sha256(built),
        "source_size": len(source.source),
        "output_size": len(built),
        "size_growth": len(built) - len(source.source),
        "bitmap_block": args.bitmap,
        "translated_scr_count": len(records),
        "restored_scr_count": len(restored),
        "skipped_scr_count": len(skipped),
        "restored_scrs": sorted(restored_indices),
        "changed_blocks": changed,
        "restored": restored,
        "skipped": skipped,
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with report_path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(
        json.dumps(
            {
                "output": report["output"],
                "output_sha256": report["output_sha256"],
                "output_size": report["output_size"],
                "size_growth": report["size_growth"],
                "restored_scr_count": report["restored_scr_count"],
                "skipped_scr_count": report["skipped_scr_count"],
                "status": report["status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
