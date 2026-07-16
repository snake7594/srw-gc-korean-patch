"""Audit add01 corrections for a dropped speaker segment.

For add01 the payload is ``<speaker>KK<body line>KK<body line>...`` whenever the
record has a speaker. ``japanese_raw`` carries only the body, so the payload has
exactly one more KK segment than ``japanese_raw`` when a speaker exists -- that
invariant holds for every add01 target and is what this audit trusts.

The historical chunk/validate tooling stripped the speaker prefix only when the
payload literally started with ``speaker_ko + "KK"``. Where the speakers map
disagreed with the name baked into the payload the prefix stayed attached, so
the required line count was inflated by one and ``"KK".join(lines)`` overwrote
the speaker segment with the first body line.

This reports, per result file and for accepted_corrections.json, every entry
whose rebuilt payload changes segment 0 while a speaker exists.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path


def load_targets(extracted: Path) -> dict:
    targets = {}
    source = extracted / "mt_targets_add01.jsonl"
    for line in source.read_text(encoding="utf-8").splitlines():
        if line:
            row = json.loads(line)
            targets[row["id"]] = row
    return targets


def legacy_rebuild(record: dict, lines: list) -> str | None:
    """Reproduce exactly what the pre-fix validator would have accepted."""
    current = record["current_payload"]
    speaker_ko = record.get("speaker_ko", "")
    if speaker_ko and current.startswith(speaker_ko + "KK"):
        prefix = speaker_ko + "KK"
        body = current[len(prefix):]
    else:
        prefix = ""
        body = current
    if len(lines) != body.count("KK") + 1:
        return None
    if any("KK" in l for l in lines):
        return None
    return prefix + "KK".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extracted", type=Path)
    parser.add_argument("results", type=Path, help="dir containing result subdirs")
    parser.add_argument("--accepted", type=Path, action="append", default=[])
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()

    targets = load_targets(args.extracted)

    def has_speaker(record: dict) -> bool:
        return bool(record.get("speaker_jp"))

    def speaker_segment(record: dict) -> str:
        return record["current_payload"].split("KK")[0]

    # --- invariant check ---------------------------------------------------
    violations = [
        rid
        for rid, r in targets.items()
        if len(r["current_payload"].split("KK"))
        - len(r["japanese_raw"].split("KK"))
        != (1 if has_speaker(r) else 0)
    ]
    print(
        json.dumps(
            {
                "add01_targets": len(targets),
                "with_speaker": sum(1 for r in targets.values() if has_speaker(r)),
                "without_speaker": sum(1 for r in targets.values() if not has_speaker(r)),
                "segment_invariant_violations": len(violations),
            },
            ensure_ascii=False,
        )
    )

    damaged = []
    stats = collections.Counter()
    by_speaker = collections.Counter()

    # --- agent results -----------------------------------------------------
    for path in sorted(args.results.rglob("mt_out_chunk_add01_*.json")):
        entries = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(entries, dict):
            entries = entries.get("corrections", [])
        for entry in entries:
            stable_id = str(entry.get("id", ""))
            record = targets.get(stable_id)
            if record is None or entry.get("keep"):
                continue
            lines = entry.get("lines")
            if not isinstance(lines, list) or not lines:
                continue
            if not all(isinstance(l, str) for l in lines):
                continue
            rebuilt = legacy_rebuild(record, lines)
            if rebuilt is None:
                stats["legacy_rejected"] += 1
                continue
            stats["legacy_accepted"] += 1
            if not has_speaker(record):
                stats["no_speaker_ok"] += 1
                continue
            before0 = speaker_segment(record)
            after0 = rebuilt.split("KK")[0]
            if before0 == after0:
                stats["speaker_preserved"] += 1
                continue
            stats["speaker_DROPPED"] += 1
            by_speaker[(record["speaker_jp"], record.get("speaker_ko", ""), before0)] += 1
            damaged.append(
                {
                    "source": str(path.relative_to(args.results.parent)),
                    "id": stable_id,
                    "speaker_jp": record["speaker_jp"],
                    "speaker_ko_map": record.get("speaker_ko", ""),
                    "payload_speaker": before0,
                    "lost_to": after0,
                    "before": record["current_payload"],
                    "legacy_after": rebuilt,
                    "agent_lines": lines,
                }
            )

    print(json.dumps(dict(stats), ensure_ascii=False, indent=1))
    print("--- dropped speakers by name (payload name is authoritative) ---")
    for (jp, ko, payload_name), count in by_speaker.most_common():
        print(f"  {count:5d}  jp={jp!r} map={ko!r} payload={payload_name!r}")

    # --- already-validated corrections -------------------------------------
    for accepted_path in args.accepted:
        if not accepted_path.exists():
            continue
        rows = json.loads(accepted_path.read_text(encoding="utf-8"))
        hit = []
        for row in rows:
            record = targets.get(row["id"])
            if record is None or not has_speaker(record):
                continue
            if row["before"].split("KK")[0] != row["after"].split("KK")[0]:
                hit.append(row["id"])
        print(
            json.dumps(
                {
                    "accepted_file": str(accepted_path),
                    "entries": len(rows),
                    "speaker_dropped": len(hit),
                    "ids": hit[:20],
                },
                ensure_ascii=False,
            )
        )

    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(
            json.dumps(damaged, ensure_ascii=False, indent=1), encoding="utf-8"
        )
        print(f"wrote {len(damaged)} damaged entries -> {args.report}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
