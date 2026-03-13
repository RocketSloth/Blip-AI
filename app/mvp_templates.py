from __future__ import annotations

from dataclasses import dataclass
import json
from textwrap import dedent

from app.lanes_config import get_lane_labels
from app.project_store import ProductBrief, SupportedLane


@dataclass
class TemplateBundle:
    lane: SupportedLane
    template_id: str
    run_command: str
    test_command: str
    required_paths: list[str]
    files: dict[str, str]


def build_template_bundle(project_title: str, brief: ProductBrief) -> TemplateBundle:
    if brief.lane == "unsupported":
        raise ValueError("Unsupported ideas cannot be scaffolded.")

    lane_config = _lane_config(brief)
    bundle = TemplateBundle(
        lane=brief.lane,
        template_id=f"{brief.lane}-v1",
        run_command="uvicorn app.main:app --reload",
        test_command="pytest -q",
        required_paths=[
            "README.md",
            "PROJECT_PLAN.md",
            "requirements.txt",
            "run.bat",
            "app/__init__.py",
            "app/main.py",
            "app/project_config.json",
            "app/templates/base.html",
            "app/templates/index.html",
            "app/templates/detail.html",
            "demo_data/seed.json",
            "tests/test_app.py",
        ],
        files={},
    )
    bundle.files = {
        "README.md": _readme(project_title, brief, bundle),
        "PROJECT_PLAN.md": _project_plan(brief),
        "requirements.txt": _requirements_txt(),
        "run.bat": _run_bat(bundle),
        "app/__init__.py": "",
        "app/project_config.json": json.dumps(lane_config, indent=2),
        "app/main.py": _generic_app_main(),
        "app/templates/base.html": _base_html(),
        "app/templates/index.html": _index_html(),
        "app/templates/detail.html": _detail_html(),
        "demo_data/seed.json": json.dumps(_seed_payload(brief.lane), indent=2),
        "tests/test_app.py": _tests_for_lane(brief.lane),
    }
    return bundle


def _lane_config(brief: ProductBrief) -> dict[str, object]:
    shared = {
        "project_title": brief.title,
        "lane": brief.lane,
        "lane_label": get_lane_labels().get(brief.lane, brief.lane),
        "problem": brief.problem,
        "success_metric": brief.success_metric,
        "target_user": brief.target_user,
        "workflow": brief.must_have_flow,
    }
    if brief.lane == "ops-copilot":
        shared.update(
            {
                "workflow_mode": "detail-update",
                "list_heading": "Priority Queue",
                "detail_heading": "Log follow-up",
                "stats_mode": "queue",
                "primary_label": "Task",
                "secondary_label": "Owner",
                "category_label": "Priority",
                "note_label": "Latest note",
                "action_label": "Action taken",
                "primary_button": "Save follow-up",
                "filter_enabled": False,
                "export_enabled": False,
                "stats_labels": ["Open work", "High priority", "Owners active"],
            }
        )
    elif brief.lane == "intake-approval":
        shared.update(
            {
                "workflow_mode": "detail-update",
                "list_heading": "Review Queue",
                "detail_heading": "Record review decision",
                "stats_mode": "approval",
                "primary_label": "Submission",
                "secondary_label": "Requester",
                "category_label": "Risk / department",
                "note_label": "Reviewer notes",
                "action_label": "Decision",
                "primary_button": "Save decision",
                "filter_enabled": False,
                "export_enabled": False,
                "stats_labels": ["Pending", "Approved", "High attention"],
            }
        )
    else:
        shared.update(
            {
                "workflow_mode": "create-action",
                "list_heading": "Performance Dashboard",
                "detail_heading": "Team detail",
                "stats_mode": "dashboard",
                "primary_label": "Team",
                "secondary_label": "Owner",
                "category_label": "Trend",
                "note_label": "Context",
                "action_label": "Action owner",
                "primary_button": "Create follow-up",
                "filter_enabled": True,
                "export_enabled": True,
                "stats_labels": ["Average score", "Blocked hours", "Open actions"],
            }
        )
    return shared


