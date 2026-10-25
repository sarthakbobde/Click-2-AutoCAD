# Click2CAD - Blender V3 - Claude

Turns furniture photos into 3D models, with **Claude** as the model:

1. Claude looks at the photo(s) and writes a Blender Python (`bpy`) script using the **parts kit**: ready-made helpers (`box`, `rod`, `tube`, `sheet`, `bevel`) that place every part from shared measurements, so attached parts meet and nothing floats.
2. The script runs in Blender (the `bpy` module, no Blender install needed) and builds the geometry.
3. The model is exported as OBJ and shown in a 3D viewer in the browser.
4. If the result isn't right, **Refine** it: describe what's wrong and Claude rewrites the script.

Same UI as V2 (Submissions, Viewer, Refine), on port **8001** so both versions can run side by side.

## Two ways Claude can run (`C2C_CLAUDE_MODE` in `.env`)

- **`live` (default)**: Claude, running in a **Claude Code session** next to the app, writes each script. No API key is needed. Each job writes `request.md` into its folder and waits (status *Asking Claude*) until Claude writes `answer.py`; then it builds as usual. The Claude Code session must be open and watching the whole time.
- **`api`**: the Anthropic API writes each script. Set `ANTHROPIC_API_KEY` (from the Claude Console, platform.claude.com, billed there) and optionally `CLAUDE_MODEL` (default `claude-opus-5`) and `CLAUDE_EFFORT`. No session is needed.

## Demo runbook (live mode)

1. Double-click **`start.bat`**. The UI opens at http://127.0.0.1:8001. Sophos may show a warning page for local sites; click **Continue**.
2. In the Claude Code session, ask Claude to **start watching Click2CAD V3**. Claude runs `tools\watch_requests.py` in the background and is alerted as soon as a job is waiting.
3. Upload photos with **+ Add**. Each job shows *Running · Asking Claude* while Claude works, usually 2 to 4 minutes, then the model appears in Submissions and the Viewer. One or two photos at a time works best.
4. Use **Refine** on any result the same way; refinements are answered live too.
5. After the demo, ask Claude to stop watching and close the server window.

If the session isn't watching, jobs wait and fail after `C2C_JOB_TIMEOUT_SECONDS` (default 30 minutes); use **Retry** once Claude is watching again.

## Setup

```powershell
winget install -e --id Python.Python.3.11
py -3.11 -m venv .venv311
.\.venv311\Scripts\pip.exe install -r requirements.txt
```

`.env` (see `.env.example`):

| Variable | Meaning |
| --- | --- |
| `C2C_CLAUDE_MODE` | `live` (default) or `api` |
| `ANTHROPIC_API_KEY` | api mode only |
| `CLAUDE_MODEL` | api mode only, default `claude-opus-5` |
| `CLAUDE_EFFORT` | api mode only: `low` to `max`, default `high` |
| `C2C_MAX_PARALLEL_JOBS` | jobs running at the same time (default 2) |
| `C2C_JOB_TIMEOUT_SECONDS` | a job running longer is stopped and marked failed (default 1800) |

`.env` is re-read for every job, so changes apply without restarting the server.

## Folder layout

```
click2cad/          Python package
  llm.py              instructions for Claude (parts-kit rules): generate and refine
  kit.py              the parts kit the scripts build with
  claude_session.py   live mode: hand the request to the Claude Code session and wait for answer.py
  claude.py           api mode: Anthropic API call
  pipeline.py         runs one job: Claude -> bpy script -> Blender -> OBJ
  jobs.py, runner.py, server.py, config.py   job records, queue, web API, settings
tools/
  watch_requests.py   live mode: exits as soon as a job is waiting for Claude
  check_script.py     test-build a script, check for floating parts, render review views
web/                browser UI
data/               created at runtime: click2cad.db and jobs/<id>/ (inputs, request.md, answer.py, script.py, model.obj, log.txt)
serve.py, start.bat, generate.py
```

## Notes

- Each job runs in a separate Python process, so every job starts from a clean Blender scene and a failing script can't take the server down. Generated code runs without a sandbox, so keep the server on `127.0.0.1` (the default).
