#!/usr/bin/env python3
"""Work out the next OpenMS release: version, tag, source ref and release branch.

Reads the remote tags and branches of OpenMS/OpenMS (git ls-remote, no API token
needed) and the version that develop's CMakeLists.txt declares.

Release types (the skill asks the user which one):
  patch  X.Y.Z -> X.Y.(Z+1), cut from the release branch releases/vX.Y.0
  minor  X.Y.Z -> X.(Y+1).0, a promoted nightly of develop ("feature release")
  major  X.Y.Z -> (X+1).0.0, a promoted nightly of develop after a version bump

Usage:
  release_plan.py --type minor --repo-dir ~/src/OpenMS [--json]
  release_plan.py --type patch [--line 3.6] --repo-dir ...
  release_plan.py --type minor --version 3.7.0 ...   (explicit version, validated)

--repo-dir must be a clone of OpenMS/OpenMS; the script fetches origin/develop
(full history, never shallow) unless --no-fetch is given.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _common import REPO_URL, TAG_RE, emit, fmt_version, parse_version, run  # noqa: E402


def remote_refs(url: str) -> tuple[dict[tuple[int, int, int], str], dict[str, str]]:
    out = run(["git", "ls-remote", "--tags", "--heads", url])
    tags: dict[tuple[int, int, int], str] = {}
    peeled: dict[str, str] = {}
    heads: dict[str, str] = {}
    for line in out.splitlines():
        sha, ref = line.split("\t", 1)
        if ref.startswith("refs/heads/"):
            heads[ref[len("refs/heads/"):]] = sha
        elif ref.startswith("refs/tags/"):
            name = ref[len("refs/tags/"):]
            if name.endswith("^{}"):
                peeled[name[:-3]] = sha
            else:
                m = TAG_RE.match(name)
                if m:
                    tags[(int(m.group(1)), int(m.group(2)), int(m.group(3)))] = sha
    # annotated tags: use the commit they point to
    for v in list(tags):
        name = f"v{fmt_version(v)}"
        if name in peeled:
            tags[v] = peeled[name]
    return tags, heads


def cmake_version(repo_dir: str, ref: str) -> tuple[int, int, int]:
    text = run(["git", "-C", repo_dir, "show", f"{ref}:CMakeLists.txt"])
    parts = []
    for p in ("MAJOR", "MINOR", "PATCH"):
        m = re.search(rf'set\(OPENMS_PACKAGE_VERSION_{p}\s+"(\d+)"\)', text)
        if not m:
            raise SystemExit(f"could not read OPENMS_PACKAGE_VERSION_{p} from {ref}:CMakeLists.txt")
        parts.append(int(m.group(1)))
    return parts[0], parts[1], parts[2]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--type", required=True, choices=["patch", "minor", "major"])
    ap.add_argument("--repo-dir", required=True, help="clone of OpenMS/OpenMS")
    ap.add_argument("--line", help="patch only: release line X.Y (default: newest line)")
    ap.add_argument("--version", help="explicit target version; validated against the type")
    ap.add_argument("--no-fetch", action="store_true", help="do not fetch origin/develop")
    ap.add_argument("--url", default=REPO_URL)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not args.no_fetch:
        run(["git", "-C", args.repo_dir, "fetch", "--quiet", "origin", "develop"])
    tags, heads = remote_refs(args.url)
    if not tags:
        raise SystemExit("no vX.Y.Z tags found on the remote")
    latest = max(tags)
    dev = cmake_version(args.repo_dir, "origin/develop")

    errors: list[str] = []
    warnings: list[str] = []
    actions: list[str] = []
    plan: dict = {"type": args.type, "latest_release": fmt_version(latest),
                  "latest_release_sha": tags[latest], "develop_version": fmt_version(dev)}

    if args.type == "patch":
        line = tuple(int(x) for x in args.line.split(".")) if args.line else latest[:2]
        on_line = sorted(v for v in tags if v[:2] == line)
        if not on_line:
            raise SystemExit(f"no release on line {line[0]}.{line[1]} yet; a patch needs a vX.Y.0 tag")
        newest = on_line[-1]
        target = (line[0], line[1], newest[2] + 1)
        branch = f"releases/v{line[0]}.{line[1]}.0"
        plan.update(previous_tag=f"v{fmt_version(newest)}", release_branch=branch,
                    release_branch_exists=branch in heads,
                    source=f"branch {branch}")
        if branch not in heads:
            actions.append(f"create {branch} from tag v{line[0]}.{line[1]}.0 "
                           f"({tags[(line[0], line[1], 0)][:12]}) and set the repository variable "
                           f"CURRENT_RELEASE_BRANCH to it (cherry-pick-to-release.yml reads it)")
        if line != latest[:2]:
            warnings.append(f"{line[0]}.{line[1]} is not the newest line ({fmt_version(latest)}): release.yml "
                            "publishes with make_latest: true and moves the archive's 'latest' link; "
                            "fix both by hand after the release (see references/channels.md)")
    else:
        if args.type == "minor":
            target = (latest[0], latest[1] + 1, 0)
        else:
            target = (latest[0] + 1, 0, 0)
        plan.update(previous_tag=f"v{fmt_version(latest)}",
                    release_branch=f"releases/v{target[0]}.{target[1]}.0",
                    release_branch_exists=f"releases/v{target[0]}.{target[1]}.0" in heads,
                    source="nightly candidate (a commit of develop that the nightly pipeline built green)")
        if dev != target:
            if args.type == "major" and dev == (latest[0], latest[1] + 1, 0):
                actions.append(f"bump develop from {fmt_version(dev)} to {fmt_version(target)} in the release "
                               f"preparation PR (tools/update_version_numbers.sh {target[0]} {target[1]} {target[2]}, "
                               f"then merge the duplicate CHANGELOG header with changelog.py rename)")
            else:
                errors.append(f"develop declares {fmt_version(dev)}, expected {fmt_version(target)} for a "
                              f"{args.type} release after {fmt_version(latest)}")

    if args.version:
        want = parse_version(args.version)
        if want != target:
            errors.append(f"requested {args.version} but a {args.type} release after the current state is "
                          f"{fmt_version(target)}")
        target = want

    if target in tags:
        errors.append(f"tag v{fmt_version(target)} already exists ({tags[target][:12]})")

    plan.update(version=fmt_version(target), tag=f"v{fmt_version(target)}",
                actions=actions, warnings=warnings, errors=errors)

    if args.json:
        emit(plan, True)
    else:
        for k in ("type", "version", "tag", "previous_tag", "source", "release_branch",
                  "release_branch_exists", "latest_release", "develop_version"):
            print(f"{k:22} {plan.get(k)}")
        for title, items in (("ACTION", actions), ("WARNING", warnings), ("ERROR", errors)):
            for i in items:
                print(f"{title}: {i}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
