from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sqlite3
import sys
from threading import Lock
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.bucket import BucketStore, ProjectIdea
from app.project_store import ActiveProject, ActiveProjectStore, idea_id_for_project

WorkspaceStatus = Literal["active", "stalled", "completed", "archived"]
RunStatus = Literal["queued", "running", "awaiting_approval", "approved", "rejected", "completed", "failed", "deferred"]
ApprovalStatus = Literal["pending", "approved", "rejected"]
SkillPermissionLevel = Literal["safe", "approval_required", "dangerous"]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _expand_configured_path(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value)))


def default_blip_home() -> Path:
    configured = os.environ.get("BLIP_HOME")
    if configured:
        path = _expand_configured_path(configured)
        return path if path.is_absolute() else (Path.cwd() / path)
    if os.name == "nt":
        local_app_data = os.environ.get("LOCALAPPDATA")
        base = _expand_configured_path(local_app_data) if local_app_data else (Path.home() / "AppData" / "Local")
        return base / "Blip-AI"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Blip-AI"
    return Path.home() / ".local" / "share" / "blip-ai"


class MissionSpec(BaseModel):
    objective: str
    summary: str = ""
    success_criteria: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    recipe_id: str
    source_type: str = ""
    manual_instructions: str = ""
    digest_summary: str = ""
    product_brief: dict[str, Any] = Field(default_factory=dict)
    digest: dict[str, Any] = Field(default_factory=dict)
    validation: dict[str, Any] = Field(default_factory=dict)


class WorkspaceRecord(BaseModel):
    id: str
    project_id: str
    title: str
    slug: str
    recipe_id: str
    source_type: str
    source_repo_url: str | None = None
    lane: str = "unsupported"
    status: WorkspaceStatus = "active"
    workspace_path: str
    default_branch: str = "main"
    current_branch: str = "main"
    current_score: int = 0
    target_score: int = 95
    last_digest_summary: str = ""
    last_run_id: str | None = None
    pending_approval_id: str | None = None
    mission_summary: str = ""
    auto_run: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class RunStepRecord(BaseModel):
    id: str
    run_id: str
    name: str
    status: str
    summary: str = ""
    prompt_excerpt: str = ""
    logs: str = ""
    artifact_paths: list[str] = Field(default_factory=list)
    started_at: str
    completed_at: str | None = None


class RunRecord(BaseModel):
    id: str
    workspace_id: str
    project_id: str
    recipe_id: str
    trigger: str = "manual"
    status: RunStatus
    branch_name: str = ""
    source_branch: str = ""
    worktree_path: str = ""
    summary: str = ""
    error: str = ""
    retryable: bool = False
    mission_spec: MissionSpec
    result_payload: dict[str, Any] = Field(default_factory=dict)
    project_snapshot: dict[str, Any] = Field(default_factory=dict)
    legacy_attempt_key: str | None = None
    created_at: str
    updated_at: str
    completed_at: str | None = None


class ApprovalRequestRecord(BaseModel):
    id: str
    workspace_id: str
    project_id: str
    run_id: str
    status: ApprovalStatus = "pending"
    summary: str = ""
    diff_summary: str = ""
    commit_hash: str = ""
    changed_files: list[str] = Field(default_factory=list)
    created_at: str
    resolved_at: str | None = None


class SkillRecord(BaseModel):
    id: str
    name: str
    description: str = ""
    capabilities: list[str] = Field(default_factory=list)
    input_schema: dict[str, Any] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    permission_level: SkillPermissionLevel = "safe"
    enabled: bool = True
    built_in: bool = True
    created_at: str
    updated_at: str


class RecipeRecord(BaseModel):
    id: str
    name: str
    description: str = ""
    definition: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    built_in: bool = True
    locked: bool = True
    created_at: str
    updated_at: str


class IdeaRecord(BaseModel):
    id: str
    title: str
    description: str
    created_at: str
    active_project_id: str | None = None
    updated_at: str


