"""Assemble the Japanese binaries from a map directory and relocate them into
the retail ISO, in one step.

This is the driver for the chain the release process has always used --
``assemble_japanese_binaries`` followed by ``iso_relocator.build_iso`` -- which
was previously invoked by hand. Having it as a script makes a release
reproducible from recorded inputs instead of remembered ones.

``--expect-sha`` is the reproducibility gate: rebuild a shipped release from its
own maps and require the published ISO hash before trusting the driver for a new
one. v1.0.6 was produced only after this reproduced v1.0.5 byte for byte.

Every path is an argument: nothing here assumes a particular machine's layout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

TOOLS_DIR = Path(__file__).resolve().parent

ISO_REPLACEMENTS = (
    "add00dat.bin",
    "add01dat.bin",
    "add02dat.bin",
    "bpilot.pak",
    "font.pak",
    "opening.bnr",
)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest().upper()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--maps", type=Path, required=True, help="replacement map directory")
    parser.add_argument("--build", type=Path, required=True, help="new binary output directory")
    parser.add_argument("--iso", type=Path, required=True, help="destination ISO")
    parser.add_argument("--source-iso", type=Path, required=True, help="unmodified Japanese retail ISO")
    parser.add_argument("--codebook", type=Path, required=True)
    parser.add_argument("--font", type=Path, required=True, help="Korean font.pak")
    parser.add_argument("--original-font", type=Path, required=True)
    parser.add_argument("--original", type=Path, required=True, help="extracted retail file directory")
    parser.add_argument("--original-bpilot", type=Path, required=True)
    parser.add_argument("--add00", type=Path, required=True, help="Korean add00dat.bin")
    parser.add_argument("--opening", type=Path, required=True, help="Korean opening.bnr")
    parser.add_argument(
        "--expect-sha",
        default=None,
        help="require this final ISO SHA-256; use to reproduce a shipped release",
    )
    args = parser.parse_args()

    if args.build.exists():
        raise FileExistsError(args.build)
    if args.iso.exists():
        raise FileExistsError(args.iso)

    sys.path.insert(0, str(TOOLS_DIR))
    import assemble_japanese_binaries
    import iso_relocator

    argv = [
        "assemble_japanese_binaries.py",
        "--root", str(args.maps),
        "--output", str(args.build),
        "--codebook", str(args.codebook),
        "--font", str(args.font),
        "--original-font", str(args.original_font),
        "--original", str(args.original),
        "--original-bpilot", str(args.original_bpilot),
        "--add00", str(args.add00),
        "--opening", str(args.opening),
    ]
    saved = sys.argv
    sys.argv = argv
    try:
        code = assemble_japanese_binaries.main()
    finally:
        sys.argv = saved
    if code != 0:
        raise RuntimeError(f"assemble_japanese_binaries returned {code}")

    replacements = {name: args.build / name for name in ISO_REPLACEMENTS}
    report = iso_relocator.build_iso(
        source=args.source_iso,
        destination=args.iso,
        replacements=replacements,
        dol=args.build / "Start.dol",
        report_path=args.build / "iso_build_report.json",
    )

    final_sha = sha256_path(args.iso)
    summary = {
        "maps": str(args.maps),
        "iso": str(args.iso),
        "iso_sha256": final_sha,
        "iso_size": args.iso.stat().st_size,
        "source_sha256": report["source_sha256"],
        "build_sha256": {
            name: sha256_path(args.build / name)
            for name in (*ISO_REPLACEMENTS, "Start.dol")
        },
    }
    (args.build / "build_summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))

    if args.expect_sha and final_sha != args.expect_sha.upper():
        raise SystemExit(
            f"reproducibility check failed: ISO SHA-256 {final_sha} "
            f"!= expected {args.expect_sha.upper()}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
