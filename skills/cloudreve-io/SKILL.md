---
name: cloudreve-io
description: Use to manage the Cloudreve file source feeding Knowledge OS — check authorization, configure OAuth credentials, list/browse files, get file metadata, download a file to a local temp path, trigger a full drive scan, and poll scan progress. Trigger when the user uploads files, asks why a file is missing, wants to browse the drive, needs a local copy of a file for analysis, or wants to configure/check the Cloudreve connection. This skill never writes to the knowledge graph (use knowledge-os for extract → review → commit).
---

# Cloudreve IO

Manage the **Cloudreve file-source** (optional). This skill is
the "librarian" for the cloud drive: it authenticates to the drive, lets you browse and fetch files,
and hands `cloudreve://` URIs off to `knowledge-os` (for graph extraction).
If Cloudreve is not configured, Knowledge OS remains fully functional via local file analysis.

## Prerequisite

The Knowledge OS backend must be running:

```bash
./start.sh            # from the knowledge_nexus repo root
```

`cloudreve` talks to `http://localhost:8000` by default.
Override with `KN_API_URL`. Run from this skill directory or call by full path:

```bash
python3 cloudreve status      # quick auth check
```

## Core workflow

### First time — configure OAuth

```bash
# Set the secret in the environment, then run configure
export CLOUDREVE_CLIENT_SECRET=<your-client-secret>
python3 cloudreve configure \
    --base-url  http://<your-cloudreve-host>:5212 \
    --client-id <your-client-id>
```

If the env var is absent and the terminal is interactive, `configure` will
prompt for the secret with `getpass` (hidden input). Pass `--no-interactive`
to fail fast in scripts instead. After saving config, complete the OAuth
authorization through the Web console (Cloudreve tab → click "Authorize").

### Upload a file to the drive

```bash
# Upload a local report to a Cloudreve folder
python3 cloudreve upload /tmp/campus-report.md --dest cloudreve://my/reports/

# Returns JSON with status, dest_uri, and size
```

Requires the OAuth token to include the `Files.Write` scope.

### Browse the drive

```bash
python3 cloudreve ls                         # root of the drive
python3 cloudreve ls cloudreve://my/campus   # a specific folder
python3 cloudreve info cloudreve://my/campus/access_log.csv
```

### Download a file for local analysis

```bash
# Prints the path of the downloaded temp file — pass it to analyzing-data
python3 cloudreve download cloudreve://my/campus/sensors.csv
# /tmp/cloudreve_abc123.csv

# Or specify a destination explicitly
python3 cloudreve download cloudreve://my/campus/sensors.csv --out /tmp/sensors.csv
```

### Discover new files (full scan)

```bash
python3 cloudreve scan           # trigger background scan
python3 cloudreve scan-status    # poll until is_scanning = false
```

Once scan completes, the files' `cloudreve://` URIs can be used by `knowledge-os`.

## Command reference

| Command | Purpose |
|---|---|
| `status` | OAuth authorization status |
| `config` | show current OAuth config (base url, redirect uri, scope) |
| `configure [--base-url] [--client-id] [--redirect-uri] [--scope]` | save OAuth config (secret via env `CLOUDREVE_CLIENT_SECRET` or prompt) |
| `ls [URI]` | list files/dirs at URI (default: `cloudreve://my`) |
| `info <URI>` | metadata for a single file or directory |
| `download <URI> [--out PATH]` | download file; prints local path |
| `upload <PATH> --dest <URI>` | upload local file to a Cloudreve folder (requires Files.Write scope) |
| `scan` | trigger a full recursive scan (background task) |
| `scan-status` | last scan result / progress + `is_scanning` flag |

## Safety rules

- **Never pass the client secret as a command-line argument.** Use the
  `CLOUDREVE_CLIENT_SECRET` environment variable or the interactive prompt.
  This prevents the secret from appearing in `ps aux` or shell history.
- `download` writes to a temp file by default; the path is printed to stdout
  so downstream scripts can capture it with `$(python3 cloudreve download ...)`.
- This skill does not write to the graph. Any local file it downloads is a
  read-only working copy; the canonical source remains Cloudreve.
