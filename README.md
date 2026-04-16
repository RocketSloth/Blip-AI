# Blip Local Agent Platform

Blip is now a local-first agent platform for autonomous repo engineering.

It combines:

- fresh-context repo planning and execution loops
- a daemon-style local control plane with isolated workspaces and runs
- approval-gated branch/worktree application
- a skill registry and recipe library

The previous lane-based MVP factory is still here, but now as a built-in specialist recipe on top of the broader platform.

Blip still supports three flagship B2B lanes:

- internal ops copilots
- intake and approval workflows
- reporting dashboards

Every generated MVP workspace still moves through the same specialist flow:

1. qualify the idea into a supported lane
2. freeze a `PRODUCT_BRIEF.json`
3. scaffold a canonical repo on one golden stack
4. run deterministic validation gates
5. let REF score qualitative quality only after the hard gates pass

README-only edits still do not count as progress. A run only matters when it improves the actual repo or workflow and survives validation.

## Local Platform Model

Blip now keeps its runtime state in a local control-plane database under `BLIP_HOME`:

- `BLIP_HOME/blip.db` for workspaces, runs, approvals, skills, recipes, and migrated legacy state
- `BLIP_HOME/workspaces` for imported/generated repos
- `BLIP_HOME/artifacts` for run worktrees, logs, and approval artifacts
- `BLIP_HOME/skills` for installed skill manifests

Generated and imported project workspaces live outside the app repo by default so `uvicorn --reload` does not watch nested repos and generated files.

Default `BLIP_HOME` roots:

- Windows: `%LOCALAPPDATA%\\Blip-AI`
- macOS: `~/Library/Application Support/Blip-AI`
- Linux: `~/.local/share/blip-ai`

Override the shared platform home with `BLIP_HOME`, or override just workspace storage with `BLIP_PROJECTS_ROOT`.

## Golden Stack

Generated MVPs use one stack only:

- FastAPI
- Jinja
- HTMX
- SQLite
- SQLModel
- pytest

Each scaffold includes:

- `README.md`
- `PROJECT_PLAN.md`
- `PRODUCT_BRIEF.json`
- `VALIDATION.json`
- seeded demo data
- a runnable app entrypoint
- lane-specific UI and workflow tests

## Supported Lanes

### `ops-copilot`
- queue view
- task detail workflow
- follow-up capture
- action recommendations placeholder

### `intake-approval`
- submission review queue
- decision workflow
- reviewer notes
- audit-friendly status tracking

### `reporting-dashboard`
- KPI dashboard
- filters
- CSV export
- follow-up action creation

## Built-in Recipes

- `lane-mvp-factory`
  - qualifies an idea into a supported lane
  - freezes the product brief
  - scaffolds the canonical stack
  - validates the workspace
  - prepares the run for review/approval
- `repo-improver`
  - imports or reuses the saved repo digest
  - builds a mission spec from digest + instructions + current validation
  - runs targeted improvements in an isolated branch/worktree
  - validates and creates an approval request before landing changes

## What Runs Automatically

Manual actions:

- `POST /api/run` researches new lane-fit ideas
- `POST /api/organize` reorganizes the bucket

Automatic actions:

- the heartbeat only iterates active projects with `auto_run=true`
- each cycle uses the staged build pipeline and deterministic validation
- projects stop auto-running once they hit the target score of `95`
- workspace runs are isolated and approval-gated before changes land in the main workspace

GitHub import actions:

- `POST /api/projects/import` clones the repository and immediately generates a persisted `REPO_DIGEST.json`
- imported projects keep manual instructions in `instructions.txt` and the AI execution brief in `REPO_DIGEST.json`
- the YOLO action now starts a real isolated autonomous run using the saved mission inputs and current recipe

## Validation Model

Before REF can score a project, Blip checks:

- scaffold contract present
- app import works
- homepage smoke test passes
- seeded demo data loads
- primary workflow test passes
- README includes install, run, and test commands

Validation output is persisted per project in:

- `VALIDATION.json`
- `records.json`
- `artifacts/`

Imported GitHub repos also persist:

- `REPO_DIGEST.json`
- `instructions.txt`

## Project Layout