def _seed_payload(lane: SupportedLane) -> dict[str, object]:
    if lane == "ops-copilot":
        return {
            "records": [
                {
                    "title": "Escalated invoice queue",
                    "owner": "Finance Ops",
                    "category": "High",
                    "status": "Open",
                    "detail": "Aging report crossed SLA for 12 invoices.",
                    "recommendation": "Notify owners and bundle work by vendor.",
                    "note": "Waiting on vendor callbacks.",
                    "action_taken": "Waiting",
                    "metric_one": 12,
                    "metric_two": 5,
                },
                {
                    "title": "Field inspection follow-up",
                    "owner": "Operations Lead",
                    "category": "Medium",
                    "status": "Review",
                    "detail": "Three inspections show the same missing permit.",
                    "recommendation": "Create one checklist for the recurring issue.",
                    "note": "Needs owner assignment.",
                    "action_taken": "Bundle",
                    "metric_one": 3,
                    "metric_two": 1,
                },
            ],
            "actions": [],
        }
    if lane == "intake-approval":
        return {
            "records": [
                {
                    "title": "New vendor onboarding",
                    "owner": "Alicia Jones",
                    "category": "Medium / Finance",
                    "status": "Pending",
                    "detail": "W-9 expiration needs confirmation.",
                    "recommendation": "Confirm packet and route to compliance.",
                    "note": "Vendor packet almost complete.",
                    "action_taken": "Pending",
                    "metric_one": 2,
                    "metric_two": 1,
                },
                {
                    "title": "Software access request",
                    "owner": "Evan Tran",
                    "category": "Low / Operations",
                    "status": "Pending",
                    "detail": "Manager approval required before provisioning.",
                    "recommendation": "Confirm manager sign-off and assign to IT.",
                    "note": "Awaiting manager reply.",
                    "action_taken": "Pending",
                    "metric_one": 1,
                    "metric_two": 0,
                },
            ],
            "actions": [],
        }
    return {
        "records": [
            {
                "title": "Inspection Ops",
                "owner": "Ops Analyst",
                "category": "Up",
                "status": "Healthy",
                "detail": "Focus time improved after queue cleanup.",
                "recommendation": "Keep batching permit reviews twice weekly.",
                "note": "Strong momentum after last process change.",
                "action_taken": "Monitor",
                "metric_one": 82,
                "metric_two": 7,
            },
            {
                "title": "Client Success",
                "owner": "Support Lead",
                "category": "Down",
                "status": "Watch",
                "detail": "Blocked time is rising because of ticket routing.",
                "recommendation": "Review routing rules and tighten ownership.",
                "note": "Queue handoffs are increasing.",
                "action_taken": "Review routing",
                "metric_one": 68,
                "metric_two": 11,
            },
        ],
        "actions": [
            {
                "record_title": "Client Success",
                "title": "Review ticket routing rules",
                "owner": "Ops Analyst",
                "status": "Open",
            }
        ],
    }


def _requirements_txt() -> str:
    return dedent(
        """\
        fastapi==0.115.0
        uvicorn==0.30.6
        sqlmodel==0.0.22
        jinja2==3.1.4
        python-multipart==0.0.9
        pytest==8.3.3
        httpx<0.28
        """
    )


def _run_bat(bundle: TemplateBundle) -> str:
    # Use python -m uvicorn so it works when uvicorn is not on PATH
    run_cmd = (
        "python -m uvicorn app.main:app --reload"
        if "uvicorn" in bundle.run_command
        else bundle.run_command
    )
    return dedent(
        f"""
        @echo off
        echo Installing dependencies...
        pip install -r requirements.txt
        if errorlevel 1 (
            echo Failed to install dependencies. Make sure Python and pip are installed.
            pause
            exit /b 1
        )
        echo.
        echo Starting the app...
        {run_cmd}
        pause
        """
    ).strip()


