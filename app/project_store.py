from __future__ import annotations

from hashlib import sha1
from io import BytesIO
import json
from pathlib import Path
import re
import shutil
from typing import Any, Iterable, Literal
from zipfile import ZIP_DEFLATED, ZipFile

from pydantic import BaseModel, Field

from app.bucket import ProjectIdea

SupportedLane = Literal[
    "ops-copilot",
    "intake-approval",
    "reporting-dashboard",
    "unsupported",
]
ProjectStage = Literal[
    "qualified",
    "scaffolded",
    "building",
    "validating",
    "usable_mvp",
    "stalled",
    "completed",
]
ValidationStatus = Literal["unknown", "passed", "failed", "deferred"]
SeedStatus = Literal["unknown", "loaded", "missing"]


def idea_id_for_project(project: ProjectIdea) -> str:
    return idea_id_from_parts(project.title, project.created_at)


def idea_id_from_parts(title: str, created_at: str) -> str:
    payload = f"{created_at}|{title}".encode("utf-8")
    return sha1(payload).hexdigest()[:16]


def fingerprint_for_text(*parts: str) -> str:
    return sha1("||".join(parts).encode("utf-8")).hexdigest()[:16]


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug or "project"


class RefCriterion(BaseModel):
    name: str
    weight: int = Field(ge=1, le=100)
    description: str


class RefRubric(BaseModel):
    summary: str = ""
    criteria: list[RefCriterion] = Field(default_factory=list)
    scoring_notes: str = ""


class ProductBrief(BaseModel):
    lane: SupportedLane = "unsupported"
    title: str = ""
    opportunity_summary: str = ""
    target_user: str = ""
    job_to_be_done: str = ""
    manual_workaround: str = ""
    pain_severity: str = ""
    roi: str = ""
    must_have_flow: str = ""
    icp: str = ""
    problem: str = ""
    success_metric: str = ""
    required_entities: list[str] = Field(default_factory=list)
    must_have_screens: list[str] = Field(default_factory=list)
    must_have_actions: list[str] = Field(default_factory=list)
    demo_scenario: str = ""
    acceptance_criteria: list[str] = Field(default_factory=list)


class HardGateResult(BaseModel):
    key: str
    label: str
    passed: bool
    details: str = ""
    artifact_path: str | None = None


class ValidationSummary(BaseModel):
    run_at: str | None = None
    status: ValidationStatus = "unknown"
    summary: str = ""
    hard_gate_results: list[HardGateResult] = Field(default_factory=list)
    passed_checks: list[str] = Field(default_factory=list)
    failing_checks: list[str] = Field(default_factory=list)
    next_task: str | None = None
    artifact_paths: dict[str, str] = Field(default_factory=dict)


class ProjectFileOperation(BaseModel):
    path: str
    action: Literal["create", "update", "delete"]
    content: str | None = None


class ProjectAttempt(BaseModel):
    attempt_key: str
    stage_name: str = "run"
    builder_name: str
    summary: str
    changed_files: list[str] = Field(default_factory=list)
    baseline_score: int = Field(ge=0, le=100)
    candidate_score: int | None = Field(default=None, ge=0, le=100)
    decision: str
    reason: str
    validation_status: ValidationStatus = "unknown"
    failed_checks: list[str] = Field(default_factory=list)
    next_task: str | None = None
    timestamp: str


class ActiveProject(BaseModel):
    id: str
    title: str
    source_title: str
    source_description: str
    source_created_at: str
    slug: str
    status: Literal["active", "completed"] = "active"
    auto_run: bool = False
    target_score: int = Field(default=95, ge=1, le=100)
    current_score: int = Field(default=0, ge=0, le=100)
    stack_name: str = "FastAPI + Jinja + HTMX + SQLite + SQLModel + pytest"
    last_cycle_at: str | None = None
    last_accepted_summary: str | None = None
    ref_rubric: RefRubric = Field(default_factory=RefRubric)
    lane: SupportedLane = "unsupported"
    stage: ProjectStage = "qualified"
    template_id: str = ""
    product_brief: ProductBrief = Field(default_factory=ProductBrief)
    run_command: str = "uvicorn app.main:app --reload"
    test_command: str = "pytest -q"
    seed_status: SeedStatus = "unknown"
    validation_status: ValidationStatus = "unknown"
    hard_gate_results: list[HardGateResult] = Field(default_factory=list)
    usable_mvp_at: str | None = None
    stalled_reason: str | None = None
    validation_artifacts: dict[str, str] = Field(default_factory=dict)


