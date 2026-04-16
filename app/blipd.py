from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha1
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any

from app.agent import LLMRequestError, ProjectBuilderAgent
from app.bucket import BucketStore
from app.config import AgentSettings
from app.platform_store import (
    ApprovalRequestRecord,
    MissionSpec,
    PlatformStore,
    RunRecord,
    RunStepRecord,
)
from app.project_store import ActiveProject, ActiveProjectStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _run_id(workspace_id: str) -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    return f"run-{workspace_id[:8]}-{stamp}"


def _hash_text(*parts: str) -> str:
    return sha1("||".join(parts).encode("utf-8")).hexdigest()[:16]


class BlipDaemon:
    def __init__(
        self,
        *,
        settings: AgentSettings,
        bucket: BucketStore,
        projects: ActiveProjectStore,
        platform: PlatformStore,
    ) -> None:
        self.settings = settings
        self.bucket = bucket
        self.projects = projects
        self.platform = platform

    def start_run(self, workspace_id: str, *, trigger: str = "manual", yolo: bool = False) -> dict[str, Any]:
        workspace = self.platform.get_workspace(workspace_id)
        if workspace is None:
            raise ValueError("Workspace not found.")
        if workspace.pending_approval_id:
            raise ValueError("Resolve the pending approval before starting another run.")

        project = self.projects.get_project(workspace.project_id)
        if project is None:
            raise ValueError("Linked project not found.")

        run_id = _run_id(workspace.id)
        run_root = self.platform.workspace_root_for_run(run_id)
        worktree_path, branch_name, source_branch = self._prepare_run_workspace(project, run_id, run_root)
        mission = self._build_mission_spec(project, workspace.recipe_id, yolo=yolo)
        run = self.platform.create_run(
            RunRecord(
                id=run_id,
                workspace_id=workspace.id,
                project_id=project.id,
                recipe_id=workspace.recipe_id,
                trigger="yolo" if yolo else trigger,
                status="running",
                branch_name=branch_name,
                source_branch=source_branch,
                worktree_path=worktree_path.as_posix(),
                summary="Run started.",
                mission_spec=mission,
                created_at=_now_iso(),
                updated_at=_now_iso(),
            )
        )
        self.platform.add_run_step(
            RunStepRecord(
                id=f"{run.id}-supervisor",
                run_id=run.id,
                name="supervisor",
                status="completed",
                summary="Prepared isolated run workspace and mission spec.",
                logs=f"Workspace: {worktree_path.as_posix()}\nBranch: {branch_name}\nRecipe: {workspace.recipe_id}",
                started_at=run.created_at,
                completed_at=_now_iso(),
            )
        )

        run_store = ActiveProjectStore(
            manifest_path=str(run_root / "run-manifest.json"),
            projects_root=str(run_root),
        )
        run_project = deepcopy(project)
        run_store.save_project(run_project)
        run_agent = ProjectBuilderAgent(settings=self.settings, bucket=self.bucket, projects=run_store)

        try:
            result = (
                run_agent.run_improvement(run_project.id)
                if project.source_type == "github"
                else run_agent.run_cycle(run_project.id, manual=True)
            )
            updated_project = run_store.get_project(run_project.id) or run_project
            run.result_payload = result
            run.project_snapshot = {
                "project": updated_project.model_dump(),
                "summary": run_store.project_summary(updated_project),
            }

            changed_files = [str(item) for item in result.get("changed_files", [])]
            decision = str(result.get("decision", "completed"))
            summary = str(result.get("accepted_summary") or result.get("message") or result.get("summary") or decision)
            validation = run_store.load_validation_summary(updated_project)
            self.platform.add_run_step(
                RunStepRecord(
                    id=f"{run.id}-executor",
                    run_id=run.id,
                    name="executor",
                    status="completed",
                    summary=summary,
                    logs=json.dumps(result, indent=2),
                    artifact_paths=list(validation.artifact_paths.values()),
                    started_at=_now_iso(),
                    completed_at=_now_iso(),
                )
            )
            self.platform.add_run_step(
                RunStepRecord(
                    id=f"{run.id}-validator",
                    run_id=run.id,
                    name="validator",
                    status="completed",
                    summary=validation.summary or "Validation captured for run workspace.",
                    logs=json.dumps(validation.model_dump(), indent=2),
                    artifact_paths=list(validation.artifact_paths.values()),
                    started_at=_now_iso(),
                    completed_at=_now_iso(),
                )
            )

            commit_hash = ""
            diff_summary = ""
            if changed_files:
                commit_hash = self._commit_run_workspace(worktree_path, run.id)
                diff_summary = self._diff_summary(worktree_path, source_branch)

            if decision == "deferred":
                run.status = "deferred"
                run.retryable = True
                run.summary = result.get("message") or "Run deferred."
                run.completed_at = _now_iso()
            elif changed_files:
                approval = self.platform.create_approval(
                    ApprovalRequestRecord(
                        id=f"approval-{_hash_text(run.id, branch_name)}",
                        workspace_id=workspace.id,
                        project_id=project.id,
                        run_id=run.id,
                        summary=summary,
                        diff_summary=diff_summary or f"{len(changed_files)} changed file(s) waiting for approval.",
                        commit_hash=commit_hash,
                        changed_files=changed_files,
                        created_at=_now_iso(),
                    )
                )
                run.status = "awaiting_approval"
                run.summary = summary or "Run completed and is awaiting approval."
                workspace.pending_approval_id = approval.id
            else:
                run.status = "completed"
                run.summary = summary or "Run completed without code changes."
                run.completed_at = _now_iso()

            workspace.last_run_id = run.id
            workspace.updated_at = _now_iso()
            self.platform.save_workspace(workspace)
            self.platform.add_run_step(
                RunStepRecord(
                    id=f"{run.id}-reviewer",
                    run_id=run.id,
                    name="reviewer",
                    status="completed",
                    summary=run.summary,
                    logs=f"Decision: {decision}\nChanged files: {', '.join(changed_files) or 'none'}",
                    started_at=_now_iso(),
                    completed_at=_now_iso(),
                )
            )
            run.updated_at = _now_iso()
            self.platform.update_run(run)
            return self.platform.run_detail(run.id)
        except LLMRequestError as exc:
            run.status = "deferred" if exc.retryable else "failed"
            run.retryable = bool(exc.retryable)
            run.error = str(exc)
            run.summary = str(exc)
            run.completed_at = _now_iso()
            run.updated_at = _now_iso()
            self.platform.add_run_step(
                RunStepRecord(
                    id=f"{run.id}-executor-error",
                    run_id=run.id,
                    name="executor",
                    status=run.status,
                    summary=str(exc),
                    logs=str(exc),
                    started_at=_now_iso(),
                    completed_at=_now_iso(),
                )
            )
            self.platform.update_run(run)
            return self.platform.run_detail(run.id)
        except Exception as exc:
            run.status = "failed"
            run.error = str(exc)
            run.summary = f"Run failed: {exc}"
            run.completed_at = _now_iso()
            run.updated_at = _now_iso()
            self.platform.add_run_step(
                RunStepRecord(
                    id=f"{run.id}-executor-error",
                    run_id=run.id,
                    name="executor",
                    status="failed",
                    summary=str(exc),
                    logs=str(exc),
                    started_at=_now_iso(),
                    completed_at=_now_iso(),
                )
            )
            self.platform.update_run(run)
            raise

    def approve_run(self, run_id: str) -> dict[str, Any]:
        run = self.platform.get_run(run_id)
        if run is None:
            raise ValueError("Run not found.")
        approval = next((item for item in self.platform.list_approvals(limit=100) if item.run_id == run.id and item.status == "pending"), None)
        if approval is None:
            raise ValueError("No pending approval found for that run.")
        project = self.projects.get_project(run.project_id)
        if project is None:
            raise ValueError("Linked project not found.")
        source_workspace = self.projects.workspace_path(project)
        run_workspace = Path(run.worktree_path)
        self._apply_run_workspace(source_workspace, run_workspace, run.branch_name, run.source_branch)

        snapshot = run.project_snapshot.get("project", {})
        if snapshot:
            updated_project = ActiveProject.model_validate(snapshot)
            self.projects.save_project(updated_project)
            project = updated_project

        self.platform.resolve_approval(approval.id, status="approved")
        run.status = "approved"
        run.summary = approval.summary or run.summary
        run.completed_at = _now_iso()
        run.updated_at = _now_iso()
        self.platform.update_run(run)
        workspace = self.platform.upsert_workspace_from_project(project)
        workspace.pending_approval_id = None
        workspace.current_branch = workspace.default_branch
        workspace.updated_at = _now_iso()
        self.platform.save_workspace(workspace)
        return self.platform.run_detail(run.id)

    def reject_run(self, run_id: str) -> dict[str, Any]:
        run = self.platform.get_run(run_id)
        if run is None:
            raise ValueError("Run not found.")
        approval = next((item for item in self.platform.list_approvals(limit=100) if item.run_id == run.id and item.status == "pending"), None)
        if approval is None:
            raise ValueError("No pending approval found for that run.")
        self.platform.resolve_approval(approval.id, status="rejected")
        run.status = "rejected"
        run.summary = approval.summary or run.summary or "Run rejected."
        run.completed_at = _now_iso()
        run.updated_at = _now_iso()
        self.platform.update_run(run)
        workspace = self.platform.get_workspace(run.workspace_id)
        if workspace is not None:
            workspace.pending_approval_id = None
            workspace.updated_at = _now_iso()
            self.platform.save_workspace(workspace)
        return self.platform.run_detail(run.id)

    def _build_mission_spec(self, project: ActiveProject, recipe_id: str, *, yolo: bool) -> MissionSpec:
        digest = self.projects.load_repo_digest(project).model_dump() if project.source_type == "github" else {}
        validation = self.projects.load_validation_summary(project).model_dump()
        manual_instructions = self.projects.load_instructions(project) if project.source_type == "github" else ""
        objective = (
            manual_instructions.strip()
            or project.product_brief.must_have_flow
            or project.repo_digest_summary
            or project.source_description
        )
        constraints = [
            "Work inside the isolated run branch only.",
            "Do not change the source workspace until approval.",
            "Preserve the repo run and test contract where possible.",
        ]
        if yolo:
            constraints.append("Maximize productive repository improvement using the current recipe and enabled skills.")
        return MissionSpec(
            objective=objective or f"Improve {project.title}",
            summary=project.last_accepted_summary or project.repo_digest_summary or project.source_description,
            success_criteria=project.product_brief.acceptance_criteria or list(project.validation_artifacts.keys()),
            constraints=constraints,
            recipe_id=recipe_id,
            source_type=project.source_type,
            manual_instructions=manual_instructions,
            digest_summary=project.repo_digest_summary,
            product_brief=project.product_brief.model_dump(),
            digest=digest,
            validation=validation,
        )

    def _prepare_run_workspace(self, project: ActiveProject, run_id: str, run_root: Path) -> tuple[Path, str, str]:
        source_workspace = self.projects.workspace_path(project)
        self._ensure_git_repo(source_workspace)
        source_branch = self._git_output(source_workspace, ["git", "branch", "--show-current"]) or "main"
        branch_name = f"blip/{project.slug}-{run_id[-8:]}"
        worktree_path = run_root / project.slug
        if worktree_path.exists():
            shutil.rmtree(worktree_path, ignore_errors=True)
        subprocess.run(
            ["git", "worktree", "add", "-b", branch_name, str(worktree_path), source_branch],
            cwd=source_workspace,
            check=True,
            capture_output=True,
            timeout=60,
        )
        self._mirror_workspace(source_workspace, worktree_path)
        return worktree_path, branch_name, source_branch

    def _ensure_git_repo(self, workspace: Path) -> None:
        if (workspace / ".git").exists():
            return
        subprocess.run(["git", "init"], cwd=workspace, check=True, capture_output=True, timeout=30)
        subprocess.run(["git", "checkout", "-b", "main"], cwd=workspace, check=True, capture_output=True, timeout=30)
        subprocess.run(["git", "add", "-A"], cwd=workspace, check=True, capture_output=True, timeout=30)
        subprocess.run(
            ["git", "-c", "user.name=Blip", "-c", "user.email=blip@local", "commit", "-m", "Initial workspace snapshot"],
            cwd=workspace,
            check=True,
            capture_output=True,
            timeout=30,
        )

    @staticmethod
    def _git_output(workspace: Path, command: list[str]) -> str:
        try:
            completed = subprocess.run(command, cwd=workspace, capture_output=True, text=True, check=True, timeout=20)
            return completed.stdout.strip()
        except Exception:
            return ""

    def _commit_run_workspace(self, worktree_path: Path, run_id: str) -> str:
        status = self._git_output(worktree_path, ["git", "status", "--porcelain"])
        if not status.strip():
            return self._git_output(worktree_path, ["git", "rev-parse", "HEAD"])
        subprocess.run(["git", "add", "-A"], cwd=worktree_path, check=True, capture_output=True, timeout=30)
        subprocess.run(
            ["git", "-c", "user.name=Blip", "-c", "user.email=blip@local", "commit", "-m", f"Blip run {run_id}"],
            cwd=worktree_path,
            check=True,
            capture_output=True,
            timeout=60,
        )
        return self._git_output(worktree_path, ["git", "rev-parse", "HEAD"])

    def _diff_summary(self, worktree_path: Path, source_branch: str) -> str:
        try:
            completed = subprocess.run(
                ["git", "diff", "--stat", source_branch],
                cwd=worktree_path,
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            return completed.stdout.strip()
        except Exception:
            return ""

    def _apply_run_workspace(self, source_workspace: Path, run_workspace: Path, branch_name: str, source_branch: str) -> None:
        subprocess.run(["git", "checkout", source_branch], cwd=source_workspace, check=True, capture_output=True, timeout=30)
        subprocess.run(["git", "merge", "--ff-only", branch_name], cwd=source_workspace, check=True, capture_output=True, timeout=60)

    @staticmethod
    def _mirror_workspace(source_workspace: Path, worktree_path: Path) -> None:
        for path in source_workspace.rglob("*"):
            try:
                relative = path.relative_to(source_workspace)
            except ValueError:
                continue
            if any(part == ".git" for part in relative.parts):
                continue
            destination = worktree_path / relative
            if path.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
