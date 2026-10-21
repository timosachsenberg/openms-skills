#!/usr/bin/env python3
"""Run or look up the OpenMS testlab for a release candidate and report pass/fail.

The testlab is configured in ../testlab.json (see references/testlab.md). Kinds:

  github-workflow  dispatch (mode "dispatch") or look up (mode "lookup") a workflow run
                   in another repository; pass == conclusion "success".
  command          run a local command template; pass == exit code 0.
  manual           print what a person has to check; always exit 3.

Placeholders in inputs/command: {sha} {version} {tag} {nightly_date}

Usage: testlab_gate.py --sha SHA --version X.Y.Z [--tag vX.Y.Z] [--config PATH] [--json]
Exit codes: 0 pass, 1 fail, 2 timeout/pending, 3 not configured or manual.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402
from _common import emit  # noqa: E402

DEFAULT_CONFIG = Path(__file__).resolve().parent.parent / "testlab.json"
FIELDS = "databaseId,headSha,status,conclusion,event,createdAt,url,displayTitle"


def fill(template: str, ctx: dict, quote: bool = False) -> str:
    vals = {k: (shlex.quote(v) if quote else v) for k, v in ctx.items()}
    return template.format(**vals)


def gh_workflow(cfg: dict, ctx: dict, wait_min: int) -> tuple[int, str, str | None]:
    repo, wf, ref = cfg["repo"], cfg["workflow"], cfg.get("ref", "main")
    started = dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=30)
    if cfg.get("mode", "dispatch") == "dispatch":
        args = ["workflow", "run", wf, "-R", repo, "--ref", ref]
        for k, v in (cfg.get("inputs") or {}).items():
            args += ["-f", f"{k}={fill(str(v), ctx)}"]
        _common.run_gh(args)
        time.sleep(15)
    match = cfg.get("match_title")  # optional: substring the run title must contain, e.g. "{sha}"
    deadline = time.time() + wait_min * 60
    while True:
        runs = _common.gh_json(["run", "list", "-R", repo, "--workflow", wf, "--limit", "30", "--json", FIELDS]) or []
        if cfg.get("mode", "dispatch") == "dispatch":
            runs = [r for r in runs if r["createdAt"] >= started.strftime("%Y-%m-%dT%H:%M:%SZ")]
        if match:
            runs = [r for r in runs if fill(match, ctx) in (r.get("displayTitle") or "")]
        run = runs[0] if runs else None
        if run and run["status"] == "completed":
            ok = run["conclusion"] == "success"
            return (0 if ok else 1), f"{wf} {run['conclusion']}", run["url"]
        if time.time() >= deadline:
            return 2, (f"{wf} {run['status']}" if run else f"no matching run of {wf} in {repo}"), \
                (run or {}).get("url")
        time.sleep(cfg.get("poll_seconds", 300))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sha", required=True)
    ap.add_argument("--version", required=True)
    ap.add_argument("--tag")
    ap.add_argument("--config", default=str(DEFAULT_CONFIG))
    ap.add_argument("--wait", type=int, help="minutes to wait (default: timeout_minutes from config)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    cfg = json.loads(Path(args.config).read_text())
    ctx = {"sha": args.sha, "version": args.version, "tag": args.tag or f"v{args.version}",
           "nightly_date": dt.date.today().strftime("%Y.%m.%d")}
    if not cfg.get("configured"):
        res = (3, "testlab is not configured: ask the user how the testlab is started and where its "
                  "verdict is read, then fill testlab.json (references/testlab.md)", None)
    elif cfg["kind"] == "github-workflow":
        res = gh_workflow(cfg, ctx, args.wait if args.wait is not None else cfg.get("timeout_minutes", 360))
    elif cfg["kind"] == "command":
        proc = subprocess.run(fill(cfg["command"], ctx, quote=True), shell=True, capture_output=True, text=True,
                              timeout=(args.wait or cfg.get("timeout_minutes", 360)) * 60)
        tail = (proc.stdout + proc.stderr).strip().splitlines()[-5:]
        res = (0 if proc.returncode == 0 else 1), " | ".join(tail), cfg.get("report_url")
    else:
        res = (3, "manual testlab: " + fill(cfg.get("instructions", "ask the user for the testlab verdict"), ctx),
               cfg.get("report_url"))

    code, detail, url = res
    if url and "{" in url:
        url = fill(url, ctx)
    state ={0: "pass", 1: "fail", 2: "pending", 3: "needs-human"}[code]
    if args.json:
        emit({"state": state, "detail": detail, "url": url, "sha": args.sha}, True)
    else:
        print(f"[{state}] testlab: {detail}" + (f"  {url}" if url else ""))
    return code


if __name__ == "__main__":
    sys.exit(main())
