"""Shared helpers for the OpenMS release scripts (stdlib only)."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from typing import Any

REPO = os.environ.get("OPENMS_REPO", "OpenMS/OpenMS")
REPO_URL = f"https://github.com/{REPO}.git"
TAP_REPO = os.environ.get("OPENMS_TAP_REPO", "OpenMS/homebrew-openms")
WEBSITE_REPO = os.environ.get("OPENMS_WEBSITE_REPO", "OpenMS/OpenMS-website")
ARCHIVE_BASE = os.environ.get("OPENMS_ARCHIVE_BASE", "https://archive.openms.de/openms")

VERSION_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")
TAG_RE = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


class GhError(RuntimeError):
    pass


def parse_version(text: str) -> tuple[int, int, int]:
    m = VERSION_RE.match(text.strip().lstrip("v"))
    if not m:
        raise ValueError(f"not a release version X.Y.Z: {text!r}")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def fmt_version(v: tuple[int, int, int]) -> str:
    return f"{v[0]}.{v[1]}.{v[2]}"


def run(cmd: list[str], cwd: str | None = None, check: bool = True) -> str:
    proc = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise RuntimeError(f"command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr.strip()}")
    return proc.stdout


def run_gh(args: list[str], check: bool = True) -> str:
    """Run the GitHub CLI. Tests replace this function."""
    if not shutil.which("gh"):
        raise GhError("the GitHub CLI 'gh' is not installed")
    proc = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise GhError(f"gh {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def gh_json(args: list[str]) -> Any:
    out = run_gh(args)
    return json.loads(out) if out.strip() else None


def http_get(url: str, headers: dict[str, str] | None = None, timeout: int = 60) -> tuple[int, bytes]:
    """GET a URL; returns (status, body). Status 0 means the request could not be made."""
    req = urllib.request.Request(url, headers={"User-Agent": "openms-release-skill", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read()
    except urllib.error.HTTPError as e:
        return e.code, e.read() if e.fp else b""
    except Exception as e:  # network blocked, DNS, TLS ...
        print(f"[http] {url}: {e}", file=sys.stderr)
        return 0, b""


def emit(result: Any, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2, sort_keys=False))
