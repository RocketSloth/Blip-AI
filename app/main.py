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
from app.blipd import BlipDaemon
from app.bucket import BucketStore, ProjectIdea
from app.config import AgentSettings
from app.lanes_config import get_lanes_config, save_lanes_config
from app.platform_store import PlatformStore, RecipeRecord, SkillRecord
from app.project_store import ActiveProjectStore, idea_id_for_project, idea_id_from_parts

logger = logging.getLogger(__name__)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class HeartbeatUpdate(BaseModel):
    heartbeat_seconds: int = Field(ge=30, le=3600)


class ProjectSelection(BaseModel):
    idea_id: str


class RepoImport(BaseModel):
    repo_url: str


class WorkspaceGenerate(BaseModel):
    idea_id: str


class WorkspaceRunRequest(BaseModel):
    recipe_id: str | None = None
    yolo: bool = False


class InstructionsUpdate(BaseModel):
    instructions: str = ""


class ProjectAutoRunUpdate(BaseModel):
    auto_run: bool


class LaneItem(BaseModel):
    id: str
    label: str = ""
    enabled: bool = True
    keywords: list[str] = Field(default_factory=list)


class LanesUpdate(BaseModel):
    lanes: list[LaneItem]


class SkillUpdate(BaseModel):
    enabled: bool


class RecipeClone(BaseModel):
    new_id: str | None = None


class RecipeUpdate(BaseModel):
    name: str
    description: str = ""
    definition: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True


