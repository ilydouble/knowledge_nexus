---
name: cloudreve-io
description: Use to manage the Cloudreve file source feeding Knowledge OS — check whether the drive is authorized, trigger a full file scan so new documents are discovered, and poll scan progress. Trigger when the user uploads files to the drive, asks why a file is not showing up, wants to (re)sync the drive, or needs to confirm Cloudreve is connected before extraction. This skill only gets files discovered; it never reads file content or touches the knowledge graph (use knowledge-os for that).
---

# Cloudreve IO

Manage the **file-source** side of the Knowledge OS pipeline. This skill is the
"librarian": it makes sure the drive is connected and its files are discovered,
then hands off to other skills (`analyzing-data` to analyse, `knowledge-os` to
extract into the graph).

## Prerequisite

The Knowledge OS backend must be running and reachable:

```bash
./start.sh            # from the knowledge_nexus repo root
```

`cloudreve` talks to `http://localhost:8000` by default. Point it elsewhere
with the `KN_API_URL` environment variable. Run it from this skill directory
(the script sits next to this file), or call it by full path:

```bash
python3 cloudreve status      # is the drive authorized?
```

If a command errors with "Cannot reach …", the backend is not running — tell
the user to run `./start.sh` first.

## Core workflow

1. **Check authorization** before anything else:
   `python3 cloudreve status`
   - `{"authorized": true}` → the drive is connected, proceed.
   - `{"authorized": false}` → OAuth is not set up. Authorization is a
     browser flow done in the Web console (**Cloudreve tab** → fill Base URL +
     Client ID/Secret → save → click authorize). Inspect the current config
     with `python3 cloudreve config`. Do **not** attempt to paste secrets on
     the command line.

2. **Trigger a scan** so newly uploaded files get discovered:
   `python3 cloudreve scan`
   Returns immediately; the scan runs in the background.

3. **Poll progress** until it finishes:
   `python3 cloudreve scan-status`
   Reports the last scan result and whether a scan is currently running.

Once a scan completes, the files are known to the system and their
`cloudreve://…` URIs can be handed to `knowledge-os` for extraction.

## Command reference

| Command | Purpose |
|---|---|
| `status` | Cloudreve OAuth authorization status |
| `config` | show OAuth config (base url, redirect uri, scope) |
| `scan` | trigger a full recursive scan (background task) |
| `scan-status` | last scan result / progress + `is_scanning` flag |

## Boundaries

- This skill **discovers** files; it does not read their content, analyse data,
  or write to the graph. For analysis use `analyzing-data`; for
  extract → review → commit → query use `knowledge-os`.
- Browsing/searching individual files is **not yet exposed** over the API
  (only a full scan is). If the user needs file-level listing/search, that
  requires a new backend endpoint — surface this as a gap rather than guessing.

## Safety rules

- Never put OAuth client secrets or tokens into command arguments. Configure
  them only through the Web console's Cloudreve tab, which writes them to the
  server-side token store.
