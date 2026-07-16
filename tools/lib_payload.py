"""Canonical handling of add02 library (도감) description payloads.

These are the records the v1.0.3 crash came from: the library viewer copies each
U+2192-delimited line into a fixed render buffer, so a line wider than 24
full-width cells overwrites the next buffer and can make the game read an
invalid address. The shipped build protects them with the reflow pass in
``apply_translation_quality_overrides.py``, and every payload ends with the
trailing arrow the pager consumes -- ``expected_missing_trailing_arrows`` is 0
in the v1.0.5 config, so dropping it would be a runtime change, not a cosmetic
one.

A raw agent rewrite is therefore never used as-is. It is canonicalized here with
the build's *own* reflow function, so the text stored in the override file is
byte-identical to what the build would produce and the build's reflow pass
becomes a no-op for it. Validating the reflowed form -- not the agent's raw
line -- is the only check that reflects what actually ships.
"""

from __future__ import annotations

import re

LIBRARY_DESCRIPTION_ID_RE = re.compile(r"^add02:b(?:040:r\d{4}:f2|041:r\d{4}:f3)$")
LIBRARY_LINE_BREAK = "→"
MAX_COLUMNS = 24
# v1.0.5 shipped expected_max_lines_after. Staying at or under the shipped
# maximum keeps the pager within a page count the retail build already renders.
MAX_VISIBLE_LINES = 31


class LibraryPayloadError(ValueError):
    """A library rewrite cannot be canonicalized into a shippable payload."""


def is_library_id(stable_id: str) -> bool:
    return bool(LIBRARY_DESCRIPTION_ID_RE.fullmatch(stable_id))


def join_lines(lines: list[str]) -> str:
    """Flatten an agent rewrite into one paragraph string.

    Agents return prose, sometimes as one long line and sometimes split across
    several. Layout is not theirs to decide: the reflow drops single arrows,
    keeps double-arrow paragraph gaps, and recomputes every break itself, so
    this only has to hand it one text with word boundaries intact.
    """
    return " ".join(line.strip() for line in lines if line.strip())


def canonicalize(lines: list[str], current_payload: str, reflow) -> str:
    """Return the exact payload the build would produce for this rewrite.

    ``reflow`` is ``apply_translation_quality_overrides.reflow_library_payload``
    -- the build's own function, passed in rather than reimplemented so the two
    can never drift.
    """
    text = join_lines(lines)
    if not text.strip():
        raise LibraryPayloadError("empty library rewrite")
    if any(character in text for character in "\r\n\t"):
        raise LibraryPayloadError("library rewrite contains a control character")
    if current_payload.endswith(LIBRARY_LINE_BREAK) and not text.endswith(
        LIBRARY_LINE_BREAK
    ):
        text += LIBRARY_LINE_BREAK
    try:
        corrected = reflow(text, MAX_COLUMNS)
    except ValueError as error:
        raise LibraryPayloadError(f"reflow refused the rewrite: {error}") from error

    segments = corrected.split(LIBRARY_LINE_BREAK)
    widest = max((len(segment) for segment in segments), default=0)
    if widest > MAX_COLUMNS:
        raise LibraryPayloadError(f"reflowed line width {widest} > {MAX_COLUMNS}")
    visible = len(segments) - int(corrected.endswith(LIBRARY_LINE_BREAK))
    if visible > MAX_VISIBLE_LINES:
        raise LibraryPayloadError(
            f"reflowed line count {visible} > shipped maximum {MAX_VISIBLE_LINES}"
        )
    if current_payload.endswith(LIBRARY_LINE_BREAK) and not corrected.endswith(
        LIBRARY_LINE_BREAK
    ):
        raise LibraryPayloadError("trailing pager arrow lost")
    return corrected
