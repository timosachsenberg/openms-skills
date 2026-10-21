#!/usr/bin/env python3
"""Point the OpenMS Bioconda recipes (openms-meta, pyopenms) at a release.

Run it in a checkout of bioconda/bioconda-recipes (for the upstream pull request) or
of the OpenMS fork's nightly branch (to keep the release branch of its recipes in sync).

  bioconda_bump.py --recipes-dir <bioconda-recipes>/recipes --version 3.7.0 \
      (--sha256 HEX | --tarball OpenMS-3.7.0.tar.gz | --download) \
      [--from-nightly <OpenMS/bioconda-recipes nightly>/recipes] [--json]

What it does per recipe:
  * --from-nightly: first copies the recipe directory from the OpenMS fork's nightly
    branch over the upstream one (files that exist only upstream are kept and listed). That recipe is the maintained one (dependencies follow develop) and carries
    both branches: 'dev' versions build from git, release versions from the tarball.
  * sets {% set version = "X.Y.Z" %} (keeps the trailing comment),
  * rewrites the release tarball URL to .../releases/download/v{{ version }}/OpenMS-{{ version }}.tar.gz
    (3.5.0 and older used release%2F<version>, which is a 404 for v-tags),
  * sets the sha256 of the non-dev source block,
  * resets build: number to 0,
  * lists the patches of the release source block. They were written against the
    previous release; the skill must check each still applies (patch --dry-run).
--download fetches https://github.com/OpenMS/OpenMS/releases/download/vX.Y.Z/OpenMS-X.Y.Z.tar.gz.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import emit, parse_version  # noqa: E402

RECIPES = ["openms-meta", "pyopenms"]
TARBALL_URL = "https://github.com/OpenMS/OpenMS/releases/download/v{v}/OpenMS-{v}.tar.gz"
URL_LINE = "url: https://github.com/OpenMS/OpenMS/releases/download/v{{ version }}/OpenMS-{{ version }}.tar.gz"


def sha256_stream(fh) -> str:
    h = hashlib.sha256()
    for chunk in iter(lambda: fh.read(1 << 20), b""):
        h.update(chunk)
    return h.hexdigest()


def check_patch(tarball: Path, patch: Path) -> str:
    """Dry-run a recipe patch against the release tarball (git archive layout, no top-level folder)."""
    if not shutil.which("patch"):
        return "unchecked: no 'patch' tool"
    work = Path(tempfile.mkdtemp())
    try:
        with tarfile.open(tarball) as tf:
            names = set()
            for line in patch.read_text(errors="replace").splitlines():
                if line.startswith(("--- a/", "+++ b/")):
                    names.add(line[6:].split("\t")[0].strip())
            members = [m for m in tf.getmembers() if m.name.lstrip("./") in names]
            tf.extractall(work, members=members, filter="data")
        def dry(*extra):
            return subprocess.run(["patch", "-p1", "--dry-run", "--batch", *extra, "-i", str(patch)],
                                  cwd=work, capture_output=True, text=True).returncode == 0
        if dry("--forward"):
            return "applies"
        if dry("--reverse"):
            return "already-applied"
        return "fails"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def bump(text: str, version: str, sha: str) -> tuple[str, dict]:
    info: dict = {}
    text, n = re.subn(r'(\{%\s*set\s+version\s*=\s*")[^"]*("\s*%\})', rf"\g<1>{version}\g<2>", text, count=1)
    info["version_set"] = n == 1
    # the release source block is the one with a tarball url (not git_url)
    m = re.search(r"(?m)^(?P<indent>[ \t]*)url:[ \t]*https://github\.com/OpenMS/OpenMS/[^\n]*OpenMS-\{\{\s*version\s*\}\}\.tar\.gz[ \t]*$", text)
    if not m:
        info["error"] = "no release tarball url found"
        return text, info
    old_url = m.group(0).strip()
    text = text[:m.start()] + m.group("indent") + URL_LINE + text[m.end():]
    info["url_changed"] = old_url != URL_LINE
    after = text[m.start():]
    s = re.search(r"(?m)^([ \t]*)sha256:[ \t]*([0-9a-fA-F]{64}|\S+)[ \t]*$", after)
    if not s:
        info["error"] = "no sha256 after the tarball url"
        return text, info
    abs_start = m.start() + s.start()
    abs_end = m.start() + s.end()
    info["old_sha256"] = s.group(2)
    text = text[:abs_start] + f"{s.group(1)}sha256: {sha}" + text[abs_end:]
    # patches listed in the same source block (until the next line starting at column 0 or a jinja tag)
    block = re.search(r"(?ms)patches:\s*\n(.*?)(?=^\S|^\{%)", text[m.start():])
    info["patches"] = re.findall(r"^\s*-\s*(\S+\.patch)", block.group(1), re.M) if block else []
    text, n = re.subn(r"(?ms)^(build:\s*\n\s*number:\s*)\d+", r"\g<1>0", text, count=1)
    info["build_number_reset"] = n == 1
    return text, info


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--recipes-dir", required=True)
    ap.add_argument("--version", required=True)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--sha256")
    g.add_argument("--tarball")
    g.add_argument("--download", action="store_true")
    ap.add_argument("--from-nightly", help="recipes dir of the OpenMS fork's nightly branch to copy from")
    ap.add_argument("--packages", nargs="+", default=RECIPES)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    parse_version(args.version)
    tarball = Path(args.tarball) if args.tarball else None
    if args.download:
        url = TARBALL_URL.format(v=args.version)
        tarball = Path(tempfile.mkdtemp()) / f"OpenMS-{args.version}.tar.gz"
        with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "openms-release"}),
                                    timeout=1800) as r, open(tarball, "wb") as out:
            shutil.copyfileobj(r, out)
    if tarball:
        with open(tarball, "rb") as fh:
            sha = sha256_stream(fh)
    else:
        sha = args.sha256.lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha):
        raise SystemExit(f"not a sha256: {sha}")

    recipes = Path(args.recipes_dir)
    report = {"version": args.version, "sha256": sha, "recipes": {}}
    for pkg in args.packages:
        upstream_only = []
        if args.from_nightly:
            src = Path(args.from_nightly) / pkg
            dst = recipes / pkg
            if dst.exists():
                upstream_only = sorted(str(f.relative_to(dst)) for f in dst.rglob("*")
                                       if f.is_file() and not (src / f.relative_to(dst)).exists())
            shutil.copytree(src, dst, dirs_exist_ok=True)
        meta = recipes / pkg / "meta.yaml"
        text, info = bump(meta.read_text(), args.version, sha)
        meta.write_text(text)
        missing = [p for p in info.get("patches", []) if not (recipes / pkg / p).exists()]
        if missing:
            info["missing_patch_files"] = missing
        if upstream_only:
            info["upstream_only_files"] = upstream_only
        if tarball and info.get("patches"):
            info["patch_check"] = {p: check_patch(tarball, recipes / pkg / p) for p in info["patches"]
                                   if p not in missing}
        report["recipes"][pkg] = info

    errors = [f"{k}: {v['error']}" for k, v in report["recipes"].items() if "error" in v]
    errors += [f"{k}: patch {p} {s}" for k, v in report["recipes"].items()
               for p, s in v.get("patch_check", {}).items() if s not in ("applies", "already-applied")]
    if args.json:
        emit(report, True)
    else:
        print(f"sha256 {sha}")
        for pkg, info in report["recipes"].items():
            print(f"{pkg}: {info}")
        for pkg, info in report["recipes"].items():
            for p in info.get("patches", []):
                state = info.get("patch_check", {}).get(p)
                if state == "applies":
                    print(f"OK {pkg}: patch {p} still applies; keep it unless the fix is upstream by now")
                elif state == "already-applied":
                    print(f"DROP {pkg}: patch {p} is already contained in the tarball; remove it from meta.yaml")
                elif state:
                    print(f"FIX {pkg}: patch {p} does not apply ({state}); first check whether OpenMS fixed the "
                          f"problem differently (git log/blame of the patched file, CHANGELOG) -> then drop it; "
                          f"otherwise rebase it")
                else:
                    print(f"REVIEW {pkg}: patch {p} unchecked (pass --tarball or --download to test it)")
            for f in info.get("upstream_only_files", []):
                print(f"REVIEW {pkg}: {f} exists only upstream (kept); delete it if it is obsolete")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
