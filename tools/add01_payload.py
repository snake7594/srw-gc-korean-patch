"""Structural handling of the add01 payload's speaker prefix.

An add01 payload is ``<speaker>KK<body>KK<body>...`` when the record has a
speaker and ``<body>KK<body>...`` when it does not. ``japanese_raw`` holds the
body only, so a payload carries exactly one more KK segment than its
``japanese_raw`` precisely when a speaker exists. That invariant holds for every
add01 target, and it is what this module trusts.

Do not identify the prefix by matching ``speaker_ko``. That map is derived from
``final_speaker_korean`` and disagrees with the name baked into 648 payloads
(隼人 -> map '핫토' vs payload '하야토'; 甲児 -> '코우' vs '코우지'). Matching on it
leaves the prefix attached, which inflates the body line count by one and lets
``"KK".join(lines)`` overwrite the speaker with the first line of dialogue.
"""

from __future__ import annotations


class Add01StructureError(ValueError):
    """A payload does not have the segment structure its record implies."""


def split_payload(record: dict) -> tuple[str | None, list[str]]:
    """Return ``(speaker_segment, body_segments)`` for an add01 record.

    ``speaker_segment`` is None when the record has no speaker. Raises
    Add01StructureError when the payload and japanese_raw disagree about how
    many segments there should be, so that inconsistent input fails loudly
    instead of being silently mangled.
    """
    payload = record["current_payload"]
    segments = payload.split("KK")
    has_speaker = bool(record.get("speaker_jp"))
    expected = len(record["japanese_raw"].split("KK")) + (1 if has_speaker else 0)
    if len(segments) != expected:
        raise Add01StructureError(
            f"{record.get('id', '?')}: payload has {len(segments)} KK segments, "
            f"japanese_raw with speaker={has_speaker} implies {expected}"
        )
    if has_speaker:
        return segments[0], segments[1:]
    return None, segments


def normalize_lines(
    lines: list[str], speaker_segment: str | None, expected_lines: int
) -> list[str]:
    """Drop a leading speaker name when an agent supplied one.

    Waves were told to exclude the speaker name and return body-only lines, but
    some returned it as ``lines[0]`` instead. Both spellings are accepted; the
    speaker segment itself always comes from the payload, never from the agent.
    """
    if (
        speaker_segment is not None
        and len(lines) == expected_lines + 1
        and lines[0] == speaker_segment
    ):
        return lines[1:]
    return lines


def build_payload(speaker_segment: str | None, lines: list[str]) -> str:
    """Rebuild a payload, keeping the speaker segment out of the agent's reach."""
    if speaker_segment is None:
        return "KK".join(lines)
    return "KK".join([speaker_segment, *lines])