def _readme(project_title: str, brief: ProductBrief, bundle: TemplateBundle) -> str:
    criteria = "\n".join(f"- {item}" for item in brief.acceptance_criteria)
    return dedent(
        f"""\
        # {project_title}

        {brief.opportunity_summary}

        ## Product Brief
        - Lane: {get_lane_labels().get(brief.lane, brief.lane)}
        - Target user: {brief.target_user}
        - ICP: {brief.icp}
        - Job to be done: {brief.job_to_be_done}
        - Success metric: {brief.success_metric}

        ## Must-Have Flow
        {brief.must_have_flow}

        ## Demo Scenario
        {brief.demo_scenario}

        ## Acceptance Criteria
        {criteria}

        ## Local Setup

        ### Quick start (Windows)
        Double-click **`run.bat`** in the project folder. It will install dependencies and start the app.  
        Open http://localhost:8000 in your browser when it says the server is running.

        ### Manual setup (all platforms)
        If you prefer not to use the batch file, or you're on macOS/Linux:

        1. **Create and activate a virtual environment** (recommended):
           - Windows: `python -m venv .venv` then `.venv\\Scripts\\activate`
           - macOS/Linux: `python3 -m venv .venv` then `source .venv/bin/activate`
        2. **Install dependencies:** `pip install -r requirements.txt`
        3. **Start the app:** `{bundle.run_command}`  
           (If `uvicorn` is not on your PATH, use: `python -m uvicorn app.main:app --reload`)
        4. **Run tests:** `{bundle.test_command}`

        Then open http://localhost:8000 in your browser.

        ## Notes
        - Demo data is seeded automatically on startup.
        - Validation expects the homepage, demo data, and primary workflow tests to pass.
        """
    )


def _project_plan(brief: ProductBrief) -> str:
    return dedent(
        f"""\
        # Project Plan

        ## Problem
        {brief.problem}

        ## Must-Have Screens
        {chr(10).join(f"- {item}" for item in brief.must_have_screens)}

        ## Must-Have Actions
        {chr(10).join(f"- {item}" for item in brief.must_have_actions)}

        ## Required Entities
        {chr(10).join(f"- {item}" for item in brief.required_entities)}

        ## Demo Scenario
        {brief.demo_scenario}
        """
    )


def _generic_app_main() -> str:
    return dedent(
        """\
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
        """
    )


def _base_html() -> str:
    return dedent(
        """\
        <!doctype html>
        <html lang="en">
          <head>
            <meta charset="UTF-8" />
            <meta name="viewport" content="width=device-width, initial-scale=1.0" />
            <title>{{ config.project_title }}</title>
            <script src="https://unpkg.com/htmx.org@1.9.12"></script>
            <style>
              :root { color-scheme: light; }
              * { box-sizing: border-box; }
              body {
                margin: 0;
                font-family: "Segoe UI", sans-serif;
                background: linear-gradient(180deg, #eef4fb 0%, #f7f9fc 100%);
                color: #162336;
              }
              .shell { max-width: 1100px; margin: 0 auto; padding: 2rem 1.25rem 3rem; }
              .hero {
                background: linear-gradient(135deg, #12324f, #0f766e);
                color: white;
                border-radius: 22px;
                padding: 1.5rem;
              }
              .hero p { color: rgba(255,255,255,0.86); max-width: 760px; }
              .chips { display: flex; flex-wrap: wrap; gap: 0.5rem; }
              .chip { border-radius: 999px; padding: 0.28rem 0.62rem; background: rgba(255,255,255,0.15); }
              .grid { display: grid; gap: 1rem; margin-top: 1rem; }
              .two-col { grid-template-columns: 1.35fr 1fr; }
              .panel { background: white; border: 1px solid #d7dee7; border-radius: 18px; padding: 1rem 1.1rem; }
              .stats { display: grid; gap: 0.85rem; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); }
              .stat { border: 1px solid #d7dee7; border-radius: 14px; padding: 0.9rem; }
              .stat strong { display: block; font-size: 1.5rem; margin-top: 0.25rem; }
              table { width: 100%; border-collapse: collapse; }
              th, td { padding: 0.7rem 0.55rem; border-bottom: 1px solid #d7dee7; text-align: left; vertical-align: top; }
              form { display: grid; gap: 0.75rem; }
              input, select, textarea, button { font: inherit; }
              input, select, textarea {
                width: 100%;
                padding: 0.65rem 0.7rem;
                border-radius: 10px;
                border: 1px solid #d7dee7;
              }
              button {
                border: none;
                border-radius: 10px;
                background: #0f766e;
                color: white;
                padding: 0.7rem 0.95rem;
                cursor: pointer;
                font-weight: 700;
              }
              a { color: #0f4f7a; text-decoration: none; }
              .muted { color: #5f6e81; }
              @media (max-width: 900px) { .two-col { grid-template-columns: 1fr; } }
            </style>
          </head>
          <body>
            <div class="shell">
              <section class="hero">
                <h1>{{ config.project_title }}</h1>
                <p>{{ config.problem }}</p>
                <div class="chips">
                  <span class="chip">{{ config.lane_label }}</span>
                  <span class="chip">Target user: {{ config.target_user }}</span>
                  <span class="chip">Success metric: {{ config.success_metric }}</span>
                </div>
                <p class="muted">Must-have flow: {{ config.workflow }}</p>
              </section>
              {% block content %}{% endblock %}
            </div>
          </body>
        </html>
        """
    )


