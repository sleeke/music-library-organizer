#!/usr/bin/env python3
"""
Convert m3u playlists from Windows absolute paths to Linux relative paths.

Transformations (applied to every line in every m3u file under the `playlists/`
folder at the repo root):
  1. A leading "\\" (or "/") — i.e. a root path — is replaced with "../".
  2. Every remaining "\\" is replaced with "/".

Before:
    #EXTINF:218,U2-Beautiful Day (Dream Dance Remix)
    \Trance [Goa]\U2-Beautiful Day (Dream Dance Remix).mp3

After:
    #EXTINF:218,U2-Beautiful Day (Dream Dance Remix)
    ../Trance [Goa]/U2-Beautiful Day (Dream Dance Remix).mp3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parent.parent
PLAYLISTS_DIR = REPO_ROOT / "playlists"


def transform_line(line: str) -> str:
    """Convert one m3u line from a Windows absolute path to a Linux relative path.

    Only the path portion of a line is touched. Comment lines (starting with '#')
    and blank lines are returned unchanged.
    """
    stripped = line.lstrip()
    if not stripped or stripped.startswith("#"):
        return line

    # Preserve the original line ending so we don't disturb the file's newlines.
    line_ending = ""
    if line.endswith("\r\n"):
        body = line[:-2]
        line_ending = "\r\n"
    elif line.endswith("\n"):
        body = line[:-1]
        line_ending = "\n"
    else:
        body = line

    # Step 1: a leading path separator ("\" or "/") marks a root path; swap it for "../".
    if body.startswith("\\") or body.startswith("/"):
        body = "../" + body[1:]

    # Step 2: convert every remaining "\" to "/".
    body = body.replace("\\", "/")

    return body + line_ending


def convert_file(path: Path, dry_run: bool) -> tuple[int, int]:
    """Convert a single m3u file in place. Returns (lines_changed, total_lines)."""
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)

    converted = [transform_line(line) for line in lines]
    changed = sum(1 for a, b in zip(lines, converted) if a != b)

    if changed and not dry_run:
        path.write_text("".join(converted), encoding="utf-8")

    return changed, len(lines)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Convert m3u playlists in playlists/ to Linux relative paths."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would change without writing to any file.",
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=PLAYLISTS_DIR,
        help=f"Directory of m3u files (default: {PLAYLISTS_DIR}).",
    )
    args = parser.parse_args()

    playlists_dir: Path = args.path
    if not playlists_dir.is_dir():
        print(f"Playlists directory not found: {playlists_dir}", file=sys.stderr)
        return 1

    m3u_files = sorted(
        p for p in playlists_dir.iterdir() if p.is_file() and p.suffix.lower() in (".m3u", ".m3u8")
    )
    if not m3u_files:
        print(f"No .m3u/.m3u8 files found in {playlists_dir}.")
        return 0

    total_files_changed = 0
    for m3u in m3u_files:
        changed, total = convert_file(m3u, dry_run=args.dry_run)
        status = "would change" if args.dry_run else "changed"
        if changed:
            print(f"  {m3u.name}: {status} {changed}/{total} lines")
            total_files_changed += 1
        else:
            print(f"  {m3u.name}: no change ({total} lines)")

    verb = "Would convert" if args.dry_run else "Converted"
    print(f"\n{verb} {total_files_changed} of {len(m3u_files)} playlist(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
