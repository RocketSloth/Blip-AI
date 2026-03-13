from pathlib import Path
import csv
import io
import json

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, PlainTextResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel import Field, SQLModel, Session, create_engine, select

BASE_DIR = Path(__file__).resolve().parent.parent
DB_PATH = BASE_DIR / "demo.db"
engine = create_engine(f"sqlite:///{DB_PATH}", connect_args={"check_same_thread": False})
templates = Jinja2Templates(directory=str(BASE_DIR / "app" / "templates"))
CONFIG = json.loads((BASE_DIR / "app" / "project_config.json").read_text(encoding="utf-8"))
app = FastAPI(title=CONFIG["project_title"])


class PrimaryRecord(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    title: str
    owner: str
    category: str
    status: str
    detail: str
    recommendation: str
    note: str = ""
    action_taken: str = ""
    metric_one: int = 0
    metric_two: int = 0


class FollowUpAction(SQLModel, table=True):
    id: int | None = Field(default=None, primary_key=True)
    record_title: str
    title: str
    owner: str
    status: str = "Open"


def _seed_payload() -> dict[str, object]:
    return json.loads((BASE_DIR / "demo_data" / "seed.json").read_text(encoding="utf-8"))


def initialize_app() -> None:
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        if session.exec(select(PrimaryRecord)).first() is None:
            payload = _seed_payload()
            for row in payload["records"]:
                session.add(PrimaryRecord(**row))
            for row in payload.get("actions", []):
                session.add(FollowUpAction(**row))
            session.commit()


def reset_demo_state() -> None:
    if DB_PATH.exists():
        DB_PATH.unlink()
    initialize_app()


@app.on_event("startup")
def on_startup() -> None:
    initialize_app()


def compute_stats(records: list[PrimaryRecord], actions: list[FollowUpAction]) -> list[dict[str, object]]:
    mode = CONFIG["stats_mode"]
    if mode == "queue":
        values = [
            sum(1 for item in records if item.status == "Open"),
            sum(1 for item in records if item.category.lower().startswith("high")),
            len({item.owner for item in records}),
        ]
    elif mode == "approval":
        values = [
            sum(1 for item in records if item.status == "Pending"),
            sum(1 for item in records if item.status == "Approved"),
            sum(1 for item in records if "Medium" in item.category or "High" in item.category),
        ]
    else:
        values = [
            round(sum(item.metric_one for item in records) / max(len(records), 1)),
            sum(item.metric_two for item in records),
            sum(1 for item in actions if item.status == "Open"),
        ]
    return [
        {"label": label, "value": value}
        for label, value in zip(CONFIG["stats_labels"], values, strict=False)
    ]


@app.get("/", response_class=HTMLResponse)
def homepage(request: Request, group: str | None = None) -> HTMLResponse:
    with Session(engine) as session:
        records = session.exec(select(PrimaryRecord).order_by(PrimaryRecord.id)).all()
        actions = session.exec(select(FollowUpAction).order_by(FollowUpAction.id)).all()
    if group:
        records = [item for item in records if item.title == group]
        actions = [item for item in actions if item.record_title == group]
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "config": CONFIG,
            "records": records,
            "actions": actions,
            "stats": compute_stats(records, actions),
            "available_groups": sorted({item.title for item in records} or {item.record_title for item in actions}),
            "selected_group": group or "",
        },
    )


@app.get("/records/{record_id}", response_class=HTMLResponse)
def record_detail(request: Request, record_id: int) -> HTMLResponse:
    with Session(engine) as session:
        record = session.get(PrimaryRecord, record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Record not found")
    return templates.TemplateResponse(
        "detail.html",
        {"request": request, "config": CONFIG, "record": record},
    )


@app.post("/records/{record_id}/act")
def update_record(
    record_id: int,
    note: str = Form(...),
    action_taken: str = Form(...),
) -> RedirectResponse:
    with Session(engine) as session:
        record = session.get(PrimaryRecord, record_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Record not found")
        record.note = note.strip()
        record.action_taken = action_taken.strip()
        if CONFIG["lane"] == "intake-approval":
            record.status = action_taken.strip()
        else:
            record.status = "Updated"
        session.add(record)
        session.commit()
    return RedirectResponse(url=f"/records/{record_id}", status_code=303)


@app.post("/actions")
def create_action(
    record_title: str = Form(...),
    title: str = Form(...),
    owner: str = Form(...),
) -> RedirectResponse:
    with Session(engine) as session:
        session.add(FollowUpAction(record_title=record_title, title=title, owner=owner, status="Open"))
        session.commit()
    return RedirectResponse(url=f"/?group={record_title}", status_code=303)


@app.get("/export.csv")
def export_csv(group: str | None = None) -> PlainTextResponse:
    with Session(engine) as session:
        records = session.exec(select(PrimaryRecord).order_by(PrimaryRecord.id)).all()
    if group:
        records = [item for item in records if item.title == group]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["title", "owner", "category", "status", "metric_one", "metric_two"])
    for row in records:
        writer.writerow([row.title, row.owner, row.category, row.status, row.metric_one, row.metric_two])
    return PlainTextResponse(buffer.getvalue(), media_type="text/csv")
