"""Merge accepted corrections from every wave into one deduplicated set.

Later waves win over earlier ones for the same id (repair fixes a rejected
wave1 attempt; wave1 supersedes the pilot only where it re-touched an id). The
merged ``before`` for every entry is re-anchored to the *current v17 map* so the
override tool's before-drift guard passes regardless of which wave produced it.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

MAP_FILES = (
    "add01_replacements.json",
    "add02_replacements.json",
    "bpilot_replacements.json",
    "dol_all_replacements.json",
)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("maps_root", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--accepted",
        type=Path,
        action="append",
        required=True,
        help="accepted_corrections.json in precedence order, lowest first",
    )
    args = parser.parse_args()

    id_to_payload = {}
    for name in MAP_FILES:
        for stable_id, payload in load_json(args.maps_root / name).items():
            id_to_payload[stable_id] = payload

    merged = {}
    for accepted_path in args.accepted:
        for row in load_json(accepted_path):
            merged[row["id"]] = row  # later file wins

    out = []
    reanchored = 0
    dropped_noop = 0
    for stable_id, row in merged.items():
        current = id_to_payload.get(stable_id)
        if current is None:
            continue
        if row["after"] == current:
            dropped_noop += 1
            continue
        if row["before"] != current:
            reanchored += 1
        out.append(
            {
                "id": stable_id,
                "family": row["family"],
                "japanese": row["japanese"],
                "before": current,
                "after": row["after"],
            }
        )

    out.sort(key=lambda r: r["id"])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(
        json.dumps(
            {
                "merged_unique": len(merged),
                "written": len(out),
                "reanchored_before": reanchored,
                "dropped_noop": dropped_noop,
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
