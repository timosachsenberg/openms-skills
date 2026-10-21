# The testlab gate

The testlab is OpenMS' integration testing beyond CI (real data, real workflows). How it is
started and where its verdict lives is configured in `testlab.json` at the skill root, so
`scripts/testlab_gate.py` can run it unattended. As shipped, the file says
`"configured": false` and the gate answers `needs-human` (exit 3).

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
