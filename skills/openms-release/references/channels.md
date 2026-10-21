# Distribution channels: publish, verify, recover

`scripts/verify_release.py --version X.Y.Z` checks all of them at once. Order matters:
everything in "automatic on tag" is re-doable by moving the tag; PyPI is not.

## Contents
- Automatic on tag: installers, deb, SDK, source tarball, docs, containers, archive
- PyPI
- Bioconda
- Homebrew
- Website, readthedocs, announcement
- Recovering from a failed tag build

## Automatic on tag (release.yml, containerdeploy.yml, wheel workflow)

Expected GitHub release assets (3.6.0 had the first five; the SDK ships from 3.7.0 on, #10248):

| Asset | Built on |
|---|---|
| `OpenMS-X.Y.Z-Debian-Linux-x86_64.deb` | ubuntu-24.04 |
| `OpenMS-X.Y.Z-Debian-Linux-aarch64.deb` | ubuntu-24.04-arm |
| `OpenMS-X.Y.Z-macOS-Silicon.pkg` (signed, notarized) | macos-15 |
| `OpenMS-X.Y.Z-Win64.exe` (NSIS) | windows-2025 |
| `OpenMS-X.Y.Z.tar.gz` (git archive; Bioconda's source) | ubuntu-24.04 |
| `OpenMS-SDK-X.Y.Z-{Linux-x86_64,Linux-aarch64,macOS-arm64}.tar.gz`, `...-Windows-x64.zip` | all four |

Installers and SDK archives (not the source tarball) also go to
`https://archive.openms.de/openms/OpenMSInstaller/release/X.Y.Z/` (`latest` link moved), docs to
`.../Documentation/release/X.Y.Z/`, wheels to `.../pyopenms/release/X.Y.Z/`. Patch releases
of the 3.6 line have no SDK (their tree has no `tools/ci/package_sdk.sh`). Images: `ghcr.io/openms/openms-{library,executables,tools,tools-thirdparty}:X.Y.Z`.

Check: `ci_status.py tag --tag vX.Y.Z --sha <tagged commit> --wait 720`, then
`verify_release.py --only github,archive,containers,docs`.

## PyPI

Only a dispatch publishes:

```bash
gh workflow run pyopenms-wheels-cibuildwheel.yml -R OpenMS/OpenMS --ref vX.Y.Z -f upload-to-pypi=true
```

It rebuilds and retests the wheels from the tag (several hours; it does not reuse the
tag-push run's wheels, and it re-uploads them to the archive), then `publish-release-pypi` runs in
environment `pypi` with trusted publishing. If that environment has required reviewers the
job waits: show the user the run URL and let them approve (GitHub deliberately asks a human
here; do not approve it on their behalf unless they told you to for this release).
PyPI versions are immutable — a broken upload can only be yanked and superseded by
`X.Y.Z.post1`-style or a new patch release. Start the dispatch only after the GitHub release
is complete and `verify_release.py --only github` is ok.

Verify: `verify_release.py --only pypi` (4 wheels: manylinux x86_64/aarch64, macOS arm64,
win_amd64, all cp311-abi3; 3.6.0 had exactly these), then in a clean venv
`pip install pyopenms==X.Y.Z && python -c "import pyopenms; print(pyopenms.__version__)"`.

## Bioconda

Upstream (bioconda/bioconda-recipes) is reviewed by Bioconda maintainers; merging is not ours.
Steps:

1. Look for an existing PR first (Bioconda's autobump bot opens one for GitHub releases):
   `gh pr list -R bioconda/bioconda-recipes --search "openms in:title" --state open`.
   If one exists, update it instead of opening a second.
2. Clone bioconda/bioconda-recipes (sparse: `recipes/openms-meta recipes/pyopenms`) and the
   OpenMS fork's `nightly` branch. Branch `openms-X.Y.Z` off upstream master.
3. Download the release tarball and run
   `bioconda_bump.py --recipes-dir <upstream>/recipes --version X.Y.Z --tarball OpenMS-X.Y.Z.tar.gz --from-nightly <fork-nightly>/recipes`.
   It copies the maintained recipes over the upstream ones (upstream-only files such as
   `build_failure.*.yaml` are kept and listed for review), sets version/url/sha256/build number
   and dry-runs every patch: `DROP` → already in the tarball, remove it from meta.yaml and
   delete the file; `FIX` → it applies neither way: first check whether OpenMS fixed the problem
   differently (`git log`/blame of the patched file, CHANGELOG) and then drop it, otherwise
   rebase it; `OK` → still needed, keep it. Example at 3.7.0: the File.cpp path patch is
   `FIX` because #10353 solved it differently (drop), the bind_format patch is `OK`.
4. Optional local check if Docker is available: `bioconda-utils build --docker --packages openms-meta`.
5. Push the branch to OpenMS/bioconda-recipes, open the PR against bioconda master
   ("Update OpenMS to X.Y.Z"). When CI is green comment `@BiocondaBot please add label`.
6. In Phase 7, carry the release block (sha256, patch decisions) back to the fork's `nightly`
   branch together with its version bump `X.Y.0dev` → `X.(Y+1).0dev`, so the next release
   starts from a correct recipe.

Verify later: `verify_release.py --only bioconda` (pending until merged and built).

## Homebrew

The tap only knows nightlies (`X.Y.Z-pre.YYYYMMDD`, pinned by `bump-nightly.py`). There is
no release formula and no decision yet how releases should appear. Until the user decides,
the skill does this and reports the gap:

- Make sure the tap's last nightly built the release commit (`ci_status.py candidate` checks
  it; dispatch `gh workflow run nightly.yml -R OpenMS/homebrew-openms -f sha=<sha> -f force=true`).
  Then the bottles for exactly the released code exist, labelled as a pre-release version.

Options to offer the user (pick once, then extend the skill):
1. Versioned release formulae in the tap (`libopenms@X.Y`, `openms@X.Y`, `openms-gui@X.Y`,
   url = GitHub release tarball, `keg_only :versioned_formula`), built through the tap's
   PR flow (`tests.yml` → `publish.yml` / `brew pr-pull`).
2. Submission to homebrew-core (the tap README says the formulae follow core rules; swap url
   to the release tarball, drop `livecheck skip` and the ccache hook).
3. A `--release vX.Y.Z` mode in `bump-nightly.py` that pins the three formulae to the tag
   with version `X.Y.Z` and pauses the nightly cron until the next develop version.

## Website, readthedocs, announcement

- `release.yml` opens `releaseannouncementX.Y.Z` on OpenMS/OpenMS-website with
  `content/en/news/releaseX.Y.Z.md` = the full announcement. Read it (version, download link,
  CHANGELOG body present), then merge (`gh pr merge -R OpenMS/OpenMS-website <n> --squash`)
  in autopilot mode, or report it for review.
- pyOpenMS docs: `https://pyopenms.readthedocs.io/en/vX.Y.Z/` must answer 200 (readthedocs
  builds the tag if the version is activated). If 404, tell the user to activate `vX.Y.Z` on
  readthedocs — no token for that here.
- Mailing lists, social media, Wikipedia: draft the text from the `release-announcement.txt`
  artifact of the release run (`gh run download <id> -n release-announcement.txt`); do not send.

## Recovering from a failed tag build

As long as no GitHub release exists and nothing is on PyPI:

1. Find the failing leg (`gh run view <id> --log-failed`), fix on develop (or the release
   branch), get the fix through the same gates.
2. `git push --delete origin vX.Y.Z` and delete the local tag; re-tag the fixed commit and
   push; watch with `ci_status.py tag --sha <new commit>` so the old runs are ignored. Images
   and archive folders of the first attempt are overwritten; the bump PR is force-updated.

Once the GitHub release is published, do not move the tag; ship X.Y.(Z+1) instead.
