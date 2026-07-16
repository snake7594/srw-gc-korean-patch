"""Build an apply_translation_quality_overrides-compatible overrides file
from validated MT corrections.

The output targets a SECOND correction pass whose input root is the current
final maps (v17). expected_inputs hashes and the library-reflow expectations
are computed by simulating the tool's own logic via its imported functions,
so a subsequent real run must pass or something genuinely drifted.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from pathlib import Path

MAP_FILES = (
    "add01_replacements.json",
    "add02_replacements.json",
    "bpilot_replacements.json",
    "dol_all_replacements.json",
)
NAME_INPUT_FILE = "dol_name_input_replacements.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def import_tool(tools_dir: Path):
    spec = importlib.util.spec_from_file_location(
        "apply_tqo", tools_dir / "apply_translation_quality_overrides.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("master", type=Path)
    parser.add_argument("maps_root", type=Path)
    parser.add_argument("accepted", type=Path, help="accepted_corrections.json")
    parser.add_argument("tools", type=Path, help="publish tools directory")
    parser.add_argument("output", type=Path, help="overrides JSON to write")
    parser.add_argument("--provenance", default="llm-mt-quality-review-2026-07")
    args = parser.parse_args()

    tool = import_tool(args.tools)
    corrections = load_json(args.accepted)

    seen = set()
    for entry in corrections:
        if entry["id"] in seen:
            raise ValueError(f"duplicate correction id: {entry['id']}")
        seen.add(entry["id"])

    expected_inputs = {"master": sha256(args.master)}
    for name in (*MAP_FILES, NAME_INPUT_FILE):
        expected_inputs[name] = sha256(args.maps_root / name)

    # --- simulate: payload overrides then library reflow --------------------
    maps = {name: load_json(args.maps_root / name) for name in MAP_FILES}
    id_to_file = {}
    for name, mapping in maps.items():
        for stable_id in mapping:
            id_to_file[stable_id] = name

    changed_ids = set()
    for entry in corrections:
        stable_id = entry["id"]
        filename = id_to_file.get(stable_id)
        if filename is None:
            raise ValueError(f"correction id not in production maps: {stable_id}")
        actual = maps[filename][stable_id]
        if actual != entry["before"]:
            raise ValueError(f"{stable_id}: before drift against maps_root")
        tool.validate_payload_change(entry["before"], entry["after"], stable_id)
        maps[filename][stable_id] = entry["after"]
        if actual != entry["after"]:
            changed_ids.add(stable_id)

    add02_mapping = maps["add02_replacements.json"]
    reflowed_ids = []
    inserted_breaks = 0
    max_columns_before = 0
    max_columns_after = 0
    max_lines_after = 0
    normalized_ascii_characters = 0
    missing_trailing_arrows = 0
    reviewed_records = 0
    for stable_id, payload in list(add02_mapping.items()):
        if not tool.LIBRARY_DESCRIPTION_ID_RE.fullmatch(stable_id):
            continue
        reviewed_records += 1
        before_segments = payload.split(tool.LIBRARY_LINE_BREAK)
        max_columns_before = max(
            max_columns_before, max((len(v) for v in before_segments), default=0)
        )
        corrected = tool.reflow_library_payload(payload, 24)
        _, normalized_count = tool.normalize_library_width(payload)
        normalized_ascii_characters += normalized_count
        after_segments = corrected.split(tool.LIBRARY_LINE_BREAK)
        visible = len(after_segments) - int(corrected.endswith(tool.LIBRARY_LINE_BREAK))
        max_lines_after = max(max_lines_after, visible)
        if not corrected.endswith(tool.LIBRARY_LINE_BREAK):
            missing_trailing_arrows += 1
        max_columns_after = max(
            max_columns_after, max((len(v) for v in after_segments), default=0)
        )
        if corrected == payload:
            continue
        reflowed_ids.append(stable_id)
        inserted_breaks += corrected.count(tool.LIBRARY_LINE_BREAK) - payload.count(
            tool.LIBRARY_LINE_BREAK
        )
        changed_ids.add(stable_id)

    document = {
        "schema": "srw-gc-pdf-translation-quality-v1",
        "description": (
            "기계번역 잔여분(add01/bpilot/add02/dol)에 대한 LLM 기반 번역 품질 교정. "
            "v1.0.5 최종 맵(v17)을 입력으로 하는 2차 교정 패스."
        ),
        "reference_pdfs": [],
        "policy": [
            "일본어 원문과 전후 문맥을 함께 대조해 기계번역 문장을 자연스러운 한국어로 교정한다.",
            "구조 토큰(KK, <AA>, <FF>, <TT>)의 개수와 형태를 보존한다.",
            "한글은 런타임 코드북에 존재하는 음절만 사용한다 (검증기에서 실제 인코더로 확인).",
        ],
        "library_reflow": {
            "description": "인물·로봇 도감 런타임 버퍼를 보호하는 U+2192 줄바꿈",
            "max_columns": 24,
            "expected_max_columns": 24,
            "expected_reviewed_records": reviewed_records,
            "expected_reflowed_records": len(reflowed_ids),
            "expected_inserted_breaks": inserted_breaks,
            "expected_max_columns_before": max_columns_before,
            "expected_max_columns_after": max_columns_after,
            "expected_max_lines_after": max_lines_after,
            "expected_normalized_ascii_characters": normalized_ascii_characters,
            "expected_missing_trailing_arrows": missing_trailing_arrows,
        },
        "expected_inputs": expected_inputs,
        "context_replacements": [],
        "payload_overrides": [
            {
                "id": entry["id"],
                "japanese": entry["japanese"],
                "before": entry["before"],
                "after": entry["after"],
                "pdf": args.provenance,
                "page": 0,
            }
            for entry in corrections
        ],
        "dialogue_overrides": [],
        "expected_payload_override_count": len(corrections),
        "expected_dialogue_override_count": 0,
        "expected_changed_record_count": len(changed_ids),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(document, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "payload_overrides": len(corrections),
                "expected_changed_record_count": len(changed_ids),
                "reflowed_records": len(reflowed_ids),
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
