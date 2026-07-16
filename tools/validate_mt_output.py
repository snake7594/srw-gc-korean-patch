"""Validate agent-produced MT corrections against build constraints.

Reads every ``mt_out_chunk_*.json`` in the results directory, checks each
correction against the same constraints the build tools enforce (structure
tokens, Japanese residue, codebook/cp932 encodability, line counts/widths),
and writes:

- accepted_corrections.json: entries ready for override generation
- rejected_corrections.json: entries with reasons, for a repair wave
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import add01_payload
import lib_payload

JAPANESE_RE = re.compile(
    r"[々ぁ-ゖァ-ヺ㐀-鿿ｦ-ﾟ]"
)
STRUCTURE_TOKENS = ("<AA>", "<FF>", "<TT>")
LINE_WIDTH_LIMITS = {"add01": 20, "bpilot": 24, "add02": 40, "dol": 40}


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extracted", type=Path, help="directory from extract_mt_targets.py")
    parser.add_argument("results", type=Path, help="directory containing mt_out_chunk_*.json")
    parser.add_argument("tools", type=Path, help="publish tools directory (for encoders)")
    parser.add_argument("codebook", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    sys.path.insert(0, str(args.tools))
    import add01_tools
    import add02_dol_tools
    import bpilot_tools
    import apply_translation_quality_overrides as build_overrides

    codebook = add02_dol_tools.load_codebook(args.codebook)
    encoders = {
        "add01": add01_tools.make_codebook_encoder(codebook),
        "add02": add02_dol_tools.codebook_encoder(codebook),
        "dol": add02_dol_tools.codebook_encoder(codebook),
        "bpilot": bpilot_tools.make_codebook_encoder(args.codebook),
    }

    targets = {}
    for family in ("add01", "bpilot", "add02", "dol"):
        source = args.extracted / f"mt_targets_{family}.jsonl"
        for line in source.read_text(encoding="utf-8").splitlines():
            if line:
                row = json.loads(line)
                targets[row["id"]] = row

    accepted = []
    rejected = []
    seen = set()
    kept = 0

    result_files = sorted(args.results.glob("mt_out_chunk_*.json"))
    for path in result_files:
        try:
            entries = load_json(path)
        except Exception as error:  # noqa: BLE001
            rejected.append({"file": path.name, "id": None, "reason": f"unreadable JSON: {error}"})
            continue
        if isinstance(entries, dict):
            entries = entries.get("corrections", [])
        for entry in entries:
            stable_id = str(entry.get("id", ""))
            record = targets.get(stable_id)

            def fail(reason: str) -> None:
                rejected.append(
                    {
                        "file": path.name,
                        "id": stable_id,
                        "reason": reason,
                        "lines": entry.get("lines"),
                    }
                )

            if record is None:
                fail("unknown or non-target id")
                continue
            if stable_id in seen:
                fail("duplicate id (first result kept)")
                continue
            seen.add(stable_id)
            if entry.get("keep"):
                kept += 1
                continue
            lines = entry.get("lines")
            if not isinstance(lines, list) or not all(isinstance(l, str) for l in lines) or not lines:
                fail("missing or invalid lines array")
                continue

            family = record["family"]
            current = record["current_payload"]

            if family == "add01":
                try:
                    speaker_segment, body_segments = add01_payload.split_payload(record)
                except add01_payload.Add01StructureError as error:
                    fail(str(error))
                    continue
                expected_lines = len(body_segments)
                lines = add01_payload.normalize_lines(
                    lines, speaker_segment, expected_lines
                )
                if speaker_segment is not None and len(lines) == expected_lines + 1:
                    fail(
                        f"first line {lines[0]!r} would replace the speaker segment "
                        f"{speaker_segment!r}"
                    )
                    continue
                if len(lines) != expected_lines:
                    fail(f"line count {len(lines)} != required {expected_lines}")
                    continue
                if any("KK" in l for l in lines):
                    fail("KK token inside a line")
                    continue
                new_payload = add01_payload.build_payload(speaker_segment, lines)
            elif lib_payload.is_library_id(stable_id):
                # The build reflows library descriptions itself, so the agent's
                # line breaks are meaningless here. Canonicalize through the
                # build's own reflow and validate that -- the raw rewrite is one
                # long paragraph and would fail a flat width check that the
                # shipped payload never has to pass.
                try:
                    new_payload = lib_payload.canonicalize(
                        lines, current, build_overrides.reflow_library_payload
                    )
                except lib_payload.LibraryPayloadError as error:
                    fail(str(error))
                    continue
            else:
                separator = "\n"
                current_lines = current.split(separator)
                if len(lines) > len(current_lines):
                    fail(f"line count {len(lines)} > current {len(current_lines)}")
                    continue
                if any("\n" in l or "\r" in l for l in lines):
                    fail("newline inside a line")
                    continue
                new_payload = separator.join(lines)

            if new_payload == current:
                kept += 1
                continue

            problems = []
            for token in STRUCTURE_TOKENS:
                if current.count(token) != new_payload.count(token):
                    problems.append(f"{token} count changed")
            if current.count("KK") != new_payload.count("KK"):
                problems.append("KK count changed")
            match = JAPANESE_RE.search(new_payload)
            if match:
                problems.append(f"Japanese character remains: {match.group()!r}")
            if lib_payload.is_library_id(stable_id):
                # canonicalize() already enforced the 24-column reflow width and
                # the pager's line budget on the exact text that will ship.
                display_lines = []
                width_limit = lib_payload.MAX_COLUMNS
            else:
                width_limit = LINE_WIDTH_LIMITS[family]
                display_lines = (
                    new_payload.split("KK")
                    if family == "add01"
                    else new_payload.split("\n")
                )
            for display_line in display_lines:
                stripped = display_line
                for token in STRUCTURE_TOKENS:
                    stripped = stripped.replace(token, "??")
                if len(stripped) > width_limit:
                    problems.append(
                        f"line width {len(stripped)} > {width_limit}: {display_line!r}"
                    )
            if "__SRWG_" in new_payload:
                problems.append("internal placeholder present")
            if not problems:
                try:
                    encoders[family](new_payload)
                except Exception as error:  # noqa: BLE001
                    problems.append(f"encoder rejected: {error}")
            if problems:
                fail("; ".join(problems))
                seen.discard(stable_id)
                continue

            accepted.append(
                {
                    "id": stable_id,
                    "family": family,
                    "japanese": record["japanese_raw"],
                    "before": current,
                    "after": new_payload,
                }
            )

    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "accepted_corrections.json").write_text(
        json.dumps(accepted, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    (args.output / "rejected_corrections.json").write_text(
        json.dumps(rejected, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    summary = {
        "result_files": len(result_files),
        "accepted": len(accepted),
        "kept": kept,
        "rejected": len(rejected),
        "reviewed_ids": len(seen) + kept,
        "targets_total": len(targets),
    }
    (args.output / "validation_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
