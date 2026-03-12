from __future__ import annotations

import asyncio
from io import BytesIO
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

from dotenv import load_dotenv

load_dotenv()
if os.environ.get("OPENAI_API_KEY"):
    os.environ["OPENAI_API_KEY"] = os.environ["OPENAI_API_KEY"].strip().strip('"').strip("'")

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent import BucketOrganizerAgent, ProjectBuilderAgent, TrendResearchAgent
from app.bucket import BucketStore, ProjectIdea
from app.config import AgentSettings
from app.project_store import ActiveProjectStore, idea_id_for_project, idea_id_from_parts

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class HeartbeatUpdate(BaseModel):
    heartbeat_seconds: int = Field(ge=30, le=3600)


class ProjectSelection(BaseModel):
    idea_id: str


class ProjectAutoRunUpdate(BaseModel):
    auto_run: bool


class AgentRuntime:
    def __init__(self) -> None:
        self.settings = AgentSettings()
        self.bucket = BucketStore()
        self.project_store = ActiveProjectStore()
        self.research_agent = TrendResearchAgent(settings=self.settings, bucket=self.bucket)
        self.organizer_agent = BucketOrganizerAgent(settings=self.settings, bucket=self.bucket)
        self.project_agent = ProjectBuilderAgent(
            settings=self.settings,
            bucket=self.bucket,
            projects=self.project_store,
        )
        self.last_run: str | None = None
        self.last_result: dict[str, Any] | None = None
        self._task: asyncio.Task | None = None
        self._lock = Lock()

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            try:
                self.run_project_heartbeat_once()
            except Exception:
                logger.exception("Background project heartbeat failed")
            await asyncio.sleep(self.settings.heartbeat_seconds)

    def _set_last_result(self, result: dict[str, Any]) -> dict[str, Any]:
        completed_at = result.get("run_at", _now_iso())
        self.last_run = completed_at
        self.last_result = result
        return result

    def run_once(self) -> dict[str, Any]:
        with self._lock:
            research_result = self.research_agent.run_once()
            organizer_result = self.organizer_agent.run_once()
            result = {
                "research": research_result,
                "organizer": organizer_result,
                "run_at": _now_iso(),
            }
            return self._set_last_result(result)

    def organize_once(self) -> dict[str, Any]:
        with self._lock:
            organizer_result = self.organizer_agent.run_once()
            result = {
                "organizer": organizer_result,
                "run_at": _now_iso(),
            }
            return self._set_last_result(result)

    def run_project_heartbeat_once(self) -> dict[str, Any]:
        with self._lock:
            result = {
                "project_heartbeat": self.project_agent.run_auto_projects_once(),
                "run_at": _now_iso(),
            }
            return self._set_last_result(result)

    def select_project(self, idea_id: str) -> dict[str, Any]:
        with self._lock:
            idea = self._bucket_project_by_id(idea_id)
            if idea is None:
                raise ValueError("Project idea not found.")
            result = self.project_agent.promote_project(idea)
            return self._set_last_result(result)

    def run_project_once(self, project_id: str) -> dict[str, Any]:
        with self._lock:
            result = self.project_agent.run_cycle(project_id, manual=True)
            return self._set_last_result(result)

    def build_project_once(self, project_id: str) -> dict[str, Any]:
        with self._lock:
            result = self.project_agent.run_build_stage(project_id)
            return self._set_last_result(result)

    def validate_project_once(self, project_id: str) -> dict[str, Any]:
        with self._lock:
            result = self.project_agent.run_validation_stage(project_id)
            return self._set_last_result(result)

    def set_project_auto_run(self, project_id: str, auto_run: bool) -> dict[str, Any]:
        with self._lock:
            project = self.project_store.get_project(project_id)
            if project is None:
                raise ValueError("Project not found.")
            if auto_run and project.current_score >= project.target_score:
                raise ValueError("Project already reached the target score.")
            project.auto_run = auto_run
            if auto_run:
                project.status = "active"
            self.project_store.save_project(project)
            result = {
                "project": self.project_store.project_summary(project),
                "run_at": _now_iso(),
            }
            return self._set_last_result(result)

    def project_detail(self, project_id: str) -> dict[str, Any]:
        project = self.project_store.get_project(project_id)
        if project is None:
            raise ValueError("Project not found.")
        detail = self.project_store.project_summary(project, attempt_limit=25)
        detail["ref_rubric"] = project.ref_rubric.model_dump()
        return detail

    def download_project_archive(self, project_id: str) -> tuple[str, bytes]:
        project = self.project_store.get_project(project_id)
        if project is None:
            raise ValueError("Project not found.")
        archive = self.project_store.build_project_archive(project)
        return f"{project.slug}.zip", archive

    def validation_artifact(self, project_id: str, artifact_name: str) -> Path:
        project = self.project_store.get_project(project_id)
        if project is None:
            raise ValueError("Project not found.")
        path = self.project_store.artifact_path(project, artifact_name)
        if not path.exists() or not path.is_file():
            raise ValueError("Artifact not found.")
        return path

    def state(self) -> dict[str, Any]:
        active_projects = self.project_store.list_projects()
        active_by_idea = {
            idea_id_from_parts(project.source_title, project.source_created_at): project.id
            for project in active_projects
        }
        bucket_projects = []
        for project in self.bucket.list_projects():
            idea_id = idea_id_for_project(project)
            bucket_projects.append(
                {
                    **project.__dict__,
                    "idea_id": idea_id,
                    "active_project_id": active_by_idea.get(idea_id),
                }
            )

        organized_sections = [
            {
                "name": section.name,
                "projects": [
                    {
                        **project.__dict__,
                        "idea_id": idea_id_for_project(project),
                        "active_project_id": active_by_idea.get(idea_id_for_project(project)),
                    }
                    for project in section.projects
                ],
            }
            for section in self.bucket.list_organized_sections()
        ]

        return {
            "heartbeat_seconds": self.settings.heartbeat_seconds,
            "last_run": self.last_run,
            "last_result": self.last_result,
            "projects": bucket_projects,
            "organized_sections": organized_sections,
            "active_projects": [
                self.project_store.project_summary(project) for project in active_projects
            ],
        }

    def _bucket_project_by_id(self, idea_id: str) -> ProjectIdea | None:
        for project in self.bucket.list_projects():
            if idea_id_for_project(project) == idea_id:
                return project
        return None


