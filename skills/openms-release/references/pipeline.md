# The OpenMS release pipeline as it is wired

Verified against OpenMS/OpenMS `develop` @ 91ba9e7 (2026-10-11), OpenMS/homebrew-openms `main`
(2026-10-11) and OpenMS/bioconda-recipes `nightly`. `scripts/preflight.py` re-checks the
load-bearing facts; when it warns, re-read the named workflow before relying on this file.

## Contents
1. Branches and tags
2. Workflows (trigger → effect)
3. What one `vX.Y.Z` tag push sets off
4. Nightly = release rehearsal
5. Known gaps and traps

## 1. Branches and tags

| Ref | Role |
|---|---|
| `develop` | integration branch; `CMakeLists.txt` carries the *next* version (e.g. 3.7.0 after 3.6.0) |
| `nightly` | fast-forwarded to `develop` daily at 01:07 UTC by `update_nightly.yml` |
| `vX.Y.Z` | release tags since 3.6.0 (before: `release/X.Y.Z` tags and `Release*`) |
| `releases/vX.Y.0` | patch-release branch per line (expected by `weekly_patch_workflow.yml`); **none exists yet** — 3.6.0 was tagged directly on develop (commit 5d5cbff) |
| `release/X.Y.Z` | old-style release branches up to 3.5.0, no longer used |

Repository variables: `CURRENT_RELEASE_BRANCH` (target of `cherry-pick-to-release.yml`),
`PATCH_LABEL` (default `patch`), `OPENMS_GITHUB_APP_ID`.

## 2. Workflows