class AgentRuntime:
    def __init__(self) -> None:
        self.settings = AgentSettings()
        self.bucket = BucketStore()
        self.project_store = ActiveProjectStore()
        self.platform_store = PlatformStore(project_store=self.project_store, bucket=self.bucket)
        self.research_agent = TrendResearchAgent(settings=self.settings, bucket=self.bucket)
        self.organizer_agent = BucketOrganizerAgent(settings=self.settings, bucket=self.bucket)
        self.project_agent = ProjectBuilderAgent(
            settings=self.settings,
            bucket=self.bucket,
            projects=self.project_store,
        )
        self.daemon = BlipDaemon(
            settings=self.settings,
            bucket=self.bucket,
            projects=self.project_store,
            platform=self.platform_store,
        )
        self.last_run: str | None = None
        self.last_result: dict[str, Any] | None = None
        self._task: asyncio.Task | None = None
        self._lock = Lock()

    def _sync_platform_bindings(self) -> None:
        self.platform_store.project_store = self.project_store
        self.platform_store.bucket = self.bucket
        self.daemon.projects = self.project_store
        self.daemon.bucket = self.bucket
        self.daemon.platform = self.platform_store

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
            self._sync_platform_bindings()
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
            self._sync_platform_bindings()
            organizer_result = self.organizer_agent.run_once()
            result = {
                "organizer": organizer_result,
                "run_at": _now_iso(),
            }
            return self._set_last_result(result)

    def run_project_heartbeat_once(self) -> dict[str, Any]:
        with self._lock:
            self._sync_platform_bindings()
            result = {
                "project_heartbeat": self.project_agent.run_auto_projects_once(),
                "run_at": _now_iso(),
            }
            return self._set_last_result(result)

    def import_project(self, repo_url: str) -> dict[str, Any]:
        with self._lock:
            self._sync_platform_bindings()
            project = self.project_store.create_project_from_github(repo_url)
            workspace = self.platform_store.upsert_workspace_from_project(project)
            try:
                digest_result = self.project_agent.generate_repo_digest(project.id)
                workspace = self.platform_store.upsert_workspace_from_project(self.project_store.get_project(project.id) or project)
                result = {
                    "project": self.project_store.project_summary(self.project_store.get_project(project.id) or project),
                    "workspace": workspace.model_dump(),
                    "repo_digest": digest_result["repo_digest"],
                    "message": "Repository cloned and repo digest completed.",
                    "run_at": digest_result.get("run_at", _now_iso()),
                }
            except Exception as exc:
                project = self.project_store.get_project(project.id) or project
                workspace = self.platform_store.upsert_workspace_from_project(project)
                result = {
                    "project": self.project_store.project_summary(project),
                    "workspace": workspace.model_dump(),
                    "repo_digest": self.project_store.load_repo_digest(project).model_dump(),
                    "message": f"Repository cloned, but repo digest did not complete: {exc}",
                    "run_at": _now_iso(),
                }
            return self._set_last_result(result)

    def select_project(self, idea_id: str) -> dict[str, Any]:
        with self._lock:
            self._sync_platform_bindings()
            idea = self._bucket_project_by_id(idea_id)
            if idea is None:
                raise ValueError("Project idea not found.")
            result = self.project_agent.promote_project(idea)
            project = self.project_store.find_by_idea(idea)
            if project is not None:
                result["workspace"] = self.platform_store.upsert_workspace_from_project(project).model_dump()
            return self._set_last_result(result)

    def run_project_once(self, project_id: str) -> dict[str, Any]:
        with self._lock:
            self._sync_platform_bindings()
            project = self.project_store.get_project(project_id)
            if project is None:
                raise ValueError("Project not found.")
            if getattr(project, "source_type", "bucket") == "github":
                result = self.project_agent.run_improvement(project_id)
            else:
                result = self.project_agent.run_cycle(project_id, manual=True)
            return self._set_last_result(result)

    def build_project_once(self, project_id: str) -> dict[str, Any]:
        with self._lock:
            self._sync_platform_bindings()
            result = self.project_agent.run_build_stage(project_id)
            return self._set_last_result(result)

    def validate_project_once(self, project_id: str) -> dict[str, Any]:
        with self._lock:
            self._sync_platform_bindings()
            result = self.project_agent.run_validation_stage(project_id)
            return self._set_last_result(result)

    def set_project_auto_run(self, project_id: str, auto_run: bool) -> dict[str, Any]:
        with self._lock:
            self._sync_platform_bindings()
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

    def delete_project(self, project_id: str) -> dict[str, Any]:
        with self._lock:
            self._sync_platform_bindings()
            project = self.project_store.delete_project(project_id)
            self.platform_store.delete_workspace(project_id)
            result = {
                "deleted_project_id": project.id,
                "deleted_title": project.title,
                "run_at": _now_iso(),
            }
            return self._set_last_result(result)

    def delete_idea(self, idea_id: str) -> dict[str, Any]:
        with self._lock:
            self._sync_platform_bindings()
            idea = self._bucket_project_by_id(idea_id)
            if idea is None:
                raise ValueError("Project idea not found.")
            self.bucket.delete_project(idea, run_at=_now_iso())
            self.platform_store.upsert_idea(
                ProjectIdea(title=idea.title, description=idea.description, created_at=idea.created_at),
                active_project_id=None,
            )
            result = {
                "deleted_idea_id": idea_id,
                "deleted_title": idea.title,
                "run_at": _now_iso(),
            }
            return self._set_last_result(result)

    def project_detail(self, project_id: str) -> dict[str, Any]:
        self._sync_platform_bindings()
        project = self.project_store.get_project(project_id)
        if project is None:
            raise ValueError("Project not found.")
        detail = self.project_store.project_summary(project, attempt_limit=25)
        detail["ref_rubric"] = project.ref_rubric.model_dump()
        return detail

    def download_project_archive(self, project_id: str) -> tuple[str, bytes]:
        self._sync_platform_bindings()
        project = self.project_store.get_project(project_id)
        if project is None:
            raise ValueError("Project not found.")
        archive = self.project_store.build_project_archive(project)
        return f"{project.slug}.zip", archive

    def validation_artifact(self, project_id: str, artifact_name: str) -> Path:
        self._sync_platform_bindings()
        project = self.project_store.get_project(project_id)
        if project is None:
            raise ValueError("Project not found.")
        path = self.project_store.artifact_path(project, artifact_name)
        if not path.exists() or not path.is_file():
            raise ValueError("Artifact not found.")
        return path

    def state(self) -> dict[str, Any]:
        self._sync_platform_bindings()
        self.platform_store.sync_legacy_state()
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
            "daemon_refresh_seconds": self.settings.daemon_refresh_seconds,
            "last_run": self.last_run,
            "last_result": self.last_result,
            "projects": bucket_projects,
            "organized_sections": organized_sections,
            "active_projects": [
                self.project_store.project_summary(project) for project in active_projects
            ],
            "workspaces": [workspace.model_dump() for workspace in self.platform_store.list_workspaces()],
            "recent_runs": [run.model_dump() for run in self.platform_store.list_runs(limit=15)],
            "approvals": [approval.model_dump() for approval in self.platform_store.list_approvals(limit=15)],
            "skills": [skill.model_dump() for skill in self.platform_store.list_skills()],
            "recipes": [recipe.model_dump() for recipe in self.platform_store.list_recipes()],
        }

    def list_workspaces(self) -> dict[str, Any]:
        self._sync_platform_bindings()
        self.platform_store.sync_legacy_state()
        return {"workspaces": [workspace.model_dump() for workspace in self.platform_store.list_workspaces()]}

    def workspace_detail(self, workspace_id: str) -> dict[str, Any]:
        self._sync_platform_bindings()
        self.platform_store.sync_legacy_state()
        return self.platform_store.workspace_detail(workspace_id)

    def import_workspace(self, repo_url: str) -> dict[str, Any]:
        return self.import_project(repo_url)

    def generate_workspace(self, idea_id: str) -> dict[str, Any]:
        return self.select_project(idea_id)

    def start_workspace_run(self, workspace_id: str, *, yolo: bool = False) -> dict[str, Any]:
        with self._lock:
            self._sync_platform_bindings()
            self.platform_store.sync_legacy_state()
            result = self.daemon.start_run(workspace_id, trigger="manual", yolo=yolo)
            return self._set_last_result(result)

    def run_detail(self, run_id: str) -> dict[str, Any]:
        self._sync_platform_bindings()
        return self.platform_store.run_detail(run_id)

    def approve_run(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            self._sync_platform_bindings()
            result = self.daemon.approve_run(run_id)
            return self._set_last_result(result)

    def reject_run(self, run_id: str) -> dict[str, Any]:
        with self._lock:
            self._sync_platform_bindings()
            result = self.daemon.reject_run(run_id)
            return self._set_last_result(result)

    def list_skills(self) -> dict[str, Any]:
        self._sync_platform_bindings()
        return {"skills": [skill.model_dump() for skill in self.platform_store.list_skills()]}

    def update_skill(self, skill_id: str, enabled: bool) -> dict[str, Any]:
        self._sync_platform_bindings()
        skill = self.platform_store.get_skill(skill_id)
        if skill is None:
            raise ValueError("Skill not found.")
        skill.enabled = enabled
        skill.updated_at = _now_iso()
        updated = self.platform_store.save_skill(skill)
        return {"skill": updated.model_dump(), "run_at": _now_iso()}

    def list_recipes(self) -> dict[str, Any]:
        self._sync_platform_bindings()
        return {"recipes": [recipe.model_dump() for recipe in self.platform_store.list_recipes()]}

    def clone_recipe(self, recipe_id: str, new_id: str | None = None) -> dict[str, Any]:
        self._sync_platform_bindings()
        recipe = self.platform_store.clone_recipe(recipe_id, new_id=new_id)
        return {"recipe": recipe.model_dump(), "run_at": _now_iso()}

    def update_recipe(self, recipe_id: str, payload: RecipeUpdate) -> dict[str, Any]:
        self._sync_platform_bindings()
        recipe = self.platform_store.get_recipe(recipe_id)
        if recipe is None:
            raise ValueError("Recipe not found.")
        if recipe.locked:
            raise ValueError("Built-in recipes are locked. Clone a recipe before editing it.")
        recipe.name = payload.name
        recipe.description = payload.description
        recipe.definition = payload.definition
        recipe.enabled = payload.enabled
        recipe.updated_at = _now_iso()
        updated = self.platform_store.save_recipe(recipe)
        return {"recipe": updated.model_dump(), "run_at": _now_iso()}

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


@app.get("/api/workspaces")
def list_workspaces() -> dict[str, Any]:
    return runtime.list_workspaces()


@app.post("/api/workspaces/import")
def import_workspace(payload: RepoImport) -> dict[str, Any]:
    try:
        return runtime.import_workspace(payload.repo_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Workspace import failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/workspaces/generate")
def generate_workspace(payload: WorkspaceGenerate) -> dict[str, Any]:
    try:
        return runtime.generate_workspace(payload.idea_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Workspace generation failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/workspaces/{workspace_id}")
def workspace_detail(workspace_id: str) -> dict[str, Any]:
    try:
        return runtime.workspace_detail(workspace_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/workspaces/{workspace_id}/runs")
def start_workspace_run(workspace_id: str, payload: WorkspaceRunRequest) -> dict[str, Any]:
    try:
        return runtime.start_workspace_run(workspace_id, yolo=payload.yolo)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Workspace run failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/runs/{run_id}")
def run_detail(run_id: str) -> dict[str, Any]:
    try:
        return runtime.run_detail(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/runs/{run_id}/approve")
def approve_run(run_id: str) -> dict[str, Any]:
    try:
        return runtime.approve_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Run approval failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/runs/{run_id}/reject")
def reject_run(run_id: str) -> dict[str, Any]:
    try:
        return runtime.reject_run(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Run rejection failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/skills")
def list_skills() -> dict[str, Any]:
    return runtime.list_skills()


@app.put("/api/skills/{skill_id}")
def update_skill(skill_id: str, payload: SkillUpdate) -> dict[str, Any]:
    try:
        return runtime.update_skill(skill_id, payload.enabled)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/api/recipes")
def list_recipes() -> dict[str, Any]:
    return runtime.list_recipes()


@app.post("/api/recipes/{recipe_id}/clone")
def clone_recipe(recipe_id: str, payload: RecipeClone) -> dict[str, Any]:
    try:
        return runtime.clone_recipe(recipe_id, new_id=payload.new_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/api/recipes/{recipe_id}")
def update_recipe(recipe_id: str, payload: RecipeUpdate) -> dict[str, Any]:
    try:
        return runtime.update_recipe(recipe_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@app.post("/api/projects/import")
def import_project(payload: RepoImport) -> dict[str, Any]:
    try:
        return runtime.import_project(payload.repo_url)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("GitHub import failed")
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
        return runtime.start_workspace_run(project_id, yolo=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Project run failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/projects/{project_id}/instructions")
def get_instructions(project_id: str) -> dict[str, Any]:
    try:
        project = runtime.project_store.get_project(project_id)
        if project is None:
            raise ValueError("Project not found.")
        return {"instructions": runtime.project_store.load_instructions(project)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/instructions")
def save_instructions(project_id: str, payload: InstructionsUpdate) -> dict[str, Any]:
    try:
        project = runtime.project_store.get_project(project_id)
        if project is None:
            raise ValueError("Project not found.")
        runtime.project_store.save_instructions(project, payload.instructions)
        return {"instructions": runtime.project_store.load_instructions(project)}
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/instructions/yolo")
def yolo_instructions(project_id: str) -> dict[str, Any]:
    try:
        return runtime.start_workspace_run(project_id, yolo=True)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("YOLO instructions failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/projects/{project_id}/improve")
def improve_project(project_id: str) -> dict[str, Any]:
    try:
        return runtime.project_agent.run_improvement(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Improvement run failed")
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


@app.delete("/api/projects/{project_id}")
def delete_project(project_id: str) -> dict[str, Any]:
    try:
        return runtime.delete_project(project_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Project delete failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.delete("/api/ideas/{idea_id}")
def delete_idea(idea_id: str) -> dict[str, Any]:
    try:
        return runtime.delete_idea(idea_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Idea delete failed")
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/lanes")
def get_lanes() -> dict[str, Any]:
    return {"lanes": get_lanes_config()}


@app.put("/api/lanes")
def put_lanes(payload: LanesUpdate) -> dict[str, Any]:
    raw = [item.model_dump() for item in payload.lanes]
    saved = save_lanes_config(raw)
    return {"lanes": saved}


@app.post("/api/heartbeat")
def update_heartbeat(payload: HeartbeatUpdate) -> dict[str, Any]:
    runtime.settings.heartbeat_seconds = payload.heartbeat_seconds
    return {"heartbeat_seconds": runtime.settings.heartbeat_seconds}
