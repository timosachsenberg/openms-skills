# openms-skills

Claude skills that take tedious OpenMS maintenance work off your hands.

| Skill | What it does |
|---|---|
| [`openms-release`](skills/openms-release/SKILL.md) | Runs an OpenMS release end to end: patch releases from `releases/vX.Y.0`, feature/major releases by promoting a green nightly of `develop`. Gated by the nightly pipeline and the testlab, and published to GitHub (installers, SDK, source tarball), PyPI, Bioconda, ghcr, Homebrew and the website. |

## Install

**claude.ai / Claude desktop app:** zip the skill folder (`skills/openms-release/` → `openms-release.zip`, with the folder at the top of the archive) and upload it under Skills in your settings.

**Claude Code:** copy the folder to `~/.claude/skills/openms-release/` (personal) or `.claude/skills/openms-release/` in a project.

The scripts need only Python ≥ 3.10 (standard library), `git` and an authenticated `gh`. Run `python3 skills/openms-release/scripts/selftest.py` after changing them.

## Keeping this repo in sync

The working copy of each skill is the version uploaded to claude.ai. After a skill is changed there, copy the updated folder back into `skills/<name>/` here and commit, so this repository stays the versioned record. Changes made here go the other way by re-uploading the zipped folder.
