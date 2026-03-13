from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import shutil
import subprocess
from hashlib import sha1
from io import BytesIO
from pathlib import Path
from typing import Any, Iterable, Literal

SourceType = Literal["bucket", "github"]
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
    instructions_used: str | None = None
    files_considered: int = 0
    chunk_count: int = 0
    skipped_files: int = 0
    llm_summary: str | None = None


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
    source_type: SourceType = "bucket"
    source_repo_url: str | None = None


def _project_root() -> Path:
    """Project root (directory containing app/). Resolves paths regardless of cwd."""
    return Path(__file__).resolve().parent.parent


class ActiveProjectStore:
    def __init__(
        self,
        manifest_path: str = "data/active_projects.json",
        projects_root: str = "data/projects",
    ) -> None:
        root = _project_root()
        self.manifest_path = root / manifest_path
        self.projects_root = root / projects_root
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

    def create_project_from_github(self, repo_url: str) -> ActiveProject:
        """Clone a GitHub repo and create an ActiveProject (source_type=github)."""
        normalized = (repo_url or "").strip().rstrip("/")
        if not re.match(r"^https://github\.com/[^/]+/[^/]+(\.git)?$", normalized):
            raise ValueError("Only https://github.com/owner/repo URLs are allowed.")
        parts = normalized.replace(".git", "").rstrip("/").split("/")
        owner, repo = parts[-2], parts[-1]
        slug_base = _slugify(repo)
        existing_slugs = {p.slug for p in self._load_manifest()}
        slug = slug_base
        suffix = 2
        while slug in existing_slugs:
            slug = f"{slug_base}-{suffix}"
            suffix += 1
        project_id = sha1(normalized.encode("utf-8")).hexdigest()[:16]
        workspace = self.projects_root / slug
        if workspace.exists():
            raise ValueError(f"Workspace already exists: {slug}")
        try:
            subprocess.run(
                ["git", "clone", "--depth", "1", normalized, str(workspace)],
                check=True,
                capture_output=True,
                timeout=120,
                cwd=str(self.projects_root),
            )
        except subprocess.CalledProcessError as e:
            raise ValueError(f"Git clone failed: {e.stderr.decode('utf-8', errors='replace') or 'unknown error'}") from e
        except FileNotFoundError:
            raise ValueError("Git is not installed or not on PATH.") from None

        source_description = ""
        readme_candidates = [workspace / "README.md", workspace / "Readme.md", workspace / "README.MD"]
        for readme in readme_candidates:
            if readme.exists():
                try:
                    source_description = readme.read_text(encoding="utf-8", errors="replace").strip()[:2000]
                    if "\n\n" in source_description:
                        source_description = source_description.split("\n\n")[0].strip()
                except Exception:
                    pass
                break

        run_cmd = "uvicorn app.main:app --reload"
        test_cmd = "pytest -q"
        if (workspace / "package.json").exists():
            try:
                pkg = json.loads((workspace / "package.json").read_text(encoding="utf-8"))
                scripts = pkg.get("scripts") or {}
                run_cmd = scripts.get("start") or run_cmd
                test_cmd = scripts.get("test") or test_cmd
            except Exception:
                pass
        elif (workspace / "requirements.txt").exists():
            run_cmd = "python -m uvicorn app.main:app --reload"
            test_cmd = "pytest -q"

        now = datetime.now(timezone.utc).isoformat()
        project = ActiveProject(
            id=project_id,
            title=repo,
            source_title=repo,
            source_description=source_description or f"Imported from {normalized}",
            source_created_at=now,
            slug=slug,
            target_score=95,
            auto_run=False,
            run_command=run_cmd,
            test_command=test_cmd,
            source_type="github",
            source_repo_url=normalized,
        )
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

    def instructions_path(self, project: ActiveProject) -> Path:
        return self.workspace_path(project) / "instructions.txt"

    def load_instructions(self, project: ActiveProject) -> str:
        path = self.instructions_path(project)
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8", errors="replace").strip()
        except Exception:
            return ""

    def save_instructions(self, project: ActiveProject, text: str) -> None:
        path = self.instructions_path(project)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text((text or "").strip(), encoding="utf-8")

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
        # Normalize: stored paths are often "artifacts/foo.log"; URL can duplicate "artifacts/".
        # Resolve under artifacts dir so "artifacts/import-check.log" and "import-check.log" both work.
        name = relative_name.strip()
        if name.startswith("artifacts/"):
            name = name[len("artifacts/") :].lstrip("/")
        if ".." in name or name.startswith("/"):
            raise ValueError("Invalid artifact path.")
        base = self.artifacts_dir(project).resolve()
        candidate = (base / name).resolve()
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
        attempts = self.recent_attempts(project, attempt_limit)
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
            "recent_attempts": [attempt.model_dump() for attempt in attempts],
            "latest_attempt": attempts[0].model_dump() if attempts else None,
            "source_type": project.source_type,
            "source_repo_url": project.source_repo_url,
            "instructions": self.load_instructions(project) if project.source_type == "github" else "",
        }
