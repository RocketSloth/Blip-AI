# Blip Autonomous MVP Factory

Blip is no longer a free-form "idea improver." It now acts as an autonomous MVP factory for three narrow B2B lanes:

- internal ops copilots
- intake and approval workflows
- reporting dashboards

Every promoted project moves through the same pipeline:

1. qualify the idea into a supported lane
2. freeze a `PRODUCT_BRIEF.json`
3. scaffold a canonical repo on one golden stack
4. run deterministic validation gates
5. let REF score qualitative quality only after the hard gates pass

README-only edits no longer count as progress. A project only improves when it stays runnable, passes validation, and strengthens the main workflow.

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

## What Runs Automatically

Manual actions:

- `POST /api/run` researches new lane-fit ideas
- `POST /api/organize` reorganizes the bucket

Automatic actions:

- the heartbeat only iterates active projects with `auto_run=true`
- each cycle uses the staged build pipeline and deterministic validation
- projects stop auto-running once they hit the target score of `95`

GitHub import actions:

- `POST /api/projects/import` clones the repository and immediately generates a persisted `REPO_DIGEST.json`
- imported projects keep manual instructions in `instructions.txt` and the AI execution brief in `REPO_DIGEST.json`
- the YOLO action now regenerates the AI repo diagnosis and a productive repo-specific improvement plan

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
|   |-- active_projects.json
|   `-- projects/
|-- static/
|   `-- index.html
|-- tests/
|   `-- test_project_workflow.py
`-- requirements.txt
```

## Install And Run

Set your API key:

```bash
export OPENAI_API_KEY="your_key_here"
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

## UI Features

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
- active projects only write inside their own `data/projects/<slug>/` workspace
- REF uses a frozen rubric per project, but only after deterministic validation passes
- duplicate pipeline attempts are recorded and skipped so the same no-op work is not retried forever