runtime = AgentRuntime()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await runtime.start()
    yield
    await runtime.stop()


app = FastAPI(title="Blip Autonomous MVP Factory", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(Path("static/index.html"))


@app.get("/api/state")
def state() -> dict[str, Any]:
    return runtime.state()


@app.get("/api/projects/{project_id}")
def project_detail(project_id: str) -> dict[str, Any]:
    try:
        return runtime.project_detail(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/download")
def download_project(project_id: str) -> StreamingResponse:
    try:
        filename, archive = runtime.download_project_archive(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return StreamingResponse(
        BytesIO(archive),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/api/projects/{project_id}/artifacts/{artifact_name:path}")
def download_validation_artifact(project_id: str, artifact_name: str) -> FileResponse:
    try:
        path = runtime.validation_artifact(project_id, artifact_name)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return FileResponse(path)


@app.post("/api/run")
def run_now() -> dict[str, Any]:
    try:
        return runtime.run_once()
    except Exception as exc:
        logger.exception("Run failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/organize")
def organize_now() -> dict[str, Any]:
    try:
        return runtime.organize_once()
    except Exception as exc:
        logger.exception("Organization failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/projects/select")
def select_project(payload: ProjectSelection) -> dict[str, Any]:
    try:
        return runtime.select_project(payload.idea_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Project promotion failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/run")
def run_project(project_id: str) -> dict[str, Any]:
    try:
        return runtime.run_project_once(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Project run failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/build")
def build_project(project_id: str) -> dict[str, Any]:
    try:
        return runtime.build_project_once(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Project build stage failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/validate")
def validate_project(project_id: str) -> dict[str, Any]:
    try:
        return runtime.validate_project_once(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Project validation stage failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/auto")
def update_project_auto(project_id: str, payload: ProjectAutoRunUpdate) -> dict[str, Any]:
    try:
        return runtime.set_project_auto_run(project_id, payload.auto_run)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Project auto-run update failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/heartbeat")
def update_heartbeat(payload: HeartbeatUpdate) -> dict[str, Any]:
    runtime.settings.heartbeat_seconds = payload.heartbeat_seconds
    return {"heartbeat_seconds": runtime.settings.heartbeat_seconds}