def _index_html() -> str:
    return dedent(
        """\
        {% extends "base.html" %}
        {% block content %}
        <div class="grid two-col">
          <section class="panel">
            <h2>{{ config.list_heading }}</h2>
            <div class="stats">
              {% for stat in stats %}
              <div class="stat"><span class="muted">{{ stat.label }}</span><strong>{{ stat.value }}</strong></div>
              {% endfor %}
            </div>
            {% if config.filter_enabled %}
            <form method="get">
              <label>
                Filter by team
                <select name="group">
                  <option value="">All teams</option>
                  {% for group in available_groups %}
                  <option value="{{ group }}" {% if group == selected_group %}selected{% endif %}>{{ group }}</option>
                  {% endfor %}
                </select>
              </label>
              <button type="submit">Apply filter</button>
            </form>
            {% endif %}
            {% if config.export_enabled %}
            <p><a href="/export.csv{% if selected_group %}?group={{ selected_group }}{% endif %}">Export current view as CSV</a></p>
            {% endif %}
            <table>
              <thead>
                <tr>
                  <th>{{ config.primary_label }}</th>
                  <th>{{ config.secondary_label }}</th>
                  <th>{{ config.category_label }}</th>
                  <th>Status</th>
                  <th>Recommendation</th>
                </tr>
              </thead>
              <tbody>
                {% for record in records %}
                <tr>
                  <td><a href="/records/{{ record.id }}">{{ record.title }}</a></td>
                  <td>{{ record.owner }}</td>
                  <td>{{ record.category }}</td>
                  <td>{{ record.status }}</td>
                  <td>{{ record.recommendation }}</td>
                </tr>
                {% endfor %}
              </tbody>
            </table>
          </section>
          <section class="panel">
            {% if config.workflow_mode == "create-action" %}
            <h2>Follow-Up Actions</h2>
            <form hx-post="/actions" method="post">
              <label>
                Team
                <select name="record_title">
                  {% for group in available_groups %}
                  <option value="{{ group }}">{{ group }}</option>
                  {% endfor %}
                </select>
              </label>
              <label>
                Action title
                <input name="title" required />
              </label>
              <label>
                Action owner
                <input name="owner" required />
              </label>
              <button type="submit">{{ config.primary_button }}</button>
            </form>
            <table>
              <thead><tr><th>Team</th><th>Action</th><th>Owner</th><th>Status</th></tr></thead>
              <tbody>
                {% for action in actions %}
                <tr>
                  <td>{{ action.record_title }}</td>
                  <td>{{ action.title }}</td>
                  <td>{{ action.owner }}</td>
                  <td>{{ action.status }}</td>
                </tr>
                {% endfor %}
              </tbody>
            </table>
            {% else %}
            <h2>Primary Workflow</h2>
            <p class="muted">Open a record, update {{ config.note_label|lower }}, and set {{ config.action_label|lower }} to move the workflow forward.</p>
            <ul>
              <li>Review the highest-priority record</li>
              <li>Capture the latest context</li>
              <li>Save the action taken so the queue stays usable</li>
            </ul>
            {% endif %}
          </section>
        </div>
        {% endblock %}
        """
    )


