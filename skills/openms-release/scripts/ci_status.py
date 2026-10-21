#!/usr/bin/env python3
"""Gate a release candidate on the OpenMS CI, or watch the runs a release tag started.

Needs an authenticated GitHub CLI (gh). Read-only: it never starts or changes runs.

  ci_status.py candidate --sha SHA [--wait MIN] [--json]
      Nightly gate for a develop commit (feature/major releases). update_nightly.yml
      fast-forwards `nightly` to develop and *dispatches* the build workflows, because
      its push uses GITHUB_TOKEN and therefore triggers no push workflows. Required,
      all on the same head SHA:
        release.yml                       on nightly  (installers deb/pkg/exe, SDK, docs, source tarball)
        test.yml                          on develop or nightly (5-way build + ctest)
        pyopenms-wheels-cibuildwheel.yml  on nightly  (abi3 wheels built and tested)
        bioconda_deploy.yaml              on nightly  (bioconda-utils lint/build/mulled test)
        containerdeploy.yml               on nightly  (images built, ctest stage)
      plus the Homebrew tap (OpenMS/homebrew-openms) having built bottles from SHA.
      Note: the Bioconda nightly recipe builds develop's tip at build time (git_rev: develop),
      which normally equals SHA but is not pinned to it.
      For release.yml the artifact list is checked for all four platforms.

  ci_status.py branch --ref releases/vX.Y.0 --sha SHA [--wait MIN]
      Patch-release gate: test.yml and pyopenms-wheels-cibuildwheel.yml on the branch.

  ci_status.py tag --tag vX.Y.Z --sha SHA [--wait MIN]
      Runs started by pushing the tag: release.yml, pyopenms-wheels-cibuildwheel.yml,
      containerdeploy.yml (required) and update_version_numbers.yml (reported). Pass the
      tagged commit as --sha so runs of an earlier, deleted tag of the same name are ignored.

Exit codes: 0 all required green, 1 something failed, 2 still pending/missing.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402
from _common import REPO, TAP_REPO, GhError, emit  # noqa: E402

RUN_FIELDS = "databaseId,headSha,headBranch,status,conclusion,event,createdAt,url,workflowName,displayTitle"
PLATFORMS = ["Linux-X64", "Linux-ARM64", "macOS-ARM64", "Windows-X64"]

CANDIDATE = [
    # (workflow file, branches to search, required)
    ("release.yml", ["nightly"], True),
    ("test.yml", ["develop", "nightly"], True),
    ("pyopenms-wheels-cibuildwheel.yml", ["nightly"], True),
    ("bioconda_deploy.yaml", ["nightly"], True),
    ("containerdeploy.yml", ["nightly"], True),
]
TAG = [
    ("release.yml", True),
    ("pyopenms-wheels-cibuildwheel.yml", True),
    ("containerdeploy.yml", True),
    ("update_version_numbers.yml", False),
]


def runs_for(workflow: str, branch: str, sha: str | None, repo: str = REPO) -> list[dict]:
    args = ["run", "list", "-R", repo, "--workflow", workflow, "--branch", branch,
            "--limit", "50", "--json", RUN_FIELDS]
    if sha:
        args += ["--commit", sha]
    runs = _common.gh_json(args) or []
    if sha:
        runs = [r for r in runs if r.get("headSha") == sha]
    return sorted(runs, key=lambda r: r.get("createdAt", ""), reverse=True)


def classify(run: dict | None) -> str:
    if run is None:
        return "missing"
    if run.get("status") != "completed":
        return "pending"
    return "ok" if run.get("conclusion") == "success" else "failed"


def artifact_names(run_id: int, repo: str = REPO) -> list[str]:
    out = _common.run_gh(["api", f"repos/{repo}/actions/runs/{run_id}/artifacts", "--paginate",
                          "--jq", ".artifacts[].name"])
    return [l.strip() for l in out.splitlines() if l.strip()]


def check_release_artifacts(names: list[str]) -> list[str]:
    missing = []
    for kind in ("installer", "sdk"):
        for plat in PLATFORMS:
            if not any(n.startswith(f"{kind}-") and n.endswith(f"-{plat}") for n in names):
                missing.append(f"{kind}-*-{plat}")
    if "documentation" not in names:
        missing.append("documentation")
    if not any(re.match(r"OpenMS-.*\.tar\.gz$", n) for n in names):
        missing.append("OpenMS-*.tar.gz (source)")
    return missing


def homebrew_status(sha: str) -> dict:
    """The tap's nightly commits "libopenms, openms, openms-gui <version>" with the body
    "Built from OpenMS/OpenMS@<sha>.", then one "<formula>: add <version> bottle." commit per
    formula. Search the recent history of main for that sequence (the tap re-pins daily, so
    the current formula alone is not enough)."""
    try:
        commits = _common.gh_json(["api", f"repos/{TAP_REPO}/commits?sha=main&per_page=100"]) or []
    except GhError as e:
        return {"check": "homebrew tap", "state": "unknown", "detail": str(e)[:200], "required": True}
    hint = f" -- dispatch: gh workflow run nightly.yml -R {TAP_REPO} -f sha={sha} -f force=true"
    for i, c in enumerate(commits):
        msg = c["commit"]["message"]
        if f"OpenMS/OpenMS@{sha}" in msg:
            version = msg.splitlines()[0].rsplit(" ", 1)[-1]
            newer = [x["commit"]["message"].splitlines()[0] for x in commits[:i]]
            missing = [f for f in ("libopenms", "openms", "openms-gui")
                       if f"{f}: add {version} bottle." not in newer]
            if not missing:
                return {"check": "homebrew tap", "state": "ok", "required": True,
                        "detail": f"bottles for {version} built from {sha[:12]}"}
            return {"check": "homebrew tap", "state": "pending", "required": True,
                    "detail": f"{version} pinned to {sha[:12]} but no bottles yet for {', '.join(missing)} "
                              f"(check the tap's nightly run: gh run list -R {TAP_REPO} --workflow nightly.yml)"}
    return {"check": "homebrew tap", "state": "pending", "required": True,
            "detail": f"no tap build from {sha[:12]} in the last {len(commits)} commits" + hint}


def evaluate(mode: str, sha: str | None, ref: str | None) -> list[dict]:
    rows: list[dict] = []
    if mode == "candidate":
        for wf, branches, required in CANDIDATE:
            best = None
            for b in branches:
                rs = runs_for(wf, b, sha)
                # prefer a successful run, then the newest one
                done = [r for r in rs if classify(r) == "ok"]
                cand = (done or rs or [None])[0]
                if cand and (best is None or classify(best) != "ok"):
                    best = cand
            row = {"check": wf, "state": classify(best), "required": required,
                   "detail": f"{best['event']} {best['headBranch']} {best['status']}/{best.get('conclusion')}"
                   if best else f"no run on {'/'.join(branches)} for {sha[:12]}",
                   "url": best["url"] if best else None}
            if wf == "release.yml" and best and classify(best) == "ok":
                miss = check_release_artifacts(artifact_names(best["databaseId"]))
                if miss:
                    row["state"] = "failed"
                    row["detail"] += f"; missing artifacts: {', '.join(miss)}"
            rows.append(row)
        rows.append(homebrew_status(sha))
    elif mode == "branch":
        for wf in ("test.yml", "pyopenms-wheels-cibuildwheel.yml"):
            rs = runs_for(wf, ref, sha)
            r = rs[0] if rs else None
            rows.append({"check": wf, "state": classify(r), "required": True,
                         "detail": (f"{r['event']} {r['status']}/{r.get('conclusion')}" if r else
                                    f"no run on {ref} @ {sha[:12]} -- start it: gh workflow run {wf} -R {REPO} --ref {ref}"),
                         "url": r["url"] if r else None})
    elif mode == "tag":
        for wf, required in TAG:
            rs = runs_for(wf, ref, sha)
            rs = [r for r in rs if r.get("headBranch") == ref]
            r = rs[0] if rs else None
            rows.append({"check": wf, "state": classify(r), "required": required,
                         "detail": f"{r['event']} {r['status']}/{r.get('conclusion')}" if r else "no run yet",
                         "url": r["url"] if r else None})
    return rows


def overall(rows: list[dict]) -> int:
    req = [r for r in rows if r.get("required")]
    if any(r["state"] == "failed" for r in req):
        return 1
    if all(r["state"] == "ok" for r in req):
        return 0
    return 2


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["candidate", "branch", "tag"])
    ap.add_argument("--sha")
    ap.add_argument("--ref", help="branch (mode branch)")
    ap.add_argument("--tag", help="tag name (mode tag)")
    ap.add_argument("--wait", type=int, default=0, help="minutes to poll while runs are pending")
    ap.add_argument("--interval", type=int, default=300, help="seconds between polls")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    if args.mode in ("candidate", "branch", "tag") and not args.sha:
        ap.error("--sha is required")
    if args.mode == "branch" and not args.ref:
        ap.error("--ref is required")
    if args.mode == "tag" and not args.tag:
        ap.error("--tag is required")
    ref = args.tag if args.mode == "tag" else args.ref

    deadline = time.time() + args.wait * 60
    while True:
        rows = evaluate(args.mode, args.sha, ref)
        code = overall(rows)
        if code != 2 or time.time() >= deadline:
            break
        time.sleep(args.interval)

    if args.json:
        emit({"mode": args.mode, "sha": args.sha, "ref": ref, "result": ["green", "failed", "pending"][code],
              "rows": rows}, True)
    else:
        for r in rows:
            req = "" if r.get("required") else " (info)"
            print(f"[{r['state']:7}] {r['check']}{req}: {r['detail']}" + (f"  {r['url']}" if r.get("url") else ""))
        print(["RESULT: green", "RESULT: failed", "RESULT: pending/missing"][code])
    return code


if __name__ == "__main__":
    sys.exit(main())