| File | Trigger | Effect |
|---|---|---|
| `release.yml` | push `v[0-9]*` tag, dispatch | 4 runners (windows-2025, macos-15, ubuntu-24.04 x64/arm). Builds, packages (NSIS exe, signed+notarized pkg, deb ×2), SDK (`tools/ci/package_sdk.sh`, tested against `src/tests/external`), docs zip, source tarball (`git archive`). Installers and SDK go to archive `/OpenMSInstaller/<type>/<version>`, docs to `/Documentation/<type>/<version>`, `latest` moved (the source tarball is only a run artifact and release asset). For a plain `vX.Y.Z`: GitHub release `Release X.Y.Z` with **make_latest: true**; body = `release-announcement.txt` template filled with the CHANGELOG section (above 124k characters whole sections are dropped, "Known issues" moved up, CHANGELOG linked); then a PR on OpenMS-website (`releaseannouncementX.Y.Z`). |
| `test.yml` | push to `nightly` or `release/*`, PR to develop, dispatch | header-set check + 5 build/ctest legs (incl. clang) |
| `pyopenms-wheels-cibuildwheel.yml` | push `v[0-9]*` tag or `nightly`, PR to develop, dispatch (input `upload-to-pypi`) | One cp311-abi3 wheel per platform (manylinux x86_64/aarch64, macOS arm64, win_amd64), tested on all Pythons in `python_versions.json`, Thermo RAW smoke test. Nightly → pypi.openms.de; tag or dispatch → archive `/pyopenms/release/<version>`; **PyPI only on dispatch at a `v*` ref with `upload-to-pypi=true`**, trusted publishing via environment `pypi` (may require reviewer approval). Version: from CMakeLists; `.devYYYYMMDD` on develop/nightly. |
| `bioconda_deploy.yaml` | push `nightly`, dispatch | builds `openms-meta` + `pyopenms` from OpenMS/bioconda-recipes `nightly` merged with bioconda master, uploads to anaconda channel `openms` (nightly only). The dev recipes build `git_rev: develop` **at build time**, so this leg tests develop's tip of that moment, normally but not necessarily the nightly SHA. |
| `containerdeploy.yml` | push `nightly` or `v*`/`Release*` tag, dispatch (`tag`, `run_tests`) | ghcr.io/openms/openms-{library,executables,tools,tools-thirdparty}:<tag>, multi-arch; tag `vX.Y.Z` → image tag `X.Y.Z`; nightly → `latest`; Singularity .sif to ghcr |
| `update_nightly.yml` | cron 01:07 UTC, dispatch (`force`) | ff `nightly` to develop, then `gh workflow run` release.yml@nightly, test.yml@**develop**, wheels@nightly, Bioconda@nightly, containers@nightly. Its push uses GITHUB_TOKEN, so push triggers do not fire; everything is dispatched. Fails if nightly has commits develop lacks; the `force` input probably cannot rescue that (`if: inputs.force != 'true'` compares a boolean with a string and stays true, so the failing check still runs). |
| `update_version_numbers.yml` | push `v[0-9]*` tag | checks out develop, runs `tools/update_version_numbers.sh X (Y+1) 0`, opens PR `update_package_number_X.(Y+1).0` → develop. **Always** opens one: the script inserts a CHANGELOG header even when the version is unchanged, so after a patch tag the PR only adds an empty duplicate header (close it unmerged; merged, it would empty the next release's notes). Branch and PR are created with GITHUB_TOKEN, so no CI runs on the PR. Errors on tags like `v3.7.0-rc1` (regex). |
| `weekly_patch_workflow.yml` | cron Tue 03:00 UTC, dispatch | newest `releases/vN.M.0` branch; if commits since the newest `vN.M.*` tag: bump patch with the script, commit, push, tag `vN.M.(P+1)` (GitHub App token, so the tag triggers the release workflows). **No tests before the tag.** |
| `cherry-pick-to-release.yml` | PR to develop merged/labelled with `patch`, dispatch (`pr_number`) | korthout/backport-action onto `vars.CURRENT_RELEASE_BRANCH`, PR labelled `backport`; conflicts → draft PR |

Homebrew tap (OpenMS/homebrew-openms): `nightly.yml` (cron 04:00 UTC, `repository_dispatch`
`openms-nightly`, dispatch with `sha`, `force`) pins `libopenms`, `openms`, `openms-gui` to a
commit with version `X.Y.Z-pre.YYYYMMDD`, builds bottles (macOS arm64, x86_64 Linux), uploads
to ghcr and pushes to `main`. `update_nightly.yml` does **not** send the dispatch (the tap README
proposes the step), so the tap follows at 04:00 UTC. No release path exists in the tap.

## 3. One `vX.Y.Z` tag push starts

1. `release.yml` — installers, SDK, docs, archive upload, GitHub release, website PR
2. `pyopenms-wheels-cibuildwheel.yml` — wheels + tests + archive upload (no PyPI)
3. `containerdeploy.yml` — images `X.Y.Z` (published even if `release.yml` fails)
4. `update_version_numbers.yml` — bump PR on develop (also after patch tags; see above)
5. `cppcheck.yml` (`on: [push]`) — informational

Not started by the tag: PyPI upload, Bioconda, Homebrew, readthedocs activation checks,
`CURRENT_RELEASE_BRANCH`, the release branch.

The tag must be pushed with a user token (gh/ssh), not GITHUB_TOKEN, or nothing runs.

## 4. Nightly = release rehearsal

Every night the exact release machinery runs on the develop tip: the same `release.yml` (with
signing/notarization), the same wheel workflow, Bioconda build with the maintained recipe,
containers, and Homebrew bottles a few hours later. Differences to a tag build: version
strings (`nightly-YYYY.MM.DD`, `.devYYYYMMDD`), upload folders, no GitHub release, no PyPI, no
website PR. A develop commit whose nightly runs are all green is therefore the release
candidate; the skill tags *that* commit instead of building something new.

## 5. Known gaps and traps (as of 2026-10-11)

1. **Empty patch release notes.** `update_version_numbers.sh` always inserts an empty
   `OpenMS X.Y.Z (under development)` header; the weekly patch workflow tags right after,
   so `release.yml` publishes empty notes (reproduced on v3.6.0 → 3.6.1 with
   `scripts/changelog.py extract`). Running the script twice adds a second header (`changelog.py dedupe`).
2. **No CI on release branches.** `test.yml` listens to `release/*`, the branches are
   `releases/vX.Y.0`; PRs only to develop. Backport PRs and the branch are untested unless
   test.yml is dispatched (`gh workflow run test.yml --ref releases/vX.Y.0`).
3. **Weekly patch race.** If the release branch has untagged commits on Tuesday 03:00 UTC
   the workflow tags a patch on its own. Disable it during a patch release
   (`gh workflow disable weekly_patch_workflow.yml`), re-enable afterwards.
4. **make_latest on old lines.** A patch for an older line becomes GitHub "latest" and moves
   the archive `release/latest` link. Fix with `gh release edit vNEWEST --latest` and by
   re-pointing the archive link (no workflow does that; tell the user).
5. **RC tags are half-supported.** `v3.7.0-rc1` builds installers but `deploy-installer`
   cannot create `/OpenMSInstaller/rc1/` (mkpath only for releases), wheels upload into
   `pyopenms/release/3.7.0/`, `update_version_numbers.yml` fails. Use the nightly instead.
6. **pyproject.toml and pyOpenMS docs versions are not bumped** by the script
   (develop: pyproject 3.6.0, docs conf.py 3.6.0, switcher nightly "3.6.0dev"). CI rewrites
   pyproject for wheels; docs and sdists use the stale value. The prep PR fixes them.
7. **Bioconda upstream lags.** bioconda/bioconda-recipes still has openms-meta/pyopenms
   **3.5.0** (url scheme `release%2F`); 3.6.0 never landed there. The maintained recipe lives
   on OpenMS/bioconda-recipes `nightly`. Its 3.6.0-era patch for File.cpp no longer applies
   to develop (the fix is upstream, #10353); the bind_format patch still applies.
8. **Containers publish before the gate.** A failing tag build still leaves `X.Y.Z` images;
   re-tagging overwrites them.
9. **Bot PRs have no CI.** PRs opened with GITHUB_TOKEN (the develop version bump) start no
   `pull_request` workflows. Close and reopen them with a user token to get test.yml.
10. **The 3.6 line has no SDK.** A tag build runs the workflows of the tagged tree;
   `releases/v3.6.0` (cut from v3.6.0) has no SDK packaging, so 3.6.x patch releases ship
   without SDK archives. `verify_release.py` only expects them when the tree has
   `tools/ci/package_sdk.sh`.
11. **Wiki page "Preparation of a new OpenMS release" is outdated** (last edited 2024-07;
   mentions openms_ci_matrix_full.yml, Release tags, KNIME). Do not follow it.