def builtin_skills() -> list[SkillRecord]:
    now = _now_iso()
    return [
        SkillRecord(
            id="file-ops",
            name="File Operations",
            description="Read and write repository files inside an approved workspace.",
            capabilities=["read_file", "write_file", "delete_file"],
            input_schema={"type": "object", "properties": {"path": {"type": "string"}}},
            output_schema={"type": "object", "properties": {"changed_files": {"type": "array"}}},
            permission_level="safe",
            built_in=True,
            enabled=True,
            created_at=now,
            updated_at=now,
        ),
        SkillRecord(
            id="git-ops",
            name="Git Operations",
            description="Clone repos, create run branches, inspect diffs, and commit staged work.",
            capabilities=["clone", "worktree", "status", "diff", "commit", "merge"],
            permission_level="approval_required",
            built_in=True,
            enabled=True,
            created_at=now,
            updated_at=now,
        ),
        SkillRecord(
            id="shell-runner",
            name="Safe Shell Runner",
            description="Run bounded local commands for tests and validation.",
            capabilities=["shell"],
            permission_level="approval_required",
            built_in=True,
            enabled=True,
            created_at=now,
            updated_at=now,
        ),
        SkillRecord(
            id="repo-digest",
            name="Repo Digest",
            description="Summarize a repository and produce targeted improvement plans.",
            capabilities=["repo_digest"],
            permission_level="safe",
            built_in=True,
            enabled=True,
            created_at=now,
            updated_at=now,
        ),
        SkillRecord(
            id="validation-runner",
            name="Validation Runner",
            description="Execute deterministic validation and capture artifacts.",
            capabilities=["validate", "test", "artifacts"],
            permission_level="safe",
            built_in=True,
            enabled=True,
            created_at=now,
            updated_at=now,
        ),
        SkillRecord(
            id="browser-docs",
            name="Browser and Docs",
            description="Fetch documentation and web pages for repo-aware improvements.",
            capabilities=["browser", "http"],
            permission_level="approval_required",
            built_in=True,
            enabled=False,
            created_at=now,
            updated_at=now,
        ),
    ]


def builtin_recipes() -> list[RecipeRecord]:
    now = _now_iso()
    return [
        RecipeRecord(
            id="lane-mvp-factory",
            name="Lane MVP Factory",
            description="Qualifier -> planner -> scaffold -> validate -> reviewer for supported B2B MVP lanes.",
            definition={
                "stages": [
                    {"id": "supervisor", "agent": "Supervisor", "skills": ["git-ops"]},
                    {"id": "planner", "agent": "Planner", "skills": ["repo-digest"]},
                    {"id": "scaffolder", "agent": "Executor", "skills": ["file-ops", "git-ops"]},
                    {"id": "validator", "agent": "Validator", "skills": ["shell-runner", "validation-runner"]},
                    {"id": "reviewer", "agent": "Reviewer", "skills": ["git-ops"], "approval_required": True},
                ]
            },
            enabled=True,
            built_in=True,
            locked=True,
            created_at=now,
            updated_at=now,
        ),
        RecipeRecord(
            id="repo-improver",
            name="Repo Improver",
            description="Digest -> mission -> targeted execution -> validate -> approval for imported repos.",
            definition={
                "stages": [
                    {"id": "supervisor", "agent": "Supervisor", "skills": ["git-ops"]},
                    {"id": "planner", "agent": "Planner", "skills": ["repo-digest"]},
                    {"id": "executor", "agent": "Executor", "skills": ["file-ops", "git-ops", "shell-runner"]},
                    {"id": "validator", "agent": "Validator", "skills": ["shell-runner", "validation-runner"]},
                    {"id": "reviewer", "agent": "Reviewer", "skills": ["git-ops"], "approval_required": True},
                ]
            },
            enabled=True,
            built_in=True,
            locked=True,
            created_at=now,
            updated_at=now,
        ),
    ]


