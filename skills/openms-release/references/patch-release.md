# Patch releases (X.Y.Z → X.Y.Z+1)

A patch release is cut from `releases/vX.Y.0`, not from develop, so the nightly does not
test it. The gates are therefore: `test.yml` and the wheel workflow dispatched on the branch,
the testlab labs on the branch's wheels, and the version/CHANGELOG checks.

## 1. Freeze the weekly job, then the release branch

- First, before any backport lands: the weekly patch workflow (Tuesday 03:00 UTC) tags the
  newest release branch by itself, untested and with empty notes, as soon as it has untagged
  commits. `gh workflow disable weekly_patch_workflow.yml -R OpenMS/OpenMS` (write access);
  re-enable in step 6. Log that you did it.
- Exists? `git ls-remote --heads origin releases/vX.Y.0`.
- If not (true for 3.6 today): create it from the tag, not from develop:
  `git push origin vX.Y.0^{commit}:refs/heads/releases/vX.Y.0`.
- If X.Y is the newest line, set `CURRENT_RELEASE_BRANCH` so future `patch`-labelled PRs are
  backported automatically: `gh variable set CURRENT_RELEASE_BRANCH -R OpenMS/OpenMS --body releases/vX.Y.0`
  (needs admin; otherwise tell the user).

## 2. Collect the fixes

- Backport PRs already open: `gh pr list -R OpenMS/OpenMS --base releases/vX.Y.0 --label backport --json number,title,isDraft,url`.
- Fixes merged into develop with the patch label but not backported (e.g. merged before the
  branch existed): `gh pr list -R OpenMS/OpenMS --base develop --label patch --state merged --search "merged:>=<date of vX.Y.0>"`;
  backport each with `gh workflow run cherry-pick-to-release.yml -R OpenMS/OpenMS -f pr_number=<n>`.
- Draft backport PRs have conflicts. Resolve them only if the conflict is mechanical
  (CHANGELOG context, renamed include); otherwise list them for the user and leave them out.
- Nothing to release (no commits since the last tag after merging)? Stop and say so.

Merge the non-draft backport PRs (they had a human `patch` decision on develop). They have
no CI of their own — the branch gate in step 4 covers them together.

## 3. Prepare the branch

On a work branch off `releases/vX.Y.0`, via PR into the release branch:

```bash
bash tools/update_version_numbers.sh X Y Z+1
python3 <skill>/scripts/changelog.py dedupe --version X.Y.Z+1      # if the header existed
# write the section: one line per backported fix, in the CHANGELOG style of the
# develop entries those PRs added (copy them; cite the PR numbers)
python3 <skill>/scripts/changelog.py finalize --version X.Y.Z+1
sed -i 's/^version = ".*"/version = "X.Y.Z+1"/' src/pyOpenMS/pyproject.toml
python3 <skill>/scripts/check_versions.py --repo-dir . --expect X.Y.Z+1
python3 <skill>/scripts/changelog.py extract --version X.Y.Z+1        # preview of the GitHub notes
```

Then merge the PR (`gh pr merge --squash`; branch protection may require a review — then wait).

## 4. Gate the branch head

```bash
SHA=$(git ls-remote origin refs/heads/releases/vX.Y.0 | cut -f1)
gh workflow run test.yml -R OpenMS/OpenMS --ref releases/vX.Y.0
gh workflow run pyopenms-wheels-cibuildwheel.yml -R OpenMS/OpenMS --ref releases/vX.Y.0   # upload-to-pypi stays false
python3 <skill>/scripts/ci_status.py branch --ref releases/vX.Y.0 --sha $SHA --wait 360
```

Testlab: do not run `testlab_gate.py` here. Its *Nightly readiness* workflow tests nightlies
only and refuses a branch commit ("not a nightly"). Once the wheel run above is green, dispatch
the package labs of `timosachsenberg/openms-test-lab` on its wheels, then ask the user for
the verdict on `SHA`:

```bash
for r in ubuntu-24.04 ubuntu-24.04-arm; do
  gh workflow run linux-lab.yml -R timosachsenberg/openms-test-lab -f runner=$r -f python_version=3.12 \
    -f wheel_run_id=<wheel run id> -f openms_package=none -f debug=false
done
gh workflow run macos-lab.yml -R timosachsenberg/openms-test-lab -f runner=macos-15 -f python_version=3.12 \
  -f wheel_run_id=<wheel run id> -f openms_package=none -f debug=false
```

The Windows lab takes no run ID; the Windows wheel is covered by the wheel workflow's own tests.

The wheel dispatch uploads to the archive's `experimental/releases_vX.Y.0` folder; harmless.
Installers are not rehearsed for a patch (no nightly on the branch); packaging is rarely
touched by backports. If a backport touches `cmake/`, `.github/`, `tools/ci/` or packaging,
tell the user that the first installer build will be the tag build and the recovery path in
channels.md applies.

## 5. Tag and publish

As for any release (SKILL.md phases 4–6), with two differences:
- The GitHub release becomes "latest". If X.Y is not the newest line, run
  `gh release edit v<newest> -R OpenMS/OpenMS --latest` afterwards and tell the user that the
  archive's `OpenMSInstaller/release/latest` link now points to X.Y.Z+1 and needs re-pointing.
- `update_version_numbers.yml` still opens (or force-updates) `update_package_number_X.(Y+1).0`
  on develop; its only change is an empty duplicate CHANGELOG header. Close it unmerged
  (`verify_release.py --only develop` flags it).
- Watch the tag with `ci_status.py tag --tag vX.Y.Z+1 --sha <branch head>`. Releases of the
  3.6 line ship no SDK archives (the tree predates the SDK packaging).

## 6. After the release

- Re-enable the weekly workflow: `gh workflow enable weekly_patch_workflow.yml -R OpenMS/OpenMS`.
- Do not merge the release branch back into develop (fixes came from develop); but if a fix was
  written on the branch directly, open a forward-port PR to develop.
- Bioconda: upstream is still at 3.5.0 (2026-10-11). Ask the user whether a patch of the
  current line should go there; if yes, same procedure as in channels.md.
