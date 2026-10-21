#!/usr/bin/env python3
"""Check that every place carrying the OpenMS version agrees with the release version.

Usage: check_versions.py --repo-dir <checkout at the candidate commit> --expect X.Y.Z [--stage prep|release] [--json]

Hard checks (exit 1 on mismatch) are the files tools/update_version_numbers.sh
writes, because CMake, the class tests and the TOPP tests compare them:
  CMakeLists.txt, VersionInfo_test.cpp, vcpkg.json, src/tests/topp/*.ini and
  INIUpdater_1_noupdate.toppas, and the CHANGELOG section.
With --stage release the CHANGELOG section must also be non-empty and dated.

Soft checks (warnings) are files CI overrides or that only affect docs:
  src/pyOpenMS/pyproject.toml (the wheel workflow rewrites "version ="),
  doc/pyopenms/docs/source/conf.py and _static/switcher.json (pyOpenMS docs).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import emit, parse_version  # noqa: E402
import changelog  # noqa: E402

INI_RE = re.compile(r'<ITEM name="version" value="([^"]*)" type="string"')


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-dir", required=True)
    ap.add_argument("--expect", required=True)
    ap.add_argument("--stage", choices=["prep", "release"], default="release")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    root = Path(args.repo_dir)
    v = parse_version(args.expect)
    vs = args.expect
    hard: list[dict] = []
    soft: list[dict] = []

    def rec(lst, name, found, ok, note=""):
        lst.append({"check": name, "found": found, "ok": ok, "note": note})

    text = (root / "CMakeLists.txt").read_text()
    got = []
    for p in ("MAJOR", "MINOR", "PATCH"):
        m = re.search(rf'set\(OPENMS_PACKAGE_VERSION_{p}\s+"(\d+)"\)', text)
        got.append(int(m.group(1)) if m else None)
    rec(hard, "CMakeLists.txt OPENMS_PACKAGE_VERSION_*", ".".join(map(str, got)), tuple(got) == v)

    t = (root / "src/tests/class_tests/openms/source/VersionInfo_test.cpp").read_text()
    got = [re.search(rf"detail\.version_{k}\s*=\s*(\d+);", t) for k in ("major", "minor", "patch")]
    got = [int(m.group(1)) if m else None for m in got]
    rec(hard, "VersionInfo_test.cpp", ".".join(map(str, got)), tuple(got) == v)

    vj = json.loads((root / "vcpkg.json").read_text())
    rec(hard, "vcpkg.json version-string", vj.get("version-string"), vj.get("version-string") == vs)

    bad = []
    n = 0
    files = list((root / "src/tests/topp").rglob("*.ini")) + [root / "src/tests/topp/INIUpdater_1_noupdate.toppas"]
    for f in files:
        if not f.exists():
            continue
        vals = INI_RE.findall(f.read_text(errors="replace"))
        if vals:
            n += 1
            if any(x != vs for x in vals):
                bad.append(f"{f.relative_to(root)}={sorted(set(vals))}")
    rec(hard, f"TOPP test INI/TOPPAS version items ({n} files)", f"{len(bad)} mismatching",
        not bad, "; ".join(bad[:5]) + (" ..." if len(bad) > 5 else ""))

    cl = (root / "CHANGELOG").read_text().split("\n")
    hits = changelog.find(cl, vs)
    if len(hits) != 1:
        rec(hard, "CHANGELOG section", f"{len(hits)} headers", False)
    else:
        idx, _, status = hits[0]
        nonblank = sum(1 for l in changelog.body(cl, idx) if l.strip())
        ok = True
        note = ""
        if args.stage == "release":
            if nonblank == 0:
                ok, note = False, "empty: the GitHub release notes would be empty"
            elif status is None or "under development" in status.lower():
                ok, note = False, "header still says under development"
        rec(hard, "CHANGELOG section", f"status={status!r}, {nonblank} lines", ok, note)

    pp = root / "src/pyOpenMS/pyproject.toml"
    if pp.exists():
        m = re.search(r'^version\s*=\s*"([^"]*)"', pp.read_text(), re.M)
        found = m.group(1) if m else None
        rec(soft, "src/pyOpenMS/pyproject.toml version", found, found == vs,
            "CI rewrites it for wheels; sdists and local builds use it")

    conf = root / "doc/pyopenms/docs/source/conf.py"
    if conf.exists():
        m = re.search(r'^version\s*=\s*"([^"]*)"', conf.read_text(), re.M)
        found = m.group(1) if m else None
        rec(soft, "pyOpenMS docs conf.py version", found, found == vs)

    sw = root / "doc/pyopenms/docs/source/_static/switcher.json"
    if sw.exists():
        try:
            entries = json.loads(sw.read_text())
            names = [e.get("version") for e in entries]
            has = vs in names
            rec(soft, "pyOpenMS docs switcher.json", f"versions={names[:4]}...", has,
                "" if has else f"add an entry for {vs} (url https://pyopenms.readthedocs.io/en/v{vs}/)")
        except json.JSONDecodeError as e:
            rec(soft, "pyOpenMS docs switcher.json", "invalid JSON", False, str(e))

    failed = [c for c in hard if not c["ok"]]
    if args.json:
        emit({"expect": vs, "stage": args.stage, "hard": hard, "soft": soft, "ok": not failed}, True)
    else:
        for lst, tag in ((hard, "HARD"), (soft, "soft")):
            for c in lst:
                mark = "ok  " if c["ok"] else ("FAIL" if tag == "HARD" else "warn")
                note = f"  -- {c['note']}" if c["note"] and not c["ok"] else ""
                print(f"[{mark}] {tag} {c['check']}: {c['found']}{note}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
