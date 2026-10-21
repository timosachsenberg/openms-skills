#!/usr/bin/env python3
"""Check every distribution channel of an OpenMS release and print a status table.

Usage: verify_release.py --version X.Y.Z [--only github,pypi,...] [--json] [--md report.md]

Channels and what "ok" means:
  github      release vX.Y.Z published, not draft/prerelease, all expected assets present
              (SDK archives only if the tagged tree has tools/ci/package_sdk.sh)
  latest      GitHub's "latest" release is vX.Y.Z (expected for the newest line only)
  archive     archive.openms.de OpenMSInstaller/release/X.Y.Z lists the installers
  pypi        pyopenms X.Y.Z on PyPI with abi3 wheels for linux x86_64/aarch64, macOS arm64, win amd64
  wheels-archive  archive.openms.de pyopenms/release/X.Y.Z lists wheels
  containers  ghcr.io/openms/openms-{library,executables,tools,tools-thirdparty}:X.Y.Z exist
  bioconda    bioconda has openms, libopenms, openms-thirdparty and pyopenms X.Y.Z
  homebrew    a formula in OpenMS/homebrew-openms carries version X.Y.Z (see channels.md)
  docs        archive Documentation/release/X.Y.Z and pyopenms.readthedocs.io/en/vX.Y.Z/ answer 200
  website     announcement PR (branch releaseannouncementX.Y.Z) in OpenMS/OpenMS-website is merged
  develop     feature/major: bump PR update_package_number_<next> merged; patch: no such PR left open

States: ok, pending (expected later, e.g. bioconda review), fail, unknown (could not check).
Exit code 1 if any channel failed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _common  # noqa: E402
from _common import ARCHIVE_BASE, REPO, TAP_REPO, WEBSITE_REPO, GhError, emit, http_get, parse_version  # noqa: E402

ASSET_PATTERNS = {
    "deb x86_64": r"^OpenMS-{v}-Debian-Linux-x86_64\.deb$",
    "deb aarch64": r"^OpenMS-{v}-Debian-Linux-aarch64\.deb$",
    "macOS pkg": r"^OpenMS-{v}-macOS-.*\.pkg$",
    "Windows exe": r"^OpenMS-{v}-Win64\.exe$",
    "source tarball": r"^OpenMS-{v}\.tar\.gz$",
    "SDK Linux x86_64": r"^OpenMS-SDK-{v}-Linux-x86_64\.tar\.gz$",
    "SDK Linux aarch64": r"^OpenMS-SDK-{v}-Linux-aarch64\.tar\.gz$",
    "SDK macOS arm64": r"^OpenMS-SDK-{v}-macOS-arm64\.tar\.gz$",
    "SDK Windows x64": r"^OpenMS-SDK-{v}-Windows-x64\.zip$",
}
WHEEL_PLATFORMS = {"linux x86_64": r"manylinux.*x86_64", "linux aarch64": r"manylinux.*aarch64",
                   "macOS arm64": r"macosx.*arm64", "windows amd64": r"win_amd64"}
IMAGES = ["openms-library", "openms-executables", "openms-tools", "openms-tools-thirdparty"]
BIOCONDA = ["openms", "libopenms", "openms-thirdparty", "pyopenms"]


def row(channel, state, detail, link=None):
    return {"channel": channel, "state": state, "detail": detail, "link": link}


def c_github(v):
    try:
        rel = _common.gh_json(["release", "view", f"v{v}", "-R", REPO,
                               "--json", "assets,isDraft,isPrerelease,url,publishedAt"])
    except GhError as e:
        return [row("github", "pending" if "not found" in str(e).lower() else "unknown", str(e)[:200])]
    names = [a["name"] for a in rel.get("assets", [])]
    patterns = dict(ASSET_PATTERNS)
    try:  # the SDK exists only in trees that have its packaging script (3.7.0 on; not the 3.6 line)
        _common.run_gh(["api", f"repos/{REPO}/contents/tools/ci/package_sdk.sh?ref=v{v}", "--jq", ".name"])
    except GhError:
        patterns = {k: p for k, p in patterns.items() if not k.startswith("SDK")}
    missing = [k for k, pat in patterns.items()
               if not any(re.match(pat.format(v=re.escape(v)), n) for n in names)]
    state = "ok" if not missing and not rel["isDraft"] and not rel["isPrerelease"] else "fail"
    detail = f"{len(names)} assets" + (f"; missing: {', '.join(missing)}" if missing else "")
    if rel["isDraft"] or rel["isPrerelease"]:
        detail += "; draft/prerelease"
    return [row("github", state, detail, rel.get("url"))]


def c_latest(v):
    try:
        tag = _common.run_gh(["api", f"repos/{REPO}/releases/latest", "--jq", ".tag_name"]).strip()
    except GhError as e:
        return [row("latest", "unknown", str(e)[:200])]
    return [row("latest", "ok" if tag == f"v{v}" else "fail",
                f"GitHub latest = {tag}" + ("" if tag == f"v{v}" else " (wrong if this is the newest line; "
                                            "correct if you released an older line)"))]


def listing(url):
    status, body = http_get(url)
    return status, body.decode(errors="replace") if body else ""


def c_archive(v):
    url = f"{ARCHIVE_BASE}/OpenMSInstaller/release/{v}/"
    status, text = listing(url)
    if status == 0:
        return [row("archive", "unknown", "archive not reachable from here", url)]
    found = [k for k in ("deb", "pkg", "exe") if re.search(rf"OpenMS-{re.escape(v)}[^\"<]*\.{k}", text)]
    ok = status == 200 and len(found) == 3
    return [row("archive", "ok" if ok else "fail", f"HTTP {status}; installers: {found}", url)]


def c_pypi(v):
    status, body = http_get(f"https://pypi.org/pypi/pyopenms/{v}/json")
    link = f"https://pypi.org/project/pyopenms/{v}/"
    if status == 404:
        return [row("pypi", "pending", "not on PyPI (dispatch the wheel workflow with upload-to-pypi)", link)]
    if status != 200:
        return [row("pypi", "unknown", f"HTTP {status}", link)]
    files = [u["filename"] for u in json.loads(body)["urls"]]
    missing = [k for k, pat in WHEEL_PLATFORMS.items() if not any(re.search(pat, f) for f in files)]
    return [row("pypi", "ok" if not missing else "fail",
                f"{len(files)} files" + (f"; missing: {', '.join(missing)}" if missing else ""), link)]


def c_wheels_archive(v):
    url = f"{ARCHIVE_BASE}/pyopenms/release/{v}/"
    status, text = listing(url)
    if status == 0:
        return [row("wheels-archive", "unknown", "archive not reachable from here", url)]
    n = len(set(re.findall(r"pyopenms-[^\"<>]*\.whl", text)))
    return [row("wheels-archive", "ok" if status == 200 and n >= 4 else "fail", f"HTTP {status}; {n} wheels", url)]


def c_containers(v):
    rows = []
    for img in IMAGES:
        status, body = http_get(f"https://ghcr.io/token?scope=repository:openms/{img}:pull")
        if status != 200:
            rows.append(row(f"container {img}", "unknown", f"token HTTP {status}"))
            continue
        token = json.loads(body).get("token", "")
        status, _ = http_get(f"https://ghcr.io/v2/openms/{img}/manifests/{v}", headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json"})
        rows.append(row(f"container {img}", "ok" if status == 200 else ("fail" if status == 404 else "unknown"),
                        f"manifest HTTP {status}", f"https://ghcr.io/openms/{img}"))
    return rows


def c_bioconda(v):
    rows = []
    for pkg in BIOCONDA:
        status, body = http_get(f"https://api.anaconda.org/package/bioconda/{pkg}")
        link = f"https://anaconda.org/bioconda/{pkg}"
        if status != 200:
            rows.append(row(f"bioconda {pkg}", "unknown", f"HTTP {status}", link))
            continue
        versions = json.loads(body).get("versions", [])
        rows.append(row(f"bioconda {pkg}", "ok" if v in versions else "pending",
                        f"latest {json.loads(body).get('latest_version')}", link))
    return rows


def c_homebrew(v):
    rows = []
    try:
        listing_ = _common.gh_json(["api", f"repos/{TAP_REPO}/contents/Formula"]) or []
    except GhError as e:
        return [row("homebrew", "unknown", str(e)[:200])]
    hits = []
    for f in listing_:
        if not f["name"].endswith(".rb"):
            continue
        text = _common.run_gh(["api", "-H", "Accept: application/vnd.github.raw",
                               f"repos/{TAP_REPO}/contents/Formula/{f['name']}"])
        m = re.search(r'^\s*version "([^"]+)"', text, re.M)
        if m and m.group(1) == v:
            hits.append(f["name"])
    rows.append(row("homebrew", "ok" if hits else "pending",
                    f"formulae at {v}: {hits}" if hits else "no formula pinned to the release (channels.md: Homebrew)",
                    f"https://github.com/{TAP_REPO}"))
    return rows


def c_docs(v):
    rows = []
    for name, url in (("docs archive", f"{ARCHIVE_BASE}/Documentation/release/{v}/"),
                      ("pyopenms docs", f"https://pyopenms.readthedocs.io/en/v{v}/")):
        status, _ = http_get(url)
        rows.append(row(name, "ok" if status == 200 else ("unknown" if status == 0 else "fail"),
                        f"HTTP {status}", url))
    return rows


def prs_for(repo, head):
    return _common.gh_json(["pr", "list", "-R", repo, "--head", head, "--state", "all",
                            "--json", "number,state,url,title,createdAt"]) or []


def c_website(v):
    try:
        prs = prs_for(WEBSITE_REPO, f"releaseannouncement{v}")
    except GhError as e:
        return [row("website", "unknown", str(e)[:200])]
    if not prs:
        return [row("website", "pending", "no announcement PR yet (created by release.yml)")]
    pr = prs[0]
    return [row("website", "ok" if pr["state"] == "MERGED" else "pending", f"PR #{pr['number']} {pr['state']}",
                pr["url"])]


def c_develop(v):
    """update_version_numbers.yml runs on every v* tag and always opens a PR (the bump script
    inserts a CHANGELOG header even when the version does not change)."""
    M, m, z = parse_version(v)
    nxt = f"{M}.{m + 1}.0"
    try:
        prs = prs_for(REPO, f"update_package_number_{nxt}")
    except GhError as e:
        return [row("develop bump", "unknown", str(e)[:200])]
    pr = prs[0] if prs else None  # newest first; the branch name repeats across releases
    if z > 0:
        if pr and pr["state"] == "OPEN":
            return [row("develop bump", "fail", f"PR #{pr['number']} is open: close it unmerged -- after a patch "
                        f"tag it only adds an empty duplicate {nxt} CHANGELOG header to develop", pr["url"])]
        return [row("develop bump", "ok", "no open bump PR (patch release)")]
    if not pr:
        return [row("develop bump", "pending", f"no PR update_package_number_{nxt} yet")]
    state = "ok" if pr["state"] == "MERGED" else "pending"
    hint = "" if state == "ok" else " -- opened with GITHUB_TOKEN, so no CI ran: close and reopen it to start test.yml"
    return [row("develop bump", state, f"PR #{pr['number']} {pr['state']} ({pr['title']}){hint}", pr["url"])]


CHECKS = {"github": c_github, "latest": c_latest, "archive": c_archive, "pypi": c_pypi,
          "wheels-archive": c_wheels_archive, "containers": c_containers, "bioconda": c_bioconda,
          "homebrew": c_homebrew, "docs": c_docs, "website": c_website, "develop": c_develop}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", required=True)
    ap.add_argument("--only", help="comma-separated subset of: " + ",".join(CHECKS))
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--md", help="also write the table as Markdown to this file")
    args = ap.parse_args()
    v = args.version.lstrip("v")
    parse_version(v)
    names = args.only.split(",") if args.only else list(CHECKS)
    rows = []
    for n in names:
        try:
            rows += CHECKS[n](v)
        except Exception as e:  # one broken check must not hide the others
            rows.append(row(n, "unknown", f"check crashed: {e}"))
    md = ["| Channel | State | Detail |", "|---|---|---|"]
    for r in rows:
        link = f" ([link]({r['link']}))" if r.get("link") else ""
        md.append(f"| {r['channel']} | {r['state']} | {r['detail']}{link} |")
    if args.md:
        Path(args.md).write_text("\n".join(md) + "\n")
    if args.json:
        emit({"version": v, "rows": rows}, True)
    else:
        print("\n".join(md))
    return 1 if any(r["state"] == "fail" for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