```text
.
|-- app/
|   |-- agent.py              # qualification, planning, scaffold, pipeline, REF
|   |-- bucket.py             # idea bucket storage
|   |-- config.py             # runtime settings
|   |-- main.py               # FastAPI app and API routes
|   |-- mvp_templates.py      # golden stack scaffolds for each lane
|   |-- project_store.py      # active project manifest and workspace storage
|   `-- project_validation.py # deterministic hard gates and artifact logs
|-- data/
|   |-- BUCKET.md
|   `-- active_projects.json
|-- static/
|   `-- index.html
|-- tests/
|   `-- test_project_workflow.py
`-- requirements.txt
```

## clawup — OpenClaw Setup Wizard

`clawup` is a guided setup tool that installs and configures OpenClaw without any terminal commands. It detects what's already on your machine, installs only what's missing, and walks through the whole thing in three steps.

### For non-technical users (browser wizard)

Run this once. It installs everything it needs, then opens the wizard in your browser:

```bash
python clawup-bootstrap.py
```

You'll be guided through:

1. **Where do you want to use your AI?** — on your computer, Telegram, or WhatsApp
2. **Which AI service do you have?** — pick OpenAI, Anthropic, OpenRouter, or local (Ollama)
3. **Setting everything up** — installs OpenClaw, saves your key, configures everything, runs a health check

### For terminal users

```bash
python clawup.py serve          # same wizard, opens browser
python clawup.py                # interactive terminal version
python clawup.py --dry-run      # preview what will be installed
python clawup.py --fix          # run openclaw doctor only
python clawup.py --help         # all options
```

---

## Install And Run

Set your API key:

```bash
export OPENAI_API_KEY="your_key_here"
```

Optional workspace override:

```bash
export BLIP_PROJECTS_ROOT="/absolute/path/for/generated-projects"
```

Optional platform home override:

```bash
export BLIP_HOME="/absolute/path/for/blip-home"
```

Install dependencies:

```bash
pip install -r requirements.txt
```

Start the app:

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`.

Start the local CLI:

```bash
python blip.py workspace list
python blip.py run start <workspace_id>
python blip.py run approve <run_id>
python blip.py skill list
python blip.py daemon start
```

## UI Features

- inspect workspaces, recent runs, approvals, skills, and recipes from the main dashboard
- run isolated approval-gated workspace executions instead of directly applying repo changes
- approve or reject pending runs before their branch/worktree changes land
- keep the lane-based MVP factory as a built-in specialist mode
- promote qualified bucket ideas into active projects
- inspect lane, stage, product brief summary, run/test contract, and demo scenario
- run `build`, `validate`, or full pipeline actions on demand
- review hard-gate pass/fail results and next best task
- inspect AI repo summaries, priority tasks, and the saved execution brief for imported repos
- keep manual user instructions separate from the AI-generated YOLO plan
- download the current generated repo at any time
- open validation logs from the `artifacts/` folder
- toggle heartbeat auto-run per project
- delete bucket ideas or active projects from the UI

## API

- `GET /api/state`
- `GET /api/workspaces`
- `POST /api/workspaces/import`
- `POST /api/workspaces/generate`
- `GET /api/workspaces/{id}`
- `POST /api/workspaces/{id}/runs`
- `GET /api/runs/{id}`
- `POST /api/runs/{id}/approve`
- `POST /api/runs/{id}/reject`
- `GET /api/skills`
- `PUT /api/skills/{id}`
- `GET /api/recipes`
- `POST /api/recipes/{id}/clone`
- `PUT /api/recipes/{id}`
- `GET /api/projects/{id}`
- `GET /api/projects/{id}/download`
- `GET /api/projects/{id}/artifacts/{artifact_name}`
- `POST /api/run`
- `POST /api/organize`
- `POST /api/projects/select`
- `POST /api/projects/import`
- `POST /api/projects/{id}/instructions`
- `POST /api/projects/{id}/instructions/yolo`
- `POST /api/projects/{id}/build`
- `POST /api/projects/{id}/validate`
- `POST /api/projects/{id}/run`
- `POST /api/projects/{id}/improve`
- `POST /api/projects/{id}/auto`
- `DELETE /api/projects/{id}`
- `DELETE /api/ideas/{idea_id}`
- `POST /api/heartbeat`

## Notes

- unsupported ideas remain in the bucket and should not be promoted
- `data/BUCKET.md` and `data/active_projects.json` still exist as compatibility surfaces, but the control plane now lives in `BLIP_HOME/blip.db`
- workspaces are isolated from the app repo by default and runs operate in isolated branches/worktrees before approval
- REF uses a frozen rubric per project, but only after deterministic validation passes
- duplicate pipeline attempts are recorded and skipped so the same no-op work is not retried forever