class ActiveProjectStore:
    def __init__(
        self,
        manifest_path: str = "data/active_projects.json",
        projects_root: str = "data/projects",
    ) -> None:
        self.manifest_path = Path(manifest_path)
        self.projects_root = Path(projects_root)
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        self.projects_root.mkdir(parents=True, exist_ok=True)
        if not self.manifest_path.exists():
            self.manifest_path.write_text(json.dumps({"projects": []}, indent=2), encoding="utf-8")

    def _normalize_project(self, project: ActiveProject) -> ActiveProject:
        if project.product_brief.title == "":
            project.product_brief.title = project.title
        if project.product_brief.opportunity_summary == "":
            project.product_brief.opportunity_summary = project.source_description
        if project.lane == "unsupported" and project.product_brief.lane != "unsupported":
            project.lane = project.product_brief.lane
        if not project.template_id and project.lane != "unsupported":
            project.template_id = f"{project.lane}-v1"
        if not project.run_command:
            project.run_command = "uvicorn app.main:app --reload"
        if not project.test_command:
            project.test_command = "pytest -q"
        return project

    def _load_manifest(self) -> list[ActiveProject]:
        try:
            payload = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {"projects": []}
        raw_projects = payload.get("projects", [])
        if not isinstance(raw_projects, list):
            raw_projects = []
        projects: list[ActiveProject] = []
        for item in raw_projects:
            try:
                projects.append(self._normalize_project(ActiveProject.model_validate(item)))
            except Exception:
                continue
        return projects

    def _save_manifest(self, projects: Iterable[ActiveProject]) -> None:
        payload = {"projects": [self._normalize_project(project).model_dump() for project in projects]}
        self.manifest_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def list_projects(self) -> list[ActiveProject]:
        return self._load_manifest()

    def get_project(self, project_id: str) -> ActiveProject | None:
        for project in self._load_manifest():
            if project.id == project_id:
                return project
        return None

    def save_project(self, project: ActiveProject) -> ActiveProject:
        project = self._normalize_project(project)
        projects = self._load_manifest()
        updated = False
        for index, existing in enumerate(projects):
            if existing.id == project.id:
                projects[index] = project
                updated = True
                break
        if not updated:
            projects.append(project)
        self._save_manifest(projects)
        return project

    def find_by_idea(self, idea: ProjectIdea) -> ActiveProject | None:
        idea_id = idea_id_for_project(idea)
        for project in self._load_manifest():
            if idea_id_from_parts(project.source_title, project.source_created_at) == idea_id:
                return project
        return None

    def create_project(self, idea: ProjectIdea, target_score: int = 95) -> ActiveProject:
        existing = self.find_by_idea(idea)
        if existing is not None:
            raise ValueError("That project idea has already been promoted.")

        existing_slugs = {project.slug for project in self._load_manifest()}
        base_slug = _slugify(idea.title)
        slug = base_slug
        suffix = 2
        while slug in existing_slugs:
            slug = f"{base_slug}-{suffix}"
            suffix += 1

        project = ActiveProject(
            id=idea_id_for_project(idea),
            title=idea.title,
            source_title=idea.title,
            source_description=idea.description,
            source_created_at=idea.created_at,
            slug=slug,
            target_score=target_score,
            auto_run=True,
        )
        workspace = self.workspace_path(project)
        workspace.mkdir(parents=True, exist_ok=True)
        self.ensure_project_files(project)
        self.save_project(project)
        return project

    def workspace_path(self, project: ActiveProject) -> Path:
        return self.projects_root / project.slug

    def records_path(self, project: ActiveProject) -> Path:
        return self.workspace_path(project) / "records.json"

    def product_brief_path(self, project: ActiveProject) -> Path:
        return self.workspace_path(project) / "PRODUCT_BRIEF.json"

    def validation_path(self, project: ActiveProject) -> Path:
        return self.workspace_path(project) / "VALIDATION.json"

    def artifacts_dir(self, project: ActiveProject) -> Path:
        return self.workspace_path(project) / "artifacts"

    def ensure_project_files(self, project: ActiveProject) -> None:
        workspace = self.workspace_path(project)
        workspace.mkdir(parents=True, exist_ok=True)
        self.artifacts_dir(project).mkdir(parents=True, exist_ok=True)
        if not self.records_path(project).exists():
            self.records_path(project).write_text(json.dumps({"attempts": []}, indent=2), encoding="utf-8")
        if not self.product_brief_path(project).exists():
            self.product_brief_path(project).write_text(
                json.dumps(project.product_brief.model_dump(), indent=2),
                encoding="utf-8",
            )
        if not self.validation_path(project).exists():
            self.validation_path(project).write_text(
                json.dumps(ValidationSummary().model_dump(), indent=2),
                encoding="utf-8",
            )

    def write_product_brief(self, project: ActiveProject, brief: ProductBrief) -> None:
        self.ensure_project_files(project)
        self.product_brief_path(project).write_text(
            json.dumps(brief.model_dump(), indent=2),
            encoding="utf-8",
        )

    def load_product_brief(self, project: ActiveProject) -> ProductBrief:
        self.ensure_project_files(project)
        try:
            payload = json.loads(self.product_brief_path(project).read_text(encoding="utf-8"))
            return ProductBrief.model_validate(payload)
        except Exception:
            return project.product_brief

    def write_validation_summary(self, project: ActiveProject, summary: ValidationSummary) -> None:
        self.ensure_project_files(project)
        self.validation_path(project).write_text(
            json.dumps(summary.model_dump(), indent=2),
            encoding="utf-8",
        )

    def load_validation_summary(self, project: ActiveProject) -> ValidationSummary:
        self.ensure_project_files(project)
        try:
            payload = json.loads(self.validation_path(project).read_text(encoding="utf-8"))
            return ValidationSummary.model_validate(payload)
        except Exception:
            return ValidationSummary()

    def write_artifact(self, project: ActiveProject, name: str, content: str) -> str:
        self.ensure_project_files(project)
        path = self.artifacts_dir(project) / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path.relative_to(self.workspace_path(project)).as_posix()

    def artifact_path(self, project: ActiveProject, relative_name: str) -> Path:
        base = self.workspace_path(project).resolve()
        candidate = (base / relative_name).resolve()
        try:
            candidate.relative_to(base)
        except ValueError as exc:
            raise ValueError("Invalid artifact path.") from exc
        return candidate

    def build_project_archive(self, project: ActiveProject) -> bytes:
        workspace = self.workspace_path(project)
        if not workspace.exists():
            raise ValueError("Project workspace not found.")

        buffer = BytesIO()
        archive_root = Path(project.slug)

        with ZipFile(buffer, "w", compression=ZIP_DEFLATED) as archive:
            for path in sorted(workspace.rglob("*")):
                if not path.is_file():
                    continue
                relative_path = path.relative_to(workspace)
                archive.write(path, arcname=(archive_root / relative_path).as_posix())

        return buffer.getvalue()

    def load_attempts(self, project: ActiveProject) -> list[ProjectAttempt]:
        self.ensure_project_files(project)
        try:
            payload = json.loads(self.records_path(project).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {"attempts": []}
        raw_attempts = payload.get("attempts", [])
        if not isinstance(raw_attempts, list):
            raw_attempts = []
        attempts: list[ProjectAttempt] = []
        for item in raw_attempts:
            try:
                attempts.append(ProjectAttempt.model_validate(item))
            except Exception:
                continue
        return attempts

    def append_attempt(self, project: ActiveProject, attempt: ProjectAttempt) -> None:
        attempts = self.load_attempts(project)
        attempts.append(attempt)
        payload = {"attempts": [item.model_dump() for item in attempts]}
        self.records_path(project).write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def recent_attempts(self, project: ActiveProject, limit: int = 5) -> list[ProjectAttempt]:
        attempts = self.load_attempts(project)
        return list(reversed(attempts[-limit:]))

    def known_attempt_fingerprints(self, project: ActiveProject) -> set[str]:
        return {attempt.attempt_key for attempt in self.load_attempts(project)}

    def known_attempt_summaries(self, project: ActiveProject) -> set[str]:
        return {attempt.summary.strip().lower() for attempt in self.load_attempts(project)}

    def replace_workspace_files(
        self,
        project: ActiveProject,
        files: dict[str, str],
        *,
        preserve_records: bool = True,
    ) -> list[str]:
        workspace = self.workspace_path(project)
        workspace.mkdir(parents=True, exist_ok=True)

        preserve_names = {"records.json"} if preserve_records else set()
        for path in list(workspace.iterdir()):
            if path.name in preserve_names:
                continue
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()

        changed_files: list[str] = []
        for relative_name, content in files.items():
            destination = workspace / relative_name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(content, encoding="utf-8")
            changed_files.append(relative_name.replace("\\", "/"))

        self.ensure_project_files(project)
        return changed_files

    @staticmethod
    def apply_file_operations(
        base_dir: Path,
        operations: Iterable[ProjectFileOperation],
    ) -> list[str]:
        resolved_base = base_dir.resolve()
        touched_files: list[str] = []

        for operation in operations:
            relative_path = Path(operation.path)
            if relative_path.is_absolute() or ".." in relative_path.parts:
                raise ValueError(f"Invalid project file path: {operation.path}")

            destination = (resolved_base / relative_path).resolve()
            try:
                destination.relative_to(resolved_base)
            except ValueError as exc:
                raise ValueError(f"Invalid project file path: {operation.path}") from exc

            if operation.action == "delete":
                if destination.exists():
                    if destination.is_dir():
                        shutil.rmtree(destination)
                    else:
                        destination.unlink()
                    touched_files.append(relative_path.as_posix())
                continue

            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(operation.content or "", encoding="utf-8")
            touched_files.append(relative_path.as_posix())

        return touched_files

    @staticmethod
    def workspace_context(
        workspace: Path,
        max_files: int = 24,
        max_chars_per_file: int = 6000,
    ) -> str:
        if not workspace.exists():
            return "Workspace is empty."

        files: list[Path] = []
        for path in sorted(workspace.rglob("*")):
            if not path.is_file():
                continue
            if path.name in {"records.json", "VALIDATION.json"}:
                continue
            if any(part.startswith(".git") for part in path.parts):
                continue
            files.append(path)
            if len(files) >= max_files:
                break

        if not files:
            return "Workspace is empty."

        lines = ["Workspace files:"]
        for path in files:
            relative = path.relative_to(workspace).as_posix()
            try:
                content = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                content = "<binary or unsupported text content>"
            if len(content) > max_chars_per_file:
                content = content[:max_chars_per_file].rstrip() + "\n...<truncated>"
            lines.append(f"\n## {relative}\n{content}")

        return "\n".join(lines)

    def project_summary(self, project: ActiveProject, attempt_limit: int = 5) -> dict[str, object]:
        project = self._normalize_project(project)
        validation = self.load_validation_summary(project)
        return {
            "id": project.id,
            "title": project.title,
            "source_title": project.source_title,
            "source_description": project.source_description,
            "source_created_at": project.source_created_at,
            "slug": project.slug,
            "status": project.status,
            "auto_run": project.auto_run,
            "target_score": project.target_score,
            "current_score": project.current_score,
            "stack_name": project.stack_name,
            "last_cycle_at": project.last_cycle_at,
            "last_accepted_summary": project.last_accepted_summary,
            "lane": project.lane,
            "stage": project.stage,
            "template_id": project.template_id,
            "product_brief": project.product_brief.model_dump(),
            "run_command": project.run_command,
            "test_command": project.test_command,
            "seed_status": project.seed_status,
            "validation_status": project.validation_status,
            "hard_gate_results": [result.model_dump() for result in project.hard_gate_results],
            "usable_mvp_at": project.usable_mvp_at,
            "stalled_reason": project.stalled_reason,
            "validation_summary": validation.model_dump(),
            "validation_artifacts": project.validation_artifacts,
            "workspace_path": self.workspace_path(project).as_posix(),
            "recent_attempts": [attempt.model_dump() for attempt in self.recent_attempts(project, attempt_limit)],
        }
