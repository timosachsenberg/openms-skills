#!/usr/bin/env python3
"""Inspect and edit the release sections of OpenMS' CHANGELOG.

Section headers are three 90-character lines; the middle one reads

  ----                                OpenMS 3.6.0     (Released September 2026)        ----

Subcommands (all take --file, default ./CHANGELOG):
  status   --version V            header state and number of non-blank lines in the section
  check    --version V            exit 1 unless the section exists, is non-empty and released
  finalize --version V [--month "October 2026"]
                                   "(under development)" -> "(Released <Month YYYY>)"
  rename   --from A --to B        rename a section, e.g. 3.7.0 -> 4.0.0 for a major release
  dedupe   --version V            drop an empty duplicate header block for V, as left by
                                   tools/update_version_numbers.sh when the header existed already
  extract  --version V            print the release notes body exactly as release.yml cuts it

The extraction mirrors the "Create Change Log" step of .github/workflows/release.yml
(grep for '----[[:space:]]*OpenMS', fixed-string match of the version, body from two
lines after the header to two lines before the next header).
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import sys
from pathlib import Path

HEADER_RE = re.compile(r"^----\s*OpenMS\s+(\S+)\s*(\((.*?)\))?\s*----\s*$")
RULE = "-" * 90


def header_line(version: str, status: str | None) -> str:
    inner = "----" + " " * 32 + f"OpenMS {version}"
    if status:
        inner += " " * 5 + f"({status})"
    return inner.ljust(86) + "----"


def headers(lines: list[str]) -> list[tuple[int, str, str | None]]:
    out = []
    for i, line in enumerate(lines):
        m = HEADER_RE.match(line)
        if m:
            out.append((i, m.group(1), m.group(3)))
    return out


def find(lines: list[str], version: str) -> list[tuple[int, str, str | None]]:
    return [h for h in headers(lines) if h[1] == version]


def body(lines: list[str], idx: int) -> list[str]:
    hs = [h[0] for h in headers(lines)]
    nxt = next((h for h in hs if h > idx), None)
    end = (nxt - 1) if nxt is not None else len(lines)  # line before the next header's top rule
    return lines[idx + 2:end]


def release_yml_extract(lines: list[str], version: str) -> list[str]:
    # releases | this_version: grep -F -A1 on the header list, as in release.yml
    hs = [h[0] for h in headers(lines)]
    matches = [k for k, h in enumerate(hs) if version in lines[h]]
    if matches:
        k = matches[0]
        sel = hs[k:k + 2]
    else:
        sel = hs[:2]
    if len(sel) < 2:
        return lines[sel[0] + 2:] if sel else []
    beg, end = sel[0] + 1 + 2, sel[1] + 1 - 2  # 1-based, inclusive, like sed -n "beg,end p"
    return lines[beg - 1:end]


def month_now() -> str:
    return dt.date.today().strftime("%B %Y")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["status", "check", "finalize", "rename", "dedupe", "extract"])
    ap.add_argument("--file", default="CHANGELOG")
    ap.add_argument("--version")
    ap.add_argument("--month", help='e.g. "October 2026" (default: current month)')
    ap.add_argument("--from", dest="src")
    ap.add_argument("--to", dest="dst")
    args = ap.parse_args()

    path = Path(args.file)
    lines = path.read_text(encoding="utf-8").split("\n")

    if args.command == "rename":
        if not (args.src and args.dst):
            ap.error("rename needs --from and --to")
        hits = find(lines, args.src)
        if len(hits) != 1:
            raise SystemExit(f"expected one section for {args.src}, found {len(hits)}")
        idx, _, status = hits[0]
        lines[idx] = header_line(args.dst, status)
        path.write_text("\n".join(lines), encoding="utf-8")
        print(f"renamed section {args.src} -> {args.dst}")
        return 0

    if not args.version:
        ap.error(f"{args.command} needs --version")
    hits = find(lines, args.version)

    if args.command == "dedupe":
        empty = [h for h in hits if not any(l.strip() for l in body(lines, h[0]))]
        if len(hits) < 2 or not empty:
            print("nothing to do")
            return 0
        idx = empty[0][0]
        # header block = rule above, header, rule below, plus trailing blank lines of the empty body
        start = idx - 1
        stop = idx + 2
        while stop < len(lines) and not lines[stop].strip():
            stop += 1
        del lines[start:stop]
        path.write_text("\n".join(lines), encoding="utf-8")
        print(f"removed empty duplicate header for {args.version}")
        return 0

    if args.command == "extract":
        print("\n".join(release_yml_extract(lines, args.version)))
        if len(hits) != 1:
            print(f"WARNING: {len(hits)} headers for {args.version}; release.yml uses the first",
                  file=sys.stderr)
        loose = [h for h in headers(lines) if args.version in lines[h[0]] and h[1] != args.version]
        if loose:
            print(f"WARNING: release.yml's fixed-string match also hits {[h[1] for h in loose]}",
                  file=sys.stderr)
        return 0

    if not hits:
        print(f"{args.version}: no section")
        return 1
    if len(hits) > 1:
        print(f"{args.version}: {len(hits)} headers (duplicate; run dedupe)")
        return 1
    idx, _, status = hits[0]
    content = [l for l in body(lines, idx) if l.strip()]

    if args.command == "status":
        print(f"{args.version}: status={status!r} line={idx + 1} non_blank_lines={len(content)}")
        return 0

    if args.command == "check":
        problems = []
        if not content:
            problems.append("section is empty")
        if status is None or "under development" in status.lower():
            problems.append(f"header status is {status!r}, not released")
        if any(re.search(r"\b(TODO|FIXME|TBD)\b", l) for l in content):
            problems.append("section contains TODO/FIXME/TBD")
        for p in problems:
            print(f"FAIL {args.version}: {p}")
        if not problems:
            print(f"OK {args.version}: {len(content)} lines, status {status!r}")
        return 1 if problems else 0

    if args.command == "finalize":
        lines[idx] = header_line(args.version, f"Released {args.month or month_now()}")
        path.write_text("\n".join(lines), encoding="utf-8")
        print(lines[idx])
        return 0
    return 2


if __name__ == "__main__":
    sys.exit(main())
