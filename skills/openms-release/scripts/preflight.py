#!/usr/bin/env python3
"""Preflight for an OpenMS release: tools, GitHub permissions, and pipeline drift.

Usage: preflight.py --repo-dir <OpenMS clone at origin/develop> [--json]

1. Tools: git, gh (authenticated), python >= 3.10, patch.
2. Permissions (gh api repos/OpenMS/OpenMS .permissions): push is required to tag and
   dispatch/disable workflows; admin for repository variables (CURRENT_RELEASE_BRANCH).
   Also push to OpenMS/bioconda-recipes
   (the fork the Bioconda PR comes from), OpenMS/homebrew-openms and OpenMS/OpenMS-website.
3. Pipeline drift: the skill was written against OpenMS/OpenMS develop @ 91ba9e7
   (2026-10-11). Each marker below is a fact the skill relies on; a missing marker
   means the workflow changed and the matching part of references/pipeline.md must be
   re-read against the current file before acting on it.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402
from _common import REPO, TAP_REPO, GhError, emit  # noqa: E402

MARKERS = [
    (".github/workflows/release.yml", "- 'v[0-9]*'", "release.yml runs on v* tag pushes"),
    (".github/workflows/release.yml", "make_latest: true", "release.yml marks every release latest"),
    (".github/workflows/release.yml", "tools/ci/package_sdk.sh", "release.yml builds the developer SDK"),
    (".github/workflows/release.yml", "OpenMS/OpenMS-website", "release.yml opens the website announcement PR"),
    (".github/workflows/pyopenms-wheels-cibuildwheel.yml", "upload-to-pypi", "PyPI upload is a dispatch input"),
    (".github/workflows/pyopenms-wheels-cibuildwheel.yml", "name: pypi", "PyPI upload uses the 'pypi' environment"),
    (".github/workflows/update_nightly.yml", "gh workflow run release.yml --ref nightly",
     "the nightly dispatches release.yml"),
    (".github/workflows/update_nightly.yml", "gh workflow run test.yml --ref develop",
     "the nightly dispatches test.yml on develop"),
    (".github/workflows/update_version_numbers.yml", "NEW_MINOR=$((MINOR + 1))",
     "a tag bumps develop to the next minor"),
    (".github/workflows/weekly_patch_workflow.yml", "releases/v[0-9]+", "patch releases use releases/vX.Y.0"),
    (".github/workflows/weekly_patch_workflow.yml", "cron: '0 3 * * 2'", "weekly patch run Tue 03:00 UTC"),
    (".github/workflows/cherry-pick-to-release.yml", "CURRENT_RELEASE_BRANCH",
     "backports go to vars.CURRENT_RELEASE_BRANCH"),
    (".github/workflows/test.yml", "release/*", "test.yml push filter (singular release/*)"),
    (".github/workflows/bioconda_deploy.yaml", "openms-meta", "Bioconda nightly builds openms-meta"),
    (".github/workflows/containerdeploy.yml", "- 'v[0-9]*'", "containers build on v* tags"),
    ("tools/update_version_numbers.sh", "section_header=", "the bump script inserts a CHANGELOG header"),
]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo-dir", required=True)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    root = Path(args.repo_dir)
    rows: list[dict] = []

    def rec(area, name, ok, detail="", blocking=True):
        rows.append({"area": area, "check": name, "ok": ok, "detail": detail, "blocking": blocking})

    for tool in ("git", "gh", "patch"):
        rec("tools", tool, shutil.which(tool) is not None, "", tool != "patch")
    rec("tools", "python >= 3.10", sys.version_info >= (3, 10), sys.version.split()[0])

    try:
        user = _common.run_gh(["api", "user", "--jq", ".login"]).strip()
        rec("github", "gh authenticated", True, user)
    except GhError as e:
        rec("github", "gh authenticated", False, str(e)[:200])
        user = None

    if user:
        for repo, need in ((REPO, "push"), (REPO, "admin"), ("OpenMS/bioconda-recipes", "push"),
                           (TAP_REPO, "push"), ("OpenMS/OpenMS-website", "push")):
            try:
                perms = _common.gh_json(["api", f"repos/{repo}", "--jq", ".permissions"]) or {}
                ok = bool(perms.get(need))
                rec("github", f"{repo}: {need}", ok,
                    "" if ok else ("needed for the repository variable CURRENT_RELEASE_BRANCH"
                                   if need == "admin" else "needed"),
                    blocking=(repo == REPO and need == "push"))
            except GhError as e:
                rec("github", f"{repo}: {need}", False, str(e)[:200], blocking=(repo == REPO))

    for path, needle, meaning in MARKERS:
        f = root / path
        ok = f.exists() and needle in f.read_text(errors="replace")
        rec("pipeline", meaning, ok, "" if ok else f"marker {needle!r} not found in {path}: re-read it", False)

    blocking = [r for r in rows if not r["ok"] and r["blocking"]]
    if args.json:
        emit({"rows": rows, "ok": not blocking}, True)
    else:
        for r in rows:
            mark = "ok  " if r["ok"] else ("FAIL" if r["blocking"] else "warn")
            print(f"[{mark}] {r['area']:8} {r['check']}" + (f"  -- {r['detail']}" if r["detail"] else ""))
        print("PREFLIGHT " + ("OK" if not blocking else f"BLOCKED ({len(blocking)})"))
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
