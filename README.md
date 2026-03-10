# Trend Bucket Agent

A lightweight AI agent that:

- Researches **latest software/AI trends** using OpenAI.
- Creates short, actionable project ideas.
- Stores all generated ideas in a markdown **Bucket** file.
- Runs automatically on a configurable heartbeat (default **2 minutes**).
- Provides a clean web UI to review and manage runs.

## What this does

The agent performs one cycle as follows:

1. Reads `data/BUCKET.md` to load previously generated ideas.
2. Sends an OpenAI request that asks for fresh trend-based ideas.
3. Filters out duplicate titles against existing bucket content.
4. Appends new ideas + run history to `data/BUCKET.md`.

This means the markdown file is both the persistent store and a memory source to avoid duplicates.

## Project layout

```
.
├── app/
│   ├── agent.py        # OpenAI-driven trend research + idea generation
│   ├── bucket.py       # Markdown bucket parsing/writing
│   ├── config.py       # Runtime settings model
│   └── main.py         # FastAPI app + scheduler + API routes
├── data/
│   └── BUCKET.md       # Created automatically if missing
├── static/
│   └── index.html      # GUI
└── requirements.txt
```

## Requirements

- Python 3.10+
- OpenAI API key

Set your key:

```bash
export OPENAI_API_KEY="your_key_here"
```

## Install & run

```bash
pip install -r requirements.txt
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Open: `http://localhost:8000`

## GUI features

- **Run research now** button for immediate generation.
- **Heartbeat editor** (seconds) so you can change cadence later.
- Live list of project ideas currently in the bucket.
- Last run timestamp display.

## API

- `GET /api/state` → returns current heartbeat, run metadata, and bucket projects.
- `POST /api/run` → executes one research cycle immediately.
- `POST /api/heartbeat` → updates heartbeat interval.

Example heartbeat update:

```bash
curl -X POST http://localhost:8000/api/heartbeat \
  -H "Content-Type: application/json" \
  -d '{"heartbeat_seconds": 180}'
```

## Notes

- Default heartbeat is **120 seconds (2 minutes)**.
- Minimum heartbeat is 30 seconds.
- Deduplication is title-based (case-insensitive).
- Bucket file format is human-readable markdown for easy manual sorting later.

## Future improvements

- Semantic duplicate detection (embedding similarity).
- Category tags (e.g., SaaS, infra, AI workflow, devtools).
- Manual pin/archive controls in GUI.
