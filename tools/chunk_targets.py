"""Split extracted MT targets into per-agent chunk files."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import add01_payload

CHUNK_SIZES = {"add01": 70, "bpilot": 120, "add02": 100, "dol": 100}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("extracted", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    manifest = []
    for family, size in CHUNK_SIZES.items():
        source = args.extracted / f"mt_targets_{family}.jsonl"
        rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line]
        for row in rows:
            payload = row["current_payload"]
            if family == "add01":
                speaker_segment, body_segments = add01_payload.split_payload(row)
                # The name as baked into the payload, which is authoritative over
                # speaker_ko; agents write body lines only and never touch it.
                row["speaker_segment"] = speaker_segment or ""
                row["required_lines"] = len(body_segments)
            else:
                row["max_lines"] = payload.count("\n") + 1
        for index in range(0, len(rows), size):
            chunk = rows[index : index + size]
            name = f"chunk_{family}_{index // size:03d}.json"
            (args.output / name).write_text(
                json.dumps({"family": family, "records": chunk}, ensure_ascii=False, indent=1),
                encoding="utf-8",
            )
            manifest.append({"chunk": name, "family": family, "count": len(chunk)})
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    counts = {}
    for entry in manifest:
        counts[entry["family"]] = counts.get(entry["family"], 0) + 1
    print(json.dumps({"chunks": counts, "total": len(manifest)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