class PlatformStore:
    def __init__(
        self,
        *,
        blip_home: str | None = None,
        project_store: ActiveProjectStore,
        bucket: BucketStore,
    ) -> None:
        configured_home = _expand_configured_path(blip_home) if blip_home else default_blip_home()
        self.blip_home = configured_home if configured_home.is_absolute() else (Path.cwd() / configured_home)
        self.db_path = self.blip_home / "blip.db"
        self.workspaces_root = self.blip_home / "workspaces"
        self.artifacts_root = self.blip_home / "artifacts"
        self.skills_root = self.blip_home / "skills"
        self.project_store = project_store
        self.bucket = bucket
        self._lock = Lock()

        self.blip_home.mkdir(parents=True, exist_ok=True)
        self.workspaces_root.mkdir(parents=True, exist_ok=True)
        self.artifacts_root.mkdir(parents=True, exist_ok=True)
        self.skills_root.mkdir(parents=True, exist_ok=True)

        self._ensure_schema()
        self._seed_defaults()
        self.sync_legacy_state()

    @contextmanager
    def _connect(self) -> Any:
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _encode(value: Any) -> str:
        return json.dumps(value or {}, indent=2, sort_keys=True)

    @staticmethod
    def _decode_dict(value: str | None) -> dict[str, Any]:
        if not value:
            return {}
        try:
            data = json.loads(value)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    @staticmethod
    def _decode_list(value: str | None) -> list[Any]:
        if not value:
            return []
        try:
            data = json.loads(value)
            return data if isinstance(data, list) else []
        except json.JSONDecodeError:
            return []

    def _ensure_schema(self) -> None:
        with self._lock, self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS workspaces (
                    id TEXT PRIMARY KEY,
                    project_id TEXT NOT NULL,
                    title TEXT NOT NULL,
                    slug TEXT NOT NULL,
                    recipe_id TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_repo_url TEXT,
                    lane TEXT NOT NULL,
                    status TEXT NOT NULL,
                    workspace_path TEXT NOT NULL,
                    default_branch TEXT NOT NULL,
                    current_branch TEXT NOT NULL,
                    current_score INTEGER NOT NULL,
                    target_score INTEGER NOT NULL,
                    last_digest_summary TEXT NOT NULL,
                    last_run_id TEXT,
                    pending_approval_id TEXT,
                    mission_summary TEXT NOT NULL,
                    auto_run INTEGER NOT NULL DEFAULT 0,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    recipe_id TEXT NOT NULL,
                    trigger_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    branch_name TEXT NOT NULL,
                    source_branch TEXT NOT NULL,
                    worktree_path TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    error TEXT NOT NULL,
                    retryable INTEGER NOT NULL DEFAULT 0,
                    mission_spec_json TEXT NOT NULL,
                    result_payload_json TEXT NOT NULL,
                    project_snapshot_json TEXT NOT NULL,
                    legacy_attempt_key TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_runs_workspace ON runs(workspace_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS run_steps (
                    id TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL,
                    name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    prompt_excerpt TEXT NOT NULL,
                    logs TEXT NOT NULL,
                    artifact_paths_json TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_run_steps_run ON run_steps(run_id, started_at ASC);
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    workspace_id TEXT NOT NULL,
                    project_id TEXT NOT NULL,
                    run_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    diff_summary TEXT NOT NULL,
                    commit_hash TEXT NOT NULL,
                    changed_files_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    resolved_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status, created_at DESC);
                CREATE TABLE IF NOT EXISTS skills (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    capabilities_json TEXT NOT NULL,
                    input_schema_json TEXT NOT NULL,
                    output_schema_json TEXT NOT NULL,
                    permission_level TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    built_in INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS recipes (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL,
                    definition_json TEXT NOT NULL,
                    enabled INTEGER NOT NULL DEFAULT 1,
                    built_in INTEGER NOT NULL DEFAULT 1,
                    locked INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS ideas (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    active_project_id TEXT,
                    updated_at TEXT NOT NULL
                );
                """
            )

    def _seed_defaults(self) -> None:
        with self._lock, self._connect() as conn:
            for skill in builtin_skills():
                conn.execute(
                    """
                    INSERT INTO skills (
                        id, name, description, capabilities_json, input_schema_json, output_schema_json,
                        permission_level, enabled, built_in, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO NOTHING
                    """,
                    (
                        skill.id,
                        skill.name,
                        skill.description,
                        self._encode(skill.capabilities),
                        self._encode(skill.input_schema),
                        self._encode(skill.output_schema),
                        skill.permission_level,
                        int(skill.enabled),
                        int(skill.built_in),
                        skill.created_at,
                        skill.updated_at,
                    ),
                )
            for recipe in builtin_recipes():
                conn.execute(
                    """
                    INSERT INTO recipes (
                        id, name, description, definition_json, enabled, built_in, locked, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO NOTHING
                    """,
                    (
                        recipe.id,
                        recipe.name,
                        recipe.description,
                        self._encode(recipe.definition),
                        int(recipe.enabled),
                        int(recipe.built_in),
                        int(recipe.locked),
                        recipe.created_at,
                        recipe.updated_at,
                    ),
                )

    def sync_legacy_state(self) -> None:
        for project in self.project_store.list_projects():
            self.upsert_workspace_from_project(project)
            for attempt in self.project_store.load_attempts(project):
                self._upsert_legacy_run(project, attempt.model_dump())

        active_by_idea = {
            idea_id_for_project(ProjectIdea(title=project.source_title, description=project.source_description, created_at=project.source_created_at)): project.id
            for project in self.project_store.list_projects()
        }
        for idea in self.bucket.list_projects():
            self.upsert_idea(idea, active_project_id=active_by_idea.get(idea_id_for_project(idea)))

    def workspace_root_for_run(self, run_id: str) -> Path:
        root = self.artifacts_root / "runs" / run_id
        root.mkdir(parents=True, exist_ok=True)
        return root

    def upsert_workspace_from_project(self, project: ActiveProject) -> WorkspaceRecord:
        recipe_id = "repo-improver" if project.source_type == "github" else "lane-mvp-factory"
        summary = project.repo_digest_summary if project.source_type == "github" else (
            project.product_brief.must_have_flow or project.product_brief.opportunity_summary or project.source_description
        )
        status: WorkspaceStatus = "completed" if project.status == "completed" else (
            "stalled" if project.stage == "stalled" else "active"
        )
        now = _now_iso()
        workspace = WorkspaceRecord(
            id=project.id,
            project_id=project.id,
            title=project.title,
            slug=project.slug,
            recipe_id=recipe_id,
            source_type=project.source_type,
            source_repo_url=project.source_repo_url,
            lane=project.lane,
            status=status,
            workspace_path=self.project_store.workspace_path(project).as_posix(),
            default_branch=self._detect_default_branch(self.project_store.workspace_path(project)),
            current_branch=self._detect_default_branch(self.project_store.workspace_path(project)),
            current_score=project.current_score,
            target_score=project.target_score,
            last_digest_summary=project.repo_digest_summary,
            mission_summary=summary,
            auto_run=project.auto_run,
            metadata={
                "stage": project.stage,
                "validation_status": project.validation_status,
                "last_cycle_at": project.last_cycle_at,
                "last_accepted_summary": project.last_accepted_summary,
            },
            created_at=project.source_created_at,
            updated_at=now,
        )
        with self._lock, self._connect() as conn:
            existing = conn.execute("SELECT created_at, pending_approval_id, last_run_id FROM workspaces WHERE id = ?", (workspace.id,)).fetchone()
            conn.execute(
                """
                INSERT INTO workspaces (
                    id, project_id, title, slug, recipe_id, source_type, source_repo_url, lane, status,
                    workspace_path, default_branch, current_branch, current_score, target_score,
                    last_digest_summary, last_run_id, pending_approval_id, mission_summary, auto_run,
                    metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    slug=excluded.slug,
                    recipe_id=excluded.recipe_id,
                    source_type=excluded.source_type,
                    source_repo_url=excluded.source_repo_url,
                    lane=excluded.lane,
                    status=excluded.status,
                    workspace_path=excluded.workspace_path,
                    default_branch=excluded.default_branch,
                    current_branch=excluded.current_branch,
                    current_score=excluded.current_score,
                    target_score=excluded.target_score,
                    last_digest_summary=excluded.last_digest_summary,
                    mission_summary=excluded.mission_summary,
                    auto_run=excluded.auto_run,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    workspace.id,
                    workspace.project_id,
                    workspace.title,
                    workspace.slug,
                    workspace.recipe_id,
                    workspace.source_type,
                    workspace.source_repo_url,
                    workspace.lane,
                    workspace.status,
                    workspace.workspace_path,
                    workspace.default_branch,
                    workspace.current_branch,
                    workspace.current_score,
                    workspace.target_score,
                    workspace.last_digest_summary,
                    existing["last_run_id"] if existing else None,
                    existing["pending_approval_id"] if existing else None,
                    workspace.mission_summary,
                    int(workspace.auto_run),
                    self._encode(workspace.metadata),
                    existing["created_at"] if existing else workspace.created_at,
                    workspace.updated_at,
                ),
            )
        return self.get_workspace(workspace.id) or workspace

    def _upsert_legacy_run(self, project: ActiveProject, attempt: dict[str, Any]) -> None:
        legacy_key = str(attempt.get("attempt_key", "")).strip()
        if not legacy_key:
            return
        run_id = f"legacy-{project.id}-{legacy_key}"[:120]
        with self._lock, self._connect() as conn:
            existing = conn.execute("SELECT id FROM runs WHERE id = ?", (run_id,)).fetchone()
            if existing:
                return
            mission = MissionSpec(
                objective=attempt.get("summary", "Legacy run"),
                summary=attempt.get("reason", ""),
                success_criteria=[],
                constraints=[],
                recipe_id="repo-improver" if project.source_type == "github" else "lane-mvp-factory",
                source_type=project.source_type,
            )
            status_map = {
                "accepted": "completed",
                "rejected": "failed",
                "skipped_duplicate": "completed",
                "deferred": "deferred",
                "no_change": "completed",
            }
            status = status_map.get(str(attempt.get("decision", "completed")), "completed")
            payload = {
                "decision": attempt.get("decision"),
                "summary": attempt.get("summary"),
                "reason": attempt.get("reason"),
                "changed_files": attempt.get("changed_files", []),
                "baseline_score": attempt.get("baseline_score"),
                "candidate_score": attempt.get("candidate_score"),
            }
            created_at = str(attempt.get("timestamp", _now_iso()))
            conn.execute(
                """
                INSERT INTO runs (
                    id, workspace_id, project_id, recipe_id, trigger_name, status, branch_name, source_branch,
                    worktree_path, summary, error, retryable, mission_spec_json, result_payload_json,
                    project_snapshot_json, legacy_attempt_key, created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    project.id,
                    project.id,
                    "repo-improver" if project.source_type == "github" else "lane-mvp-factory",
                    "legacy_import",
                    status,
                    "",
                    "",
                    self.project_store.workspace_path(project).as_posix(),
                    str(attempt.get("summary", "")).strip(),
                    "",
                    0,
                    self._encode(mission.model_dump()),
                    self._encode(payload),
                    self._encode({"project": self.project_store.project_summary(project)}),
                    legacy_key,
                    created_at,
                    created_at,
                    created_at,
                ),
            )

    def upsert_idea(self, idea: ProjectIdea, *, active_project_id: str | None) -> IdeaRecord:
        now = _now_iso()
        idea_record = IdeaRecord(
            id=idea_id_for_project(idea),
            title=idea.title,
            description=idea.description,
            created_at=idea.created_at,
            active_project_id=active_project_id,
            updated_at=now,
        )
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO ideas (id, title, description, created_at, active_project_id, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    title=excluded.title,
                    description=excluded.description,
                    active_project_id=excluded.active_project_id,
                    updated_at=excluded.updated_at
                """,
                (
                    idea_record.id,
                    idea_record.title,
                    idea_record.description,
                    idea_record.created_at,
                    idea_record.active_project_id,
                    idea_record.updated_at,
                ),
            )
        return idea_record

    @staticmethod
    def _detect_default_branch(workspace_path: Path) -> str:
        try:
            from subprocess import run

            completed = run(
                ["git", "branch", "--show-current"],
                cwd=workspace_path,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            )
            branch = completed.stdout.strip()
            return branch or "main"
        except Exception:
            return "main"

    def _workspace_from_row(self, row: sqlite3.Row) -> WorkspaceRecord:
        return WorkspaceRecord(
            id=row["id"],
            project_id=row["project_id"],
            title=row["title"],
            slug=row["slug"],
            recipe_id=row["recipe_id"],
            source_type=row["source_type"],
            source_repo_url=row["source_repo_url"],
            lane=row["lane"],
            status=row["status"],
            workspace_path=row["workspace_path"],
            default_branch=row["default_branch"],
            current_branch=row["current_branch"],
            current_score=int(row["current_score"]),
            target_score=int(row["target_score"]),
            last_digest_summary=row["last_digest_summary"],
            last_run_id=row["last_run_id"],
            pending_approval_id=row["pending_approval_id"],
            mission_summary=row["mission_summary"],
            auto_run=bool(row["auto_run"]),
            metadata=self._decode_dict(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _run_from_row(self, row: sqlite3.Row) -> RunRecord:
        return RunRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            project_id=row["project_id"],
            recipe_id=row["recipe_id"],
            trigger=row["trigger_name"],
            status=row["status"],
            branch_name=row["branch_name"],
            source_branch=row["source_branch"],
            worktree_path=row["worktree_path"],
            summary=row["summary"],
            error=row["error"],
            retryable=bool(row["retryable"]),
            mission_spec=MissionSpec.model_validate(self._decode_dict(row["mission_spec_json"])),
            result_payload=self._decode_dict(row["result_payload_json"]),
            project_snapshot=self._decode_dict(row["project_snapshot_json"]),
            legacy_attempt_key=row["legacy_attempt_key"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            completed_at=row["completed_at"],
        )

    def _approval_from_row(self, row: sqlite3.Row) -> ApprovalRequestRecord:
        return ApprovalRequestRecord(
            id=row["id"],
            workspace_id=row["workspace_id"],
            project_id=row["project_id"],
            run_id=row["run_id"],
            status=row["status"],
            summary=row["summary"],
            diff_summary=row["diff_summary"],
            commit_hash=row["commit_hash"],
            changed_files=[str(item) for item in self._decode_list(row["changed_files_json"])],
            created_at=row["created_at"],
            resolved_at=row["resolved_at"],
        )

    def _skill_from_row(self, row: sqlite3.Row) -> SkillRecord:
        return SkillRecord(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            capabilities=[str(item) for item in self._decode_list(row["capabilities_json"])],
            input_schema=self._decode_dict(row["input_schema_json"]),
            output_schema=self._decode_dict(row["output_schema_json"]),
            permission_level=row["permission_level"],
            enabled=bool(row["enabled"]),
            built_in=bool(row["built_in"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def _recipe_from_row(self, row: sqlite3.Row) -> RecipeRecord:
        return RecipeRecord(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            definition=self._decode_dict(row["definition_json"]),
            enabled=bool(row["enabled"]),
            built_in=bool(row["built_in"]),
            locked=bool(row["locked"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_workspaces(self) -> list[WorkspaceRecord]:
        self.sync_legacy_state()
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM workspaces ORDER BY updated_at DESC, created_at DESC").fetchall()
        return [self._workspace_from_row(row) for row in rows]

    def get_workspace(self, workspace_id: str) -> WorkspaceRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM workspaces WHERE id = ?", (workspace_id,)).fetchone()
        return self._workspace_from_row(row) if row else None

    def save_workspace(self, workspace: WorkspaceRecord) -> WorkspaceRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO workspaces (
                    id, project_id, title, slug, recipe_id, source_type, source_repo_url, lane, status,
                    workspace_path, default_branch, current_branch, current_score, target_score, last_digest_summary,
                    last_run_id, pending_approval_id, mission_summary, auto_run, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    project_id=excluded.project_id,
                    title=excluded.title,
                    slug=excluded.slug,
                    recipe_id=excluded.recipe_id,
                    source_type=excluded.source_type,
                    source_repo_url=excluded.source_repo_url,
                    lane=excluded.lane,
                    status=excluded.status,
                    workspace_path=excluded.workspace_path,
                    default_branch=excluded.default_branch,
                    current_branch=excluded.current_branch,
                    current_score=excluded.current_score,
                    target_score=excluded.target_score,
                    last_digest_summary=excluded.last_digest_summary,
                    last_run_id=excluded.last_run_id,
                    pending_approval_id=excluded.pending_approval_id,
                    mission_summary=excluded.mission_summary,
                    auto_run=excluded.auto_run,
                    metadata_json=excluded.metadata_json,
                    updated_at=excluded.updated_at
                """,
                (
                    workspace.id,
                    workspace.project_id,
                    workspace.title,
                    workspace.slug,
                    workspace.recipe_id,
                    workspace.source_type,
                    workspace.source_repo_url,
                    workspace.lane,
                    workspace.status,
                    workspace.workspace_path,
                    workspace.default_branch,
                    workspace.current_branch,
                    workspace.current_score,
                    workspace.target_score,
                    workspace.last_digest_summary,
                    workspace.last_run_id,
                    workspace.pending_approval_id,
                    workspace.mission_summary,
                    int(workspace.auto_run),
                    self._encode(workspace.metadata),
                    workspace.created_at,
                    workspace.updated_at,
                ),
            )
        return self.get_workspace(workspace.id) or workspace

    def delete_workspace(self, workspace_id: str) -> None:
        with self._lock, self._connect() as conn:
            conn.execute("DELETE FROM run_steps WHERE run_id IN (SELECT id FROM runs WHERE workspace_id = ?)", (workspace_id,))
            conn.execute("DELETE FROM approvals WHERE workspace_id = ?", (workspace_id,))
            conn.execute("DELETE FROM runs WHERE workspace_id = ?", (workspace_id,))
            conn.execute("DELETE FROM workspaces WHERE id = ?", (workspace_id,))
            conn.execute("UPDATE ideas SET active_project_id = NULL, updated_at = ? WHERE active_project_id = ?", (_now_iso(), workspace_id))

    def create_run(self, run: RunRecord) -> RunRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO runs (
                    id, workspace_id, project_id, recipe_id, trigger_name, status, branch_name, source_branch,
                    worktree_path, summary, error, retryable, mission_spec_json, result_payload_json,
                    project_snapshot_json, legacy_attempt_key, created_at, updated_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run.id,
                    run.workspace_id,
                    run.project_id,
                    run.recipe_id,
                    run.trigger,
                    run.status,
                    run.branch_name,
                    run.source_branch,
                    run.worktree_path,
                    run.summary,
                    run.error,
                    int(run.retryable),
                    self._encode(run.mission_spec.model_dump()),
                    self._encode(run.result_payload),
                    self._encode(run.project_snapshot),
                    run.legacy_attempt_key,
                    run.created_at,
                    run.updated_at,
                    run.completed_at,
                ),
            )
        return self.get_run(run.id) or run

    def update_run(self, run: RunRecord) -> RunRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                UPDATE runs
                SET status=?, branch_name=?, source_branch=?, worktree_path=?, summary=?, error=?, retryable=?,
                    mission_spec_json=?, result_payload_json=?, project_snapshot_json=?, updated_at=?, completed_at=?
                WHERE id=?
                """,
                (
                    run.status,
                    run.branch_name,
                    run.source_branch,
                    run.worktree_path,
                    run.summary,
                    run.error,
                    int(run.retryable),
                    self._encode(run.mission_spec.model_dump()),
                    self._encode(run.result_payload),
                    self._encode(run.project_snapshot),
                    run.updated_at,
                    run.completed_at,
                    run.id,
                ),
            )
        return self.get_run(run.id) or run

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return self._run_from_row(row) if row else None

    def list_runs(self, *, workspace_id: str | None = None, limit: int = 25) -> list[RunRecord]:
        with self._lock, self._connect() as conn:
            if workspace_id:
                rows = conn.execute(
                    "SELECT * FROM runs WHERE workspace_id = ? ORDER BY created_at DESC LIMIT ?",
                    (workspace_id, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM runs ORDER BY created_at DESC LIMIT ?",
                    (limit,),
                ).fetchall()
        return [self._run_from_row(row) for row in rows]

    def add_run_step(self, step: RunStepRecord) -> RunStepRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO run_steps (
                    id, run_id, name, status, summary, prompt_excerpt, logs, artifact_paths_json, started_at, completed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    step.id,
                    step.run_id,
                    step.name,
                    step.status,
                    step.summary,
                    step.prompt_excerpt,
                    step.logs,
                    self._encode(step.artifact_paths),
                    step.started_at,
                    step.completed_at,
                ),
            )
        return step

    def list_run_steps(self, run_id: str) -> list[RunStepRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM run_steps WHERE run_id = ? ORDER BY started_at ASC", (run_id,)).fetchall()
        return [
            RunStepRecord(
                id=row["id"],
                run_id=row["run_id"],
                name=row["name"],
                status=row["status"],
                summary=row["summary"],
                prompt_excerpt=row["prompt_excerpt"],
                logs=row["logs"],
                artifact_paths=[str(item) for item in self._decode_list(row["artifact_paths_json"])],
                started_at=row["started_at"],
                completed_at=row["completed_at"],
            )
            for row in rows
        ]

    def create_approval(self, approval: ApprovalRequestRecord) -> ApprovalRequestRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO approvals (
                    id, workspace_id, project_id, run_id, status, summary, diff_summary, commit_hash,
                    changed_files_json, created_at, resolved_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    approval.id,
                    approval.workspace_id,
                    approval.project_id,
                    approval.run_id,
                    approval.status,
                    approval.summary,
                    approval.diff_summary,
                    approval.commit_hash,
                    self._encode(approval.changed_files),
                    approval.created_at,
                    approval.resolved_at,
                ),
            )
        workspace = self.get_workspace(approval.workspace_id)
        if workspace is not None:
            workspace.pending_approval_id = approval.id
            workspace.updated_at = _now_iso()
            self.save_workspace(workspace)
        return self.get_approval(approval.id) or approval

    def get_approval(self, approval_id: str) -> ApprovalRequestRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
        return self._approval_from_row(row) if row else None

    def list_approvals(self, *, status: ApprovalStatus | None = None, limit: int = 25) -> list[ApprovalRequestRecord]:
        with self._lock, self._connect() as conn:
            if status:
                rows = conn.execute(
                    "SELECT * FROM approvals WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                    (status, limit),
                ).fetchall()
            else:
                rows = conn.execute("SELECT * FROM approvals ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [self._approval_from_row(row) for row in rows]

    def resolve_approval(self, approval_id: str, *, status: ApprovalStatus) -> ApprovalRequestRecord:
        resolved_at = _now_iso()
        with self._lock, self._connect() as conn:
            conn.execute(
                "UPDATE approvals SET status = ?, resolved_at = ? WHERE id = ?",
                (status, resolved_at, approval_id),
            )
        approval = self.get_approval(approval_id)
        if approval is None:
            raise ValueError("Approval not found.")
        workspace = self.get_workspace(approval.workspace_id)
        if workspace is not None and workspace.pending_approval_id == approval.id:
            workspace.pending_approval_id = None
            workspace.updated_at = resolved_at
            self.save_workspace(workspace)
        return approval

    def list_skills(self) -> list[SkillRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM skills ORDER BY built_in DESC, id ASC").fetchall()
        return [self._skill_from_row(row) for row in rows]

    def get_skill(self, skill_id: str) -> SkillRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM skills WHERE id = ?", (skill_id,)).fetchone()
        return self._skill_from_row(row) if row else None

    def save_skill(self, skill: SkillRecord) -> SkillRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO skills (
                    id, name, description, capabilities_json, input_schema_json, output_schema_json,
                    permission_level, enabled, built_in, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    capabilities_json=excluded.capabilities_json,
                    input_schema_json=excluded.input_schema_json,
                    output_schema_json=excluded.output_schema_json,
                    permission_level=excluded.permission_level,
                    enabled=excluded.enabled,
                    built_in=excluded.built_in,
                    updated_at=excluded.updated_at
                """,
                (
                    skill.id,
                    skill.name,
                    skill.description,
                    self._encode(skill.capabilities),
                    self._encode(skill.input_schema),
                    self._encode(skill.output_schema),
                    skill.permission_level,
                    int(skill.enabled),
                    int(skill.built_in),
                    skill.created_at,
                    skill.updated_at,
                ),
            )
        return self.get_skill(skill.id) or skill

    def install_skill_manifest(self, manifest_path: str) -> SkillRecord:
        payload = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
        now = _now_iso()
        skill = SkillRecord(
            id=str(payload.get("id", "")).strip(),
            name=str(payload.get("name", "")).strip() or str(payload.get("id", "")).strip(),
            description=str(payload.get("description", "")).strip(),
            capabilities=[str(item).strip() for item in payload.get("capabilities", []) if str(item).strip()],
            input_schema=payload.get("input_schema", {}) if isinstance(payload.get("input_schema"), dict) else {},
            output_schema=payload.get("output_schema", {}) if isinstance(payload.get("output_schema"), dict) else {},
            permission_level=str(payload.get("permission_level", "safe")),
            enabled=bool(payload.get("enabled", True)),
            built_in=False,
            created_at=now,
            updated_at=now,
        )
        if not skill.id:
            raise ValueError("Skill manifest must include an id.")
        return self.save_skill(skill)

    def list_recipes(self) -> list[RecipeRecord]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT * FROM recipes ORDER BY built_in DESC, id ASC").fetchall()
        return [self._recipe_from_row(row) for row in rows]

    def get_recipe(self, recipe_id: str) -> RecipeRecord | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM recipes WHERE id = ?", (recipe_id,)).fetchone()
        return self._recipe_from_row(row) if row else None

    def save_recipe(self, recipe: RecipeRecord) -> RecipeRecord:
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO recipes (
                    id, name, description, definition_json, enabled, built_in, locked, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name,
                    description=excluded.description,
                    definition_json=excluded.definition_json,
                    enabled=excluded.enabled,
                    built_in=excluded.built_in,
                    locked=excluded.locked,
                    updated_at=excluded.updated_at
                """,
                (
                    recipe.id,
                    recipe.name,
                    recipe.description,
                    self._encode(recipe.definition),
                    int(recipe.enabled),
                    int(recipe.built_in),
                    int(recipe.locked),
                    recipe.created_at,
                    recipe.updated_at,
                ),
            )
        return self.get_recipe(recipe.id) or recipe

    def clone_recipe(self, recipe_id: str, *, new_id: str | None = None) -> RecipeRecord:
        recipe = self.get_recipe(recipe_id)
        if recipe is None:
            raise ValueError("Recipe not found.")
        now = _now_iso()
        clone = RecipeRecord(
            id=new_id or f"{recipe.id}-custom",
            name=f"{recipe.name} Custom",
            description=recipe.description,
            definition=recipe.definition,
            enabled=recipe.enabled,
            built_in=False,
            locked=False,
            created_at=now,
            updated_at=now,
        )
        return self.save_recipe(clone)

    def workspace_detail(self, workspace_id: str) -> dict[str, Any]:
        workspace = self.get_workspace(workspace_id)
        if workspace is None:
            raise ValueError("Workspace not found.")
        project = self.project_store.get_project(workspace.project_id)
        recent_runs = [run.model_dump() for run in self.list_runs(workspace_id=workspace_id, limit=10)]
        approvals = [approval.model_dump() for approval in self.list_approvals(limit=25) if approval.workspace_id == workspace_id]
        detail = workspace.model_dump()
        detail["project"] = self.project_store.project_summary(project) if project is not None else None
        detail["recent_runs"] = recent_runs
        detail["approvals"] = approvals
        return detail

    def run_detail(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run is None:
            raise ValueError("Run not found.")
        workspace = self.get_workspace(run.workspace_id)
        approval = next((item for item in self.list_approvals(limit=100) if item.run_id == run.id), None)
        return {
            "run": run.model_dump(),
            "steps": [step.model_dump() for step in self.list_run_steps(run.id)],
            "workspace": workspace.model_dump() if workspace else None,
            "approval": approval.model_dump() if approval else None,
        }