def _detail_html() -> str:
    return dedent(
        """\
        {% extends "base.html" %}
        {% block content %}
        <div class="grid two-col">
          <section class="panel">
            <h2>{{ record.title }}</h2>
            <p><strong>{{ config.secondary_label }}:</strong> {{ record.owner }}</p>
            <p><strong>{{ config.category_label }}:</strong> {{ record.category }}</p>
            <p><strong>Status:</strong> {{ record.status }}</p>
            <p><strong>Context:</strong> {{ record.detail }}</p>
            <p><strong>Recommendation:</strong> {{ record.recommendation }}</p>
            <p><strong>{{ config.note_label }}:</strong> {{ record.note }}</p>
            <p><strong>{{ config.action_label }}:</strong> {{ record.action_taken }}</p>
            <p><a href="/">Back to {{ config.list_heading|lower }}</a></p>
          </section>
          <section class="panel">
            <h2>{{ config.detail_heading }}</h2>
            <form hx-post="/records/{{ record.id }}/act" method="post">
              <label>
                {{ config.note_label }}
                <textarea name="note" rows="4" required>{{ record.note }}</textarea>
              </label>
              <label>
                {{ config.action_label }}
                <input name="action_taken" value="{{ record.action_taken }}" required />
              </label>
              <button type="submit">{{ config.primary_button }}</button>
            </form>
          </section>
        </div>
        {% endblock %}
        """
    )


def _tests_for_lane(lane: SupportedLane) -> str:
    if lane == "reporting-dashboard":
        return dedent(
            """\
            from fastapi.testclient import TestClient

            from app.main import app, reset_demo_state


            def setup_function() -> None:
                reset_demo_state()


            def test_homepage_smoke() -> None:
                client = TestClient(app)
                response = client.get("/")
                assert response.status_code == 200
                assert "Performance Dashboard" in response.text


            def test_seeded_demo_data() -> None:
                client = TestClient(app)
                response = client.get("/")
                assert "Inspection Ops" in response.text
                assert "Review ticket routing rules" in response.text


            def test_primary_workflow() -> None:
                client = TestClient(app)
                response = client.post(
                    "/actions",
                    data={"record_title": "Inspection Ops", "title": "Escalate permit review", "owner": "Team Lead"},
                    follow_redirects=True,
                )
                assert response.status_code == 200
                assert "Escalate permit review" in response.text
                export = client.get("/export.csv")
                assert export.status_code == 200
                assert "Inspection Ops" in export.text
            """
        )
    if lane == "intake-approval":
        return dedent(
            """\
            from fastapi.testclient import TestClient

            from app.main import app, reset_demo_state


            def setup_function() -> None:
                reset_demo_state()


            def test_homepage_smoke() -> None:
                client = TestClient(app)
                response = client.get("/")
                assert response.status_code == 200
                assert "Review Queue" in response.text


            def test_seeded_demo_data() -> None:
                client = TestClient(app)
                response = client.get("/")
                assert "New vendor onboarding" in response.text
                assert "Alicia Jones" in response.text


            def test_primary_workflow() -> None:
                client = TestClient(app)
                response = client.post(
                    "/records/1/act",
                    data={"note": "Vendor packet complete.", "action_taken": "Approved"},
                    follow_redirects=True,
                )
                assert response.status_code == 200
                assert "Approved" in response.text
                assert "Vendor packet complete." in response.text
            """
        )
    return dedent(
        """\
        from fastapi.testclient import TestClient

        from app.main import app, reset_demo_state


        def setup_function() -> None:
            reset_demo_state()


        def test_homepage_smoke() -> None:
            client = TestClient(app)
            response = client.get("/")
            assert response.status_code == 200
            assert "Priority Queue" in response.text


        def test_seeded_demo_data() -> None:
            client = TestClient(app)
            response = client.get("/")
            assert "Escalated invoice queue" in response.text
            assert "Finance Ops" in response.text


        def test_primary_workflow() -> None:
            client = TestClient(app)
            response = client.post(
                "/records/1/act",
                data={"note": "Called vendor and grouped invoices.", "action_taken": "Escalated"},
                follow_redirects=True,
            )
            assert response.status_code == 200
            assert "Called vendor and grouped invoices." in response.text
            assert "Escalated" in response.text
        """
    )
