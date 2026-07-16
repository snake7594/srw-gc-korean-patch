"""Build repair chunks from rejected corrections.

Each repair record carries the target's own fields (from the regenerated chunk
files, so ``required_lines`` is the fixed count) plus what the previous attempt
produced and why the validator refused it. Agents get the diagnosis, not just
the task, so a second attempt does not repeat the first one's mistake.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

CHUNK_SIZE = 40


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("chunks", type=Path, help="regenerated chunk directory")
    parser.add_argument("codebook", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument(
        "--rejected",
        type=Path,
        action="append",
        required=True,
        help="rejected_corrections.json (repeatable)",
    )
    args = parser.parse_args()

    hangul = set()
    with args.codebook.open(encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            hangul.add(row["target"])

    # index every record from the regenerated chunks by stable id
    records = {}
    for path in sorted(args.chunks.glob("chunk_*.json")):
        document = load_json(path)
        for record in document["records"]:
            records[record["id"]] = record

    repairs = []
    seen = set()
    for rejected_path in args.rejected:
        for row in load_json(rejected_path):
            stable_id = row.get("id")
            if not stable_id or stable_id in seen:
                continue
            record = records.get(stable_id)
            if record is None:
                continue
            seen.add(stable_id)
            reason = row["reason"]
            attempt = row.get("lines") or []
            if "encoder rejected" in reason:
                missing = sorted(
                    {
                        character
                        for line in attempt
                        for character in line
                        if "가" <= character <= "힣" and character not in hangul
                    }
                )
                diagnosis = (
                    "이전 시도가 폰트 코드북에 없는 한글 음절을 사용해 빌드가 거부했습니다. "
                    f"사용 금지 음절: {' '.join(missing) if missing else '(불명)'}. "
                    "해당 음절을 피해 같은 뜻을 다른 표현으로 다시 쓰세요."
                )
            elif "would replace the speaker segment" in reason:
                diagnosis = (
                    "이전 시도가 화자 이름 칸을 대사로 덮어썼습니다(줄 수를 1 많게 반환). "
                    "lines에는 화자 이름을 넣지 말고 본문만, required_lines와 정확히 같은 "
                    "개수로 반환하세요."
                )
            elif "line width" in reason:
                diagnosis = f"이전 시도가 줄 폭 제한을 넘었습니다: {reason}"
            elif "line count" in reason:
                diagnosis = f"이전 시도의 줄 수가 요구치와 달랐습니다: {reason}"
            else:
                diagnosis = f"이전 시도가 거부되었습니다: {reason}"

            repair = dict(record)
            repair["previous_attempt"] = attempt
            repair["reject_reason"] = reason
            repair["diagnosis"] = diagnosis
            repairs.append(repair)

    repairs.sort(key=lambda r: r["id"])
    args.output.mkdir(parents=True, exist_ok=True)
    manifest = []
    for index in range(0, len(repairs), CHUNK_SIZE):
        batch = repairs[index : index + CHUNK_SIZE]
        name = f"chunk_repair_{index // CHUNK_SIZE:03d}.json"
        (args.output / name).write_text(
            json.dumps({"family": "mixed", "records": batch}, ensure_ascii=False, indent=1),
            encoding="utf-8",
        )
        manifest.append({"chunk": name, "count": len(batch)})
    (args.output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(json.dumps({"repairs": len(repairs), "chunks": len(manifest)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
