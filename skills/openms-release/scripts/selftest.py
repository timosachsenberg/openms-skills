#!/usr/bin/env python3
"""Offline self-test of the release scripts (mocked gh, no network, no pushes).

Usage: selftest.py [--repo-dir <OpenMS clone>]   (repo-dir enables the CHANGELOG/version tests)
Run it after editing the scripts or when the OpenMS pipeline changed.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import _common  # noqa: E402
import ci_status  # noqa: E402
import changelog  # noqa: E402

SHA = "a" * 40
FAILS: list[str] = []


def check(cond: bool, what: str) -> None:
    print(("PASS " if cond else "FAIL ") + what)
    if not cond:
        FAILS.append(what)


def fake_gh(table: dict):
    def run_gh(args, check=True):
        key = " ".join(args)
        for pat, out in table.items():
            if pat in key:
                return out if isinstance(out, str) else json.dumps(out)
        return "[]"
    return run_gh


def run_obj(wf, branch, status="completed", conclusion="success", event="workflow_dispatch", sha=SHA, rid=1):
    return {"databaseId": rid, "headSha": sha, "headBranch": branch, "status": status, "conclusion": conclusion,
            "event": event, "createdAt": "2026-10-11T02:00:00Z", "url": f"https://x/{wf}", "workflowName": wf,
            "displayTitle": wf}


def test_ci_status() -> None:
    arts = "\n".join([f"installer-nightly-2026.10.11-{p}" for p in ci_status.PLATFORMS] +
                     [f"sdk-nightly-2026.10.11-{p}" for p in ci_status.PLATFORMS] +
                     ["documentation", "OpenMS-nightly-2026.10.11.tar.gz"])
    def tap(sha, bottles=("libopenms", "openms", "openms-gui")):
        newer = [{"commit": {"message": f"{f}: add 3.7.0-pre.20261011 bottle."}} for f in bottles]
        return newer + [{"commit": {"message": "libopenms, openms, openms-gui 3.7.0-pre.20261011\n\n"
                                               f"Built from OpenMS/OpenMS@{sha}."}},
                        {"commit": {"message": "older"}}]
    table = {
        "--workflow release.yml --branch nightly": [run_obj("release.yml", "nightly")],
        "--workflow test.yml --branch develop": [run_obj("test.yml", "develop")],
        "--workflow pyopenms-wheels-cibuildwheel.yml --branch nightly": [run_obj("wheels", "nightly")],
        "--workflow bioconda_deploy.yaml --branch nightly": [run_obj("bioconda", "nightly")],
        "--workflow containerdeploy.yml --branch nightly": [run_obj("containers", "nightly")],
        "actions/runs/1/artifacts": arts,
        "homebrew-openms/commits": tap(SHA),
    }
    _common.run_gh = fake_gh(table)
    rows = ci_status.evaluate("candidate", SHA, None)
    check(ci_status.overall(rows) == 0, "candidate: all green -> exit 0")

    table["actions/runs/1/artifacts"] = arts.replace("sdk-nightly-2026.10.11-Windows-X64\n", "")
    rows = ci_status.evaluate("candidate", SHA, None)
    check(ci_status.overall(rows) == 1 and "sdk-*-Windows-X64" in rows[0]["detail"],
          "candidate: missing Windows SDK artifact -> failed")
    table["actions/runs/1/artifacts"] = arts

    table["--workflow bioconda_deploy.yaml --branch nightly"] = [run_obj("bioconda", "nightly", status="in_progress",
                                                                         conclusion=None)]
    check(ci_status.overall(ci_status.evaluate("candidate", SHA, None)) == 2, "candidate: pending run -> exit 2")

    table["--workflow bioconda_deploy.yaml --branch nightly"] = [run_obj("bioconda", "nightly", sha="b" * 40)]
    check(ci_status.overall(ci_status.evaluate("candidate", SHA, None)) == 2,
          "candidate: run for another SHA does not count")
    table["--workflow bioconda_deploy.yaml --branch nightly"] = [run_obj("bioconda", "nightly")]

    table["homebrew-openms/commits"] = tap("c" * 40)
    rows = ci_status.evaluate("candidate", SHA, None)
    check(ci_status.overall(rows) == 2 and "nightly.yml" in rows[-1]["detail"],
          "candidate: tap not built from SHA -> pending with dispatch hint")
    table["homebrew-openms/commits"] = tap(SHA, bottles=("libopenms",))
    rows = ci_status.evaluate("candidate", SHA, None)
    check(ci_status.overall(rows) == 2 and "openms-gui" in rows[-1]["detail"],
          "candidate: tap pinned but bottles missing -> pending")
    table["homebrew-openms/commits"] = tap(SHA)

    ttable = {
        "--workflow release.yml --branch v3.7.0": [run_obj("release.yml", "v3.7.0", event="push")],
        "--workflow pyopenms-wheels-cibuildwheel.yml --branch v3.7.0": [run_obj("w", "v3.7.0", event="push")],
        "--workflow containerdeploy.yml --branch v3.7.0": [run_obj("c", "v3.7.0", event="push")],
        "--workflow update_version_numbers.yml --branch v3.7.0": [run_obj("u", "v3.7.0", conclusion="failure")],
    }
    _common.run_gh = fake_gh(ttable)
    check(ci_status.overall(ci_status.evaluate("tag", SHA, "v3.7.0")) == 0,
          "tag: informational update_version_numbers failure does not fail the gate")
    ttable["--workflow release.yml --branch v3.7.0"] = [run_obj("release.yml", "v3.7.0", event="push",
                                                                conclusion="failure", sha="d" * 40)]
    check(ci_status.overall(ci_status.evaluate("tag", SHA, "v3.7.0")) == 2,
          "tag: failed run of an earlier tag on another commit is ignored")


def test_changelog(repo: Path) -> None:
    tmp = Path(tempfile.mkdtemp())
    shutil.copy(repo / "CHANGELOG", tmp / "CHANGELOG")
    lines = (tmp / "CHANGELOG").read_text().split("\n")
    hs = changelog.headers(lines)
    check(len(hs) > 5, "changelog: headers parsed")
    for idx, ver, status in hs[:3]:
        check(changelog.header_line(ver, status) == lines[idx], f"changelog: header {ver} reproduced byte-exact")
    cmd = [sys.executable, str(HERE / "changelog.py")]
    newest = hs[0][1]
    subprocess.run(cmd + ["finalize", "--version", newest, "--month", "October 2026", "--file",
                          str(tmp / "CHANGELOG")], check=True, capture_output=True)
    rc = subprocess.run(cmd + ["check", "--version", newest, "--file", str(tmp / "CHANGELOG")],
                        capture_output=True).returncode
    check(rc == 0, f"changelog: finalize makes {newest} pass check")
    shutil.rmtree(tmp)


def test_bioconda_bump() -> None:
    import bioconda_bump
    recipe = ('{% set name = "OpenMS" %}\n{% set version = "3.5.0" %}  # comment kept\n\n'
              '{% if \'dev\' in version %}\nsource:\n  git_url: https://github.com/OpenMS/OpenMS.git\n'
              '{% else %}\nsource:\n'
              '  url: https://github.com/OpenMS/OpenMS/releases/download/release%2F{{ version }}/OpenMS-{{ version }}.tar.gz\n'
              '  sha256: ' + "0" * 64 + '\n  patches:\n    - 0001-fix.patch\n{% endif %}\n\nbuild:\n  number: 3\n')
    out, info = bioconda_bump.bump(recipe, "3.7.0", "f" * 64)
    check('{% set version = "3.7.0" %}  # comment kept' in out, "bioconda: version set, comment kept")
    check("releases/download/v{{ version }}/OpenMS-{{ version }}.tar.gz" in out, "bioconda: url moved to v-tags")
    check(("sha256: " + "f" * 64) in out and "0" * 64 not in out, "bioconda: sha256 replaced")
    check("number: 0" in out, "bioconda: build number reset")
    check(info.get("patches") == ["0001-fix.patch"], "bioconda: patches listed")


def test_verify_develop() -> None:
    import verify_release as vr
    open_pr = [{"number": 2, "state": "OPEN", "url": "u", "title": "bump", "createdAt": "2026-10-20"},
               {"number": 1, "state": "MERGED", "url": "u", "title": "bump", "createdAt": "2026-09-30"}]
    _common.run_gh = fake_gh({"pr list": open_pr})
    check(vr.c_develop("3.6.1")[0]["state"] == "fail", "verify: open bump PR after a patch tag -> close it")
    check(vr.c_develop("3.7.0")[0]["state"] == "pending", "verify: open bump PR after a feature tag -> pending")
    _common.run_gh = fake_gh({"pr list": open_pr[1:]})
    check(vr.c_develop("3.6.1")[0]["state"] == "ok", "verify: only an old merged PR -> ok for a patch")
    rel = {"assets": [{"name": n} for n in ["OpenMS-3.6.1-Debian-Linux-x86_64.deb",
           "OpenMS-3.6.1-Debian-Linux-aarch64.deb", "OpenMS-3.6.1-macOS-Silicon.pkg", "OpenMS-3.6.1-Win64.exe",
           "OpenMS-3.6.1.tar.gz"]], "isDraft": False, "isPrerelease": False, "url": "u"}

    def gh(args, check=True):
        k = " ".join(args)
        if k.startswith("release view"):
            return json.dumps(rel)
        if "package_sdk.sh" in k:
            raise _common.GhError("HTTP 404")
        return "[]"
    _common.run_gh = gh
    check(vr.c_github("3.6.1")[0]["state"] == "ok", "verify: no SDK expected when the tree has no package_sdk.sh")


def test_testlab() -> None:
    tmp = Path(tempfile.mkdtemp())
    cfg = tmp / "t.json"
    cfg.write_text(json.dumps({"configured": True, "kind": "command", "command": "test {version} = 3.7.0"}))
    cmd = [sys.executable, str(HERE / "testlab_gate.py"), "--sha", "x; false", "--config", str(cfg)]
    check(subprocess.run(cmd + ["--version", "3.7.0"], capture_output=True).returncode == 0, "testlab: command pass")
    check(subprocess.run(cmd + ["--version", "3.7.1"], capture_output=True).returncode == 1, "testlab: command fail")
    cfg.write_text(json.dumps({"configured": False}))
    check(subprocess.run(cmd + ["--version", "3.7.0"], capture_output=True).returncode == 3,
          "testlab: unconfigured -> needs human")
    shutil.rmtree(tmp)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-dir")
    args = ap.parse_args()
    test_ci_status()
    test_bioconda_bump()
    test_verify_develop()
    test_testlab()
    if args.repo_dir:
        test_changelog(Path(args.repo_dir))
    print(f"\n{len(FAILS)} failure(s)")
    return 1 if FAILS else 0


if __name__ == "__main__":
    sys.exit(main())
