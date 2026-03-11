# Trend Bucket Agents

A lightweight AI workspace with two cooperating agents:

- A research agent that finds fresh software project ideas.
- An organizer agent that reads `data/BUCKET.md` and groups ideas into sections.
- A FastAPI app and web UI to run either workflow on demand.

## What this does

One research cycle now works like this:

1. Read `data/BUCKET.md` to load previously generated ideas.
2. Ask OpenAI for fresh trend-based ideas.
3. Filter out duplicate titles against the existing bucket.
4. Append new ideas to the raw `## Project Ideas` list.
5. Run a second OpenAI pass that groups all ideas into `## Organized Projects`.
6. Append run history to the markdown file.

This keeps the raw list intact while also maintaining an LLM-organized view of the same bucket.

## Project layout

```text
.
|-- app/
|   |-- agent.py        # Research agent + bucket organizer agent
|   |-- bucket.py       # Markdown bucket parsing/writing
|   |-- config.py       # Runtime settings model
|   `-- main.py         # FastAPI app + scheduler + API routes
|-- data/
|   `-- BUCKET.md       # Persistent markdown bucket
|-- static/
|   `-- index.html      # UI for running and reviewing agents
`-- requirements.txt
```

## Requirements

- Python 3.10+
- OpenAI API key

Set your key:

```bash
export OPENAI_API_KEY="your_key_here"
```

## Install and run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`

## UI features

- `Run research + organize` to generate new ideas and immediately regroup the bucket.
- `Organize existing bucket` to re-cluster the current markdown file without generating new ideas.
- Heartbeat editor for scheduled background runs.
- Organized section view plus the raw append-only project list.

## API

- `GET /api/state` returns heartbeat, run metadata, raw projects, and organized sections.
- `POST /api/run` runs research followed by organization.
- `POST /api/organize` runs only the organizer agent.
- `POST /api/heartbeat` updates the scheduler interval.

## Notes

- Default heartbeat is `120` seconds.
- Minimum heartbeat is `30` seconds.
- Deduplication is title-based and case-insensitive.
- `BUCKET.md` now stores both the raw idea stream and an LLM-organized section view.
