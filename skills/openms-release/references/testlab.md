# The testlab gate

The testlab is OpenMS' integration testing beyond CI (real data, real workflows). How it is
started and where its verdict lives is configured in `testlab.json` at the skill root, so
`scripts/testlab_gate.py` can run it unattended.

## The configured testlab: openms-test-lab

`testlab.json` points at **timosachsenberg/openms-test-lab**, workflow `nightly-readiness.yml`,
mode `lookup-or-dispatch`:

- *Nightly readiness* tests the files the nightly published for one OpenMS commit. It pins the
  four installers (archive folder of that night) and four wheels (pypi.openms.de, same night)
  by URL. Then it runs Release readiness, the release matrix of the package labs (Windows,
  macOS, Linux x64/arm64, 22.04, Python 3.12 and 3.14) and the macOS upgrade check, and ends
  with a *Verdict* job. The run concludes `success` only if every automated blocking check of
  the lab's RELEASE-READINESS.md passed, including A2 (every lab installed that commit).
- Run name `Nightly readiness · <sha> · <stage>`; `match_title: "{sha}"` finds it. A daily
  schedule (05:30 UTC) starts one per nightly, so the gate usually finds a finished run. Else
  it dispatches one with `stage=release` (A3, E8 block too) and waits; a run takes about 3 h.
- The run refuses a commit that is not a nightly, whose nightly builds failed or are still
  running, or whose files a later nightly on the same UTC day replaced. So run the gate after
  the CI gate (Phase 3), and if develop moved twice in a day, gate the later nightly.
- A reused schedule run has `stage=nightly`, where A3 and E8 are advisory. Phase 3 step 5
  (`check_versions.py`, `changelog.py check`) covers both for the release.
- Not decided by the run: judgement checks (D5, E4), the static checks run by hand (F7 signing,
  F8 licenses, ...), tag-build checks (G) and human checks (H1–H4). The run summary and the
  `nightly-readiness-verdict-<run>` artifact (`gate.md`) list them. Name them to the user in
  the Phase 4 checkpoint; in autopilot, say in the report that they were not checked.
- A failed run: read `gate.md` (blocking failures first) and the failing lab job. Infrastructure
  failures may be re-run once (`gh run rerun <id> -R timosachsenberg/openms-test-lab --failed`).
- Patch releases: the release branch has no nightly; see references/patch-release.md step 4.

## When the gate is not configured

Ask the user once, in one message:
1. How is a testlab run started for a given OpenMS commit or nightly (GitHub workflow in
   which repository, a command on a machine, or does it run on every nightly by itself)?
2. Where is the verdict read (workflow conclusion, a status URL, a report)?
3. How long does a run take?

Then fill `testlab.json` and, if the skill directory is writable, save it there so the next
release does not ask again. Until then the testlab gate is passed only by the user's explicit
"testlab is green for <sha>".

## Configuration examples

GitHub workflow that is dispatched per candidate:

```json
{ "configured": true, "kind": "github-workflow", "repo": "OpenMS/<testlab-repo>",
  "workflow": "release-candidate.yml", "ref": "main", "mode": "dispatch",
  "inputs": {"openms_sha": "{sha}", "openms_version": "{version}"},
  "timeout_minutes": 360, "poll_seconds": 300 }
```

Workflow that already runs on every nightly (look up the newest run whose title has the SHA):

```json
{ "configured": true, "kind": "github-workflow", "repo": "OpenMS/<testlab-repo>",
  "workflow": "nightly.yml", "mode": "lookup", "match_title": "{sha}",
  "timeout_minutes": 120 }
```

A command on a machine the user's session can reach (exit code 0 = pass):

```json
{ "configured": true, "kind": "command",
  "command": "ssh testlab ./run_release_tests.sh {sha} {version}",
  "timeout_minutes": 480, "report_url": "https://testlab.example/report/{sha}" }
```

Placeholders: `{sha}`, `{version}`, `{tag}`, `{nightly_date}` (YYYY.MM.DD as in nightly
artifact names). Values substituted into `command` are shell-quoted.
