"""Draw a deterministic QA sample from merged corrections, with JP context."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("merged", type=Path)
    parser.add_argument("extracted", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--per-family", type=int, default=60)
    args = parser.parse_args()

    targets = {}
    for family in ("add01", "bpilot", "add02", "dol"):
        source = args.extracted / f"mt_targets_{family}.jsonl"
        for line in source.read_text(encoding="utf-8").splitlines():
            if line:
                row = json.loads(line)
                targets[row["id"]] = row

    merged = json.loads(args.merged.read_text(encoding="utf-8"))
    by_family: dict[str, list] = {}
    for row in merged:
        by_family.setdefault(row["family"], []).append(row)

    sample = []
    for family, rows in sorted(by_family.items()):
        # Deterministic even spread across the id-sorted list.
        rows = sorted(rows, key=lambda r: r["id"])
        step = max(1, len(rows) // args.per_family)
        picked = rows[::step][: args.per_family]
        for row in picked:
            target = targets.get(row["id"], {})
            sample.append(
                {
                    "id": row["id"],
                    "family": family,
                    "japanese": target.get("japanese", ""),
                    "speaker": target.get("speaker_ko", ""),
                    "old_mt": target.get("current_korean", ""),
                    "new": row["after"],
                }
            )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(sample, ensure_ascii=False, indent=1), encoding="utf-8")
    counts = {family: len(rows) for family, rows in by_family.items()}
    print(json.dumps({"sample": len(sample), "population": counts}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
