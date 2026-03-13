from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha1
import json
import logging
from pathlib import Path
import shutil
from tempfile import TemporaryDirectory
import time
from typing import Any

from openai import APIConnectionError, APITimeoutError, OpenAI
from pydantic import BaseModel, Field

from app.bucket import BucketStore, ProjectIdea, ProjectSection
from app.config import AgentSettings
from app.mvp_templates import TemplateBundle, build_template_bundle
from app.project_store import (
    ActiveProject,
    ActiveProjectStore,
    ProductBrief,
    ProjectAttempt,
    RefCriterion,
    RefRubric,
    SupportedLane,
    ValidationSummary,
    fingerprint_for_text,
)
from app.lanes_config import get_enabled_lanes, get_lane_keywords
from app.project_validation import all_hard_gates_pass, docs_only_change, validate_workspace

logger = logging.getLogger(__name__)


class LLMRequestError(RuntimeError):
    pass


class RefScore(BaseModel):
    score: int = Field(ge=0, le=100)
    reason: str = ""
    strengths: list[str] = Field(default_factory=list)
    gaps: list[str] = Field(default_factory=list)


class QualificationDecision(BaseModel):
    supported: bool = False
    lane: SupportedLane = "unsupported"
    target_user: str = ""
    job_to_be_done: str = ""
    manual_workaround: str = ""
    pain_severity: str = ""
    roi: str = ""
    must_have_flow: str = ""
    reason: str = ""


@dataclass
class CandidateResult:
    changed_files: list[str]
    summary: str
    validation: ValidationSummary
    score: RefScore


@dataclass
class RepoChunk:
    index: int
    text: str
    file_paths: list[str]


EXCLUDED_REPO_DIRS = {
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".pytest_cache",
    "dist",
    "build",
    "coverage",
    ".next",
    ".turbo",
    ".idea",
    ".vscode",
}
EXCLUDED_REPO_FILES = {
    "records.json",
    "VALIDATION.json",
    "active_projects.json",
}
TEXT_FILE_EXTENSIONS = {
    ".py",
    ".js",
    ".jsx",
    ".ts",
    ".tsx",
    ".json",
    ".md",
    ".txt",
    ".html",
    ".css",
    ".scss",
    ".yml",
    ".yaml",
    ".toml",
    ".ini",
    ".cfg",
    ".sh",
    ".bat",
    ".ps1",
    ".sql",
    ".xml",
    ".env",
    ".gitignore",
    ".dockerignore",
}
MAX_REPO_FILE_BYTES = 200_000
MAX_REPO_FILE_CHARS = 8_000
MAX_REPO_TOTAL_CHARS = 120_000
MAX_REPO_CHUNK_CHARS = 18_000
MAX_REPO_EDIT_FILES = 40


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_json_object(text: str) -> dict[str, Any]:
    text = (text or "").strip()
    if not text:
        return {}
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            logger.warning("Failed to parse model output as JSON; output=%s", text)
            return {}
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            logger.warning("Failed to parse model output as JSON; output=%s", text)
            return {}


def _build_client(settings: AgentSettings) -> OpenAI:
    return OpenAI(timeout=settings.openai_timeout_seconds, max_retries=0)


def _run_json_completion(
    *,
    client: OpenAI,
    settings: AgentSettings,
    prompt: str,
    temperature: float,
    label: str,
) -> dict[str, Any]:
    for attempt in range(settings.openai_request_retries + 1):
        try:
            response = client.chat.completions.create(
                model=settings.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
                temperature=temperature,
                timeout=settings.openai_timeout_seconds,
            )
            text = response.choices[0].message.content or ""
            return _parse_json_object(text)
        except (APITimeoutError, APIConnectionError) as exc:
            if attempt >= settings.openai_request_retries:
                raise LLMRequestError(f"{label} could not reach OpenAI in time.") from exc
            time.sleep(min(2**attempt, 4))


def _run_text_completion(
    *,
    client: OpenAI,
    settings: AgentSettings,
    prompt: str,
    temperature: float,
    label: str,
) -> str:
    for attempt in range(settings.openai_request_retries + 1):
        try:
            response = client.chat.completions.create(
                model=settings.model,
                messages=[{"role": "user", "content": prompt}],
                temperature=temperature,
                timeout=settings.openai_timeout_seconds,
            )
            return (response.choices[0].message.content or "").strip()
        except (APITimeoutError, APIConnectionError) as exc:
            if attempt >= settings.openai_request_retries:
                raise LLMRequestError(f"{label} could not reach OpenAI in time.") from exc
            time.sleep(min(2**attempt, 4))


class TrendResearchAgent:
    def __init__(self, settings: AgentSettings, bucket: BucketStore):
        self.settings = settings
        self.bucket = bucket
        self.client = _build_client(settings)

    def run_once(self) -> dict[str, Any]:
        existing_titles = self.bucket.existing_titles()
        ideas = self._generate_ideas(existing_titles)

        added: list[ProjectIdea] = []
        skipped: list[str] = []
        now = _now_iso()

        for idea in ideas:
            title = str(idea.get("title", "")).strip()
            description = str(idea.get("description", "")).strip()
            if not title or not description:
                continue
            normalized = title.lower()
            if normalized in existing_titles:
                skipped.append(title)
                continue
            added.append(ProjectIdea(title=title, description=description, created_at=now))
            existing_titles.add(normalized)

        self.bucket.append_run(added=added, skipped_titles=skipped)
        return {"added": [project.__dict__ for project in added], "skipped": skipped, "run_at": now}

    def _generate_ideas(self, existing_titles: set[str]) -> list[dict[str, str]]:
        prompt = (
            "You are a B2B software opportunity researcher. Return only ideas that fit one of these lanes: "
            "ops copilots, intake/approval workflows, or reporting dashboards.\n"
            "Return strict JSON with key 'ideas', where each item includes "
            "{title, lane, target_user, job_to_be_done, manual_workaround, pain_severity, roi, must_have_flow}.\n"
            f"Existing titles: {sorted(existing_titles)}.\n"
            "Keep titles distinct and practical."
        )
        data = _run_json_completion(
            client=self.client,
            settings=self.settings,
            prompt=prompt,
            temperature=0.7,
            label="Trend research",
        )
        raw_ideas = data.get("ideas", [])
        if not isinstance(raw_ideas, list):
            return []
        ideas: list[dict[str, str]] = []
        for item in raw_ideas[: self.settings.ideas_per_run]:
            if not isinstance(item, dict):
                continue
            lane = str(item.get("lane", "")).strip()
            target_user = str(item.get("target_user", "")).strip()
            flow = str(item.get("must_have_flow", "")).strip()
            roi = str(item.get("roi", "")).strip()
            description = " | ".join(
                bit
                for bit in [
                    f"Lane: {lane}" if lane else "",
                    f"User: {target_user}" if target_user else "",
                    f"Flow: {flow}" if flow else "",
                    f"ROI: {roi}" if roi else "",
                ]
                if bit
            )
            ideas.append(
                {
                    "title": str(item.get("title", "")).strip(),
                    "description": description[:220] or str(item.get("job_to_be_done", "")).strip()[:220],
                }
            )
        return ideas


class BucketOrganizerAgent:
    def __init__(self, settings: AgentSettings, bucket: BucketStore):
        self.settings = settings
        self.bucket = bucket
        self.client = _build_client(settings)

    def run_once(self) -> dict[str, Any]:
        projects = self.bucket.list_projects()
        now = _now_iso()
        if not projects:
            return {"sections": [], "organized_count": 0, "section_count": 0, "run_at": now}
        sections = self._generate_sections(projects)
        self.bucket.write_organized_sections(sections, run_at=now)
        return {
            "sections": [
                {"name": section.name, "projects": [project.__dict__ for project in section.projects]}
                for section in sections
            ],
            "organized_count": sum(len(section.projects) for section in sections),
            "section_count": len(sections),
            "run_at": now,
        }

    def _generate_sections(self, projects: list[ProjectIdea]) -> list[ProjectSection]:
        prompt = (
            "Group these project ideas into clear B2B sections.\n"
            'Return strict JSON: {"sections":[{"name":"Section","titles":["Exact Title"]}]}\n'
            f"Projects: {json.dumps([project.__dict__ for project in projects])}"
        )
        data = _run_json_completion(
            client=self.client,
            settings=self.settings,
            prompt=prompt,
            temperature=0.2,
            label="Bucket organization",
        )
        raw_sections = data.get("sections", [])
        if not isinstance(raw_sections, list):
            raw_sections = []
        project_lookup = {project.title.lower().strip(): project for project in projects}
        used_names: set[str] = set()
        assigned: set[str] = set()
        sections: list[ProjectSection] = []
        for raw_section in raw_sections:
            if not isinstance(raw_section, dict):
                continue
            name = self._unique_section_name(str(raw_section.get("name", "")).strip(), used_names)
            titles = raw_section.get("titles", [])
            if not isinstance(titles, list):
                continue
            bucket = []
            for raw_title in titles:
                key = str(raw_title).lower().strip()
                project = project_lookup.get(key)
                if project is None or key in assigned:
                    continue
                bucket.append(project)
                assigned.add(key)
            if bucket:
                sections.append(ProjectSection(name=name, projects=bucket))
        if not sections:
            return [ProjectSection(name="All Projects", projects=projects)]
        unassigned = [project for project in projects if project.title.lower().strip() not in assigned]
        if unassigned:
            sections.append(ProjectSection(name=self._unique_section_name("Other Ideas", used_names), projects=unassigned))
        return sections

    @staticmethod
    def _unique_section_name(name: str, used_names: set[str]) -> str:
        base_name = name or "Other Ideas"
        candidate = base_name
        suffix = 2
        while candidate.lower() in used_names:
            candidate = f"{base_name} {suffix}"
            suffix += 1
        used_names.add(candidate.lower())
        return candidate


class ProjectQualifierAgent:
    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self.client = _build_client(settings)

    def qualify(self, idea: ProjectIdea) -> QualificationDecision:
        enabled = get_enabled_lanes()
        if not enabled:
            return QualificationDecision(
                supported=False,
                lane="unsupported",
                reason="No project types are enabled. Enable at least one lane in Project types.",
            )
        lanes_list = ", ".join(enabled)
        prompt = (
            "You are a product qualifier for an autonomous MVP factory.\n"
            f"Only support these lanes: {lanes_list}.\n"
            "Reject consumer coaching, generic apps, or anything without a clear workflow.\n"
            "Return strict JSON with: "
            '{"supported":true,"lane":"ops-copilot","target_user":"...","job_to_be_done":"...",'
            '"manual_workaround":"...","pain_severity":"...","roi":"...","must_have_flow":"...","reason":"..."}\n'
            f"Title: {idea.title}\nDescription: {idea.description}"
        )
        try:
            data = _run_json_completion(
                client=self.client,
                settings=self.settings,
                prompt=prompt,
                temperature=0.2,
                label="Qualification",
            )
            decision = QualificationDecision.model_validate(data)
            if decision.supported and decision.lane != "unsupported" and decision.lane in enabled:
                return decision
        except Exception:
            pass
        return self._fallback_decision(idea)

    def _fallback_decision(self, idea: ProjectIdea) -> QualificationDecision:
        text = f"{idea.title} {idea.description}".lower()
        lane: SupportedLane = "unsupported"
        best_hits = 0
        keywords_map = get_lane_keywords()
        for candidate, keywords in keywords_map.items():
            hits = sum(1 for keyword in keywords if keyword in text)
            if hits > best_hits:
                lane = candidate
                best_hits = hits
        if lane == "unsupported":
            return QualificationDecision(
                supported=False,
                lane="unsupported",
                reason="Idea does not match the supported B2B MVP lanes.",
            )
        defaults = _lane_defaults(lane)
        return QualificationDecision(
            supported=True,
            lane=lane,
            target_user=defaults["target_user"],
            job_to_be_done=defaults["job_to_be_done"],
            manual_workaround=defaults["manual_workaround"],
            pain_severity="High",
            roi=defaults["roi"],
            must_have_flow=defaults["must_have_flow"],
            reason="Matched a supported B2B workflow lane by heuristic classification.",
        )


class ProjectPlannerAgent:
    def __init__(self, settings: AgentSettings) -> None:
        self.settings = settings
        self.client = _build_client(settings)

    def plan(self, idea: ProjectIdea, qualification: QualificationDecision) -> ProductBrief:
        prompt = (
            "Create a frozen MVP product brief for a B2B workflow tool.\n"
            "Return strict JSON with: "
            '{"lane":"ops-copilot","title":"...","opportunity_summary":"...","target_user":"...",'
            '"job_to_be_done":"...","manual_workaround":"...","pain_severity":"...","roi":"...",'
            '"must_have_flow":"...","icp":"...","problem":"...","success_metric":"...",'
            '"required_entities":["..."],"must_have_screens":["..."],"must_have_actions":["..."],'
            '"demo_scenario":"...","acceptance_criteria":["..."]}\n'
            f"Title: {idea.title}\nDescription: {idea.description}\nQualification: {qualification.model_dump_json(indent=2)}"
        )
        try:
            data = _run_json_completion(
                client=self.client,
                settings=self.settings,
                prompt=prompt,
                temperature=0.3,
                label="Planning",
            )
            brief = ProductBrief.model_validate(data)
            if brief.lane != "unsupported":
                return brief
        except Exception:
            pass
        return self._fallback_brief(idea, qualification)

    def _fallback_brief(self, idea: ProjectIdea, qualification: QualificationDecision) -> ProductBrief:
        defaults = _lane_defaults(qualification.lane)
        return ProductBrief(
            lane=qualification.lane,
            title=idea.title,
            opportunity_summary=idea.description or defaults["summary"],
            target_user=qualification.target_user or defaults["target_user"],
            job_to_be_done=qualification.job_to_be_done or defaults["job_to_be_done"],
            manual_workaround=qualification.manual_workaround or defaults["manual_workaround"],
            pain_severity=qualification.pain_severity or "High",
            roi=qualification.roi or defaults["roi"],
            must_have_flow=qualification.must_have_flow or defaults["must_have_flow"],
            icp=defaults["icp"],
            problem=defaults["problem"],
            success_metric=defaults["success_metric"],
            required_entities=defaults["required_entities"],
            must_have_screens=defaults["must_have_screens"],
            must_have_actions=defaults["must_have_actions"],
            demo_scenario=defaults["demo_scenario"],
            acceptance_criteria=defaults["acceptance_criteria"],
        )


class TemplateScaffolderAgent:
    def scaffold(self, project_title: str, brief: ProductBrief) -> TemplateBundle:
        return build_template_bundle(project_title, brief)


class ProjectBackendBuilderAgent:
    def apply(self, workspace: Path, bundle: TemplateBundle, validation: ValidationSummary, force_full: bool) -> list[str]:
        if force_full:
            return _write_full_bundle(workspace, bundle)
        failing = set(validation.failing_checks)
        paths = []
        if failing & {"scaffold_contract", "run_command", "smoke_test", "seed_data", "workflow_test"}:
            paths.extend(["app/main.py", "app/project_config.json", "demo_data/seed.json"])
        return _write_bundle_subset(workspace, bundle, paths)


class ProjectUXBuilderAgent:
    def apply(self, workspace: Path, bundle: TemplateBundle, validation: ValidationSummary, force_full: bool) -> list[str]:
        paths = []
        if force_full or "readme_instructions" in validation.failing_checks:
            paths.extend(["README.md", "PROJECT_PLAN.md"])
        if force_full or set(validation.failing_checks) & {"scaffold_contract", "smoke_test"}:
            paths.extend(["app/templates/base.html", "app/templates/index.html", "app/templates/detail.html"])
        return _write_bundle_subset(workspace, bundle, paths)


class ProjectQABuilderAgent:
    def apply(self, workspace: Path, bundle: TemplateBundle, validation: ValidationSummary, force_full: bool) -> list[str]:
        paths = []
        if force_full or set(validation.failing_checks) & {"scaffold_contract", "run_command", "workflow_test", "seed_data"}:
            paths.extend(["requirements.txt", "tests/test_app.py"])
        return _write_bundle_subset(workspace, bundle, paths)


class ProjectRefAgent:
    def __init__(self, settings: AgentSettings, projects: ActiveProjectStore) -> None:
        self.settings = settings
        self.projects = projects
        self.client = _build_client(settings)

    def build_rubric(self, project: ActiveProject) -> RefRubric:
        criteria = [
            RefCriterion(name="Workflow usefulness", weight=30, description="Core user flow solves the target job to be done."),
            RefCriterion(name="MVP completeness", weight=25, description="Essential screens, actions, and seeded demo data are present."),
            RefCriterion(name="Usability", weight=20, description="The workflow is understandable and easy to try locally."),
            RefCriterion(name="Lane fit", weight=15, description="The project clearly matches the chosen B2B workflow lane."),
            RefCriterion(name="Quality and clarity", weight=10, description="Tests, README, and implementation quality support adoption."),
        ]
        return RefRubric(
            summary=f"Hybrid rubric for {project.title} in lane {project.lane}.",
            criteria=criteria,
            scoring_notes="Hard gates must pass before qualitative scoring can count.",
        )

    def score(self, project: ActiveProject, workspace: Path, validation: ValidationSummary) -> RefScore:
        if not all_hard_gates_pass(validation):
            return RefScore(
                score=0,
                reason="Hard gates are still failing, so REF will not sign off on this MVP yet.",
                strengths=[],
                gaps=validation.failing_checks,
            )
        prompt = (
            "You are REF, the final reviewer for a B2B MVP factory.\n"
            "Only evaluate qualitative quality now that deterministic gates have passed.\n"
            'Return strict JSON: {"score":78,"reason":"...","strengths":["..."],"gaps":["..."]}\n'
            f"Product brief: {project.product_brief.model_dump_json(indent=2)}\n"
            f"Rubric: {project.ref_rubric.model_dump_json(indent=2)}\n"
            f"Validation: {validation.model_dump_json(indent=2)}\n"
            f"Workspace:\n{self.projects.workspace_context(workspace)}"
        )
        try:
            data = _run_json_completion(
                client=self.client,
                settings=self.settings,
                prompt=prompt,
                temperature=0.1,
                label="REF scoring",
            )
            return RefScore.model_validate(data)
        except Exception:
            score = self.settings.usable_mvp_score + min(15, len(project.product_brief.acceptance_criteria))
            return RefScore(
                score=min(score, 92),
                reason="All hard gates passed and the scaffold matches the product brief.",
                strengths=["Runnable locally", "Demo workflow passes", "Seed data present"],
                gaps=["Further polish would require deeper workflow differentiation."],
            )


class ProjectBuilderAgent:
    def __init__(self, settings: AgentSettings, bucket: BucketStore, projects: ActiveProjectStore) -> None:
        self.settings = settings
        self.bucket = bucket
        self.projects = projects
        self.qualifier = ProjectQualifierAgent(settings)
        self.planner = ProjectPlannerAgent(settings)
        self.scaffolder = TemplateScaffolderAgent()
        self.backend_builder = ProjectBackendBuilderAgent()
        self.ux_builder = ProjectUXBuilderAgent()
        self.qa_builder = ProjectQABuilderAgent()
        self.ref = ProjectRefAgent(settings, projects)

    def promote_project(self, idea: ProjectIdea) -> dict[str, Any]:
        qualification = self.qualifier.qualify(idea)
        if not qualification.supported or qualification.lane == "unsupported":
            raise ValueError("Only supported B2B workflow ideas can be promoted into MVP generation.")
        brief = self.planner.plan(idea, qualification)
        project = self.projects.create_project(idea, target_score=self.settings.project_target_score)
        project.lane = brief.lane
        project.product_brief = brief
        project.template_id = f"{brief.lane}-v1"
        project.stage = "qualified"
        project.stack_name = "FastAPI + Jinja + HTMX + SQLite + SQLModel + pytest"
        project.run_command = "uvicorn app.main:app --reload"
        project.test_command = "pytest -q"
        project.ref_rubric = self.ref.build_rubric(project)
        self.projects.save_project(project)
        self.projects.write_product_brief(project, brief)

        build_result = self.run_build_stage(project.id)
        validate_result = self.run_validation_stage(project.id)
        return {
            "project": self.projects.project_summary(self.projects.get_project(project.id) or project),
            "build": build_result,
            "validation": validate_result,
            "decision": validate_result.get("decision", "accepted"),
            "accepted_candidate_score": validate_result.get("accepted_candidate_score"),
            "accepted_summary": validate_result.get("accepted_summary"),
            "run_at": _now_iso(),
        }

    def run_build_stage(self, project_id: str) -> dict[str, Any]:
        project = self._ensure_project_ready(project_id)
        bundle = self.scaffolder.scaffold(project.title, project.product_brief)
        changed_files = self.projects.replace_workspace_files(project, bundle.files)
        project.template_id = bundle.template_id
        project.stage = "scaffolded"
        project.stalled_reason = None
        project.run_command = bundle.run_command
        project.test_command = bundle.test_command
        self.projects.write_product_brief(project, project.product_brief)
        self.projects.save_project(project)
        summary = "Scaffolded canonical MVP bundle." if changed_files else "Scaffold already matched canonical bundle."
        self.projects.append_attempt(
            project,
            ProjectAttempt(
                attempt_key=fingerprint_for_text("scaffold", summary, ",".join(changed_files)),
                stage_name="scaffolded",
                builder_name="Template Scaffolder",
                summary=summary,
                changed_files=changed_files,
                baseline_score=project.current_score,
                candidate_score=project.current_score,
                decision="accepted",
                reason="Canonical scaffold prepared for validation.",
                validation_status=project.validation_status,
                timestamp=_now_iso(),
            ),
        )
        return {"changed_files": changed_files, "summary": summary, "run_at": _now_iso()}

    def run_validation_stage(self, project_id: str) -> dict[str, Any]:
        project = self._ensure_project_ready(project_id)
        workspace = self.projects.workspace_path(project)
        previous_score = project.current_score
        project.last_cycle_at = _now_iso()
        project.stage = "validating"
        validation = validate_workspace(
            workspace,
            project,
            self.settings,
            artifact_dir=self.projects.artifacts_dir(project),
        )
        project.validation_status = validation.status
        project.hard_gate_results = validation.hard_gate_results
        project.validation_artifacts = validation.artifact_paths
        project.seed_status = "loaded" if "seed_data" in validation.passed_checks else "missing"
        if all_hard_gates_pass(validation):
            score = self.ref.score(project, workspace, validation)
            project.current_score = max(project.current_score, score.score)
            project.last_accepted_summary = score.reason
            if score.score >= self.settings.usable_mvp_score:
                project.stage = "usable_mvp"
                project.usable_mvp_at = project.usable_mvp_at or project.last_cycle_at
                project.stalled_reason = None
            else:
                project.stage = "validating"
        else:
            score = RefScore(score=0, reason=validation.summary, strengths=[], gaps=validation.failing_checks)
            project.stage = "stalled"
            project.stalled_reason = validation.next_task
        if project.current_score >= project.target_score:
            project.status = "completed"
            project.auto_run = False
            project.stage = "completed"
        self.projects.write_validation_summary(project, validation)
        self.projects.save_project(project)
        self.projects.append_attempt(
            project,
            ProjectAttempt(
                attempt_key=fingerprint_for_text("validate", validation.summary, ",".join(validation.passed_checks)),
                stage_name="validating",
                builder_name="Validator + REF",
                summary=validation.summary,
                changed_files=[],
                baseline_score=previous_score,
                candidate_score=score.score,
                decision="accepted" if all_hard_gates_pass(validation) else "rejected",
                reason=score.reason,
                validation_status=validation.status,
                failed_checks=validation.failing_checks,
                next_task=validation.next_task,
                timestamp=project.last_cycle_at,
            ),
        )
        return {
            "project": self.projects.project_summary(project),
            "baseline_score": previous_score,
            "accepted_candidate_score": score.score if all_hard_gates_pass(validation) else None,
            "decision": "accepted" if all_hard_gates_pass(validation) else "rejected",
            "accepted_summary": score.reason if all_hard_gates_pass(validation) else None,
            "run_at": project.last_cycle_at,
        }

    def run_cycle(self, project_id: str, *, manual: bool = True) -> dict[str, Any]:
        project = self._ensure_project_ready(project_id)
        current_workspace = self.projects.workspace_path(project)
        baseline_validation = validate_workspace(current_workspace, project, self.settings)
        baseline_score = project.current_score if all_hard_gates_pass(baseline_validation) else 0

        with TemporaryDirectory() as tmpdir:
            staged_root = Path(tmpdir) / project.slug
            if current_workspace.exists():
                shutil.copytree(current_workspace, staged_root, dirs_exist_ok=True)
            else:
                staged_root.mkdir(parents=True, exist_ok=True)

            bundle = self.scaffolder.scaffold(project.title, project.product_brief)
            force_full = not _workspace_matches_template(staged_root, bundle.required_paths)
            changed_files: list[str] = []
            if force_full:
                shutil.rmtree(staged_root, ignore_errors=True)
                staged_root.mkdir(parents=True, exist_ok=True)
                changed_files.extend(_write_full_bundle(staged_root, bundle))
            else:
                changed_files.extend(self.backend_builder.apply(staged_root, bundle, baseline_validation, force_full))
                changed_files.extend(self.ux_builder.apply(staged_root, bundle, baseline_validation, force_full))
                changed_files.extend(self.qa_builder.apply(staged_root, bundle, baseline_validation, force_full))
            changed_files = sorted(set(changed_files))
            summary = "Run staged build, UX, QA, validation, and REF review."
            fingerprint = fingerprint_for_text(
                "pipeline",
                summary,
                ",".join(changed_files),
                ",".join(sorted(baseline_validation.failing_checks)),
                baseline_validation.next_task or "",
            )

            if fingerprint in self.projects.known_attempt_fingerprints(project):
                return self._record_skipped_duplicate(project, baseline_score, baseline_validation)

            candidate_validation = validate_workspace(staged_root, project, self.settings)
            candidate_score = self.ref.score(project, staged_root, candidate_validation)
            accept, reason = self._should_accept_candidate(
                changed_files=changed_files,
                baseline_score=baseline_score,
                baseline_validation=baseline_validation,
                candidate_score=candidate_score,
                candidate_validation=candidate_validation,
            )

            attempt = ProjectAttempt(
                attempt_key=fingerprint,
                stage_name="pipeline",
                builder_name="Build Pipeline",
                summary=summary,
                changed_files=changed_files,
                baseline_score=baseline_score,
                candidate_score=candidate_score.score if all_hard_gates_pass(candidate_validation) else None,
                decision="accepted" if accept else "rejected",
                reason=reason,
                validation_status=candidate_validation.status,
                failed_checks=candidate_validation.failing_checks,
                next_task=candidate_validation.next_task,
                timestamp=_now_iso(),
            )

            if accept:
                files = _workspace_file_map(staged_root)
                self.projects.replace_workspace_files(project, files)
                project.template_id = bundle.template_id
                project.run_command = bundle.run_command
                project.test_command = bundle.test_command
                project.stack_name = "FastAPI + Jinja + HTMX + SQLite + SQLModel + pytest"
                project.last_accepted_summary = candidate_score.reason
                self.projects.write_product_brief(project, project.product_brief)
                self.projects.append_attempt(project, attempt)
                validation_result = self.run_validation_stage(project.id)
                return {
                    "project": self.projects.project_summary(self.projects.get_project(project.id) or project),
                    "baseline_score": baseline_score,
                    "accepted_candidate_score": validation_result.get("accepted_candidate_score"),
                    "decision": "accepted",
                    "accepted_summary": candidate_score.reason,
                    "run_at": _now_iso(),
                }

            project.stage = "stalled"
            project.stalled_reason = reason
            if not manual:
                project.auto_run = False
            self.projects.save_project(project)
            self.projects.append_attempt(project, attempt)
            return {
                "project": self.projects.project_summary(project),
                "baseline_score": baseline_score,
                "accepted_candidate_score": None,
                "decision": "no_change",
                "accepted_summary": None,
                "run_at": _now_iso(),
            }

    def run_auto_projects_once(self) -> dict[str, Any]:
        run_at = _now_iso()
        results: list[dict[str, Any]] = []
        for project in self.projects.list_projects():
            if not project.auto_run:
                continue
            try:
                if getattr(project, "source_type", "bucket") == "github":
                    results.append(self.run_improvement(project.id))
                else:
                    results.append(self.run_cycle(project.id, manual=False))
            except LLMRequestError as exc:
                logger.warning("Automatic project run deferred for %s: %s", project.id, exc)
                results.append({"project_id": project.id, "title": project.title, "decision": "deferred", "error": str(exc), "run_at": run_at})
            except ValueError as exc:
                logger.warning("Automatic project run skipped for %s: %s", project.id, exc)
                results.append({"project_id": project.id, "title": project.title, "decision": "skipped", "error": str(exc), "run_at": run_at})
            except Exception as exc:
                logger.exception("Automatic project run failed for %s", project.id)
                results.append({"project_id": project.id, "title": project.title, "decision": "error", "error": str(exc), "run_at": run_at})
        return {"projects_processed": len(results), "results": results, "run_at": run_at}

    def _ensure_project_ready(self, project_id: str) -> ActiveProject:
        project = self.projects.get_project(project_id)
        if project is None:
            raise ValueError("Project not found.")
        if project.product_brief.lane == "unsupported" or project.lane == "unsupported":
            idea = ProjectIdea(title=project.source_title, description=project.source_description, created_at=project.source_created_at)
            decision = self.qualifier.qualify(idea)
            if not decision.supported or decision.lane == "unsupported":
                project.stage = "stalled"
                project.auto_run = False
                project.lane = "unsupported"
                project.stalled_reason = "This idea does not fit the supported B2B MVP lanes."
                self.projects.save_project(project)
                raise ValueError(project.stalled_reason)
            project.product_brief = self.planner.plan(idea, decision)
            project.lane = project.product_brief.lane
            project.template_id = f"{project.lane}-v1"
            project.stack_name = "FastAPI + Jinja + HTMX + SQLite + SQLModel + pytest"
            project.run_command = "uvicorn app.main:app --reload"
            project.test_command = "pytest -q"
            project.ref_rubric = self.ref.build_rubric(project)
            self.projects.write_product_brief(project, project.product_brief)
            self.projects.save_project(project)
        self.projects.ensure_project_files(project)
        return project

    def generate_instructions_yolo(self, project_id: str) -> str:
        """Have the LLM analyze the repo and return improvement instructions; save to instructions.txt."""
        project = self.projects.get_project(project_id)
        if project is None:
            raise ValueError("Project not found.")
        workspace = self.projects.workspace_path(project)
        if not workspace.exists():
            raise ValueError("Project workspace not found.")
        chunks, included, skipped = build_repo_chunks(workspace)
        if not chunks:
            raise ValueError("No text files were eligible for full-project analysis.")
        chunk_notes: list[str] = []
        for chunk in chunks:
            prompt = (
                "You are reviewing one chunk of a software project.\n"
                "Summarize the most important improvement opportunities from this chunk only.\n"
                'Return strict JSON: {"summary":"...","candidate_files":["path"],"notes":["..."]}\n\n'
                f"Chunk {chunk.index} of {len(chunks)}\n{chunk.text}"
            )
            data = _run_json_completion(
                client=self.ref.client,
                settings=self.settings,
                prompt=prompt,
                temperature=0.2,
                label=f"YOLO chunk {chunk.index}",
            )
            summary = str(data.get("summary", "")).strip()
            notes = data.get("notes", [])
            if not isinstance(notes, list):
                notes = []
            block = [f"Chunk {chunk.index} summary: {summary}"] if summary else [f"Chunk {chunk.index} summary:"]
            block.extend(f"- {str(note).strip()}" for note in notes if str(note).strip())
            chunk_notes.append("\n".join(block).strip())
        prompt = (
            "You are analyzing a complete software project from chunked repo context.\n"
            "Write concise, actionable instructions for an autonomous coding agent to improve the project.\n"
            "Focus on the most valuable changes first. Cover code quality, tests, docs, reliability, and developer experience where relevant.\n"
            "Output only the instructions, no preamble or title.\n\n"
            f"Included text files: {len(included)}\n"
            f"Skipped files: {len(skipped)}\n\n"
            + "\n\n".join(chunk_notes)
        )
        try:
            text = _run_text_completion(
                client=self.ref.client,
                settings=self.settings,
                prompt=prompt,
                temperature=0.3,
                label="YOLO instructions",
            )
            self.projects.save_instructions(project, text)
            return text
        except Exception as exc:
            raise LLMRequestError(f"YOLO instructions generation failed: {exc}") from exc

    def run_improvement(self, project_id: str) -> dict[str, Any]:
        """Run instruction-based improvement on a GitHub-imported project (no scaffold)."""
        project = self.projects.get_project(project_id)
        if project is None:
            raise ValueError("Project not found.")
        if getattr(project, "source_type", "bucket") != "github":
            raise ValueError("Improvement pipeline is only for GitHub-imported projects.")
        instructions = self.projects.load_instructions(project)
        if not instructions.strip():
            return {
                "project": self.projects.project_summary(project),
                "changed_files": [],
                "message": "No instructions set. Add instructions or use YOLO to generate them.",
                "run_at": _now_iso(),
            }
        workspace = self.projects.workspace_path(project).resolve()
        if not workspace.exists():
            raise ValueError("Project workspace not found.")
        chunks, included, skipped = build_repo_chunks(workspace)
        if not chunks:
            raise ValueError("No text files were eligible for improvement.")
        chunk_analyses: list[dict[str, Any]] = []
        candidate_paths: list[str] = []
        for chunk in chunks:
            prompt = (
                "You are reviewing one chunk of a software project for automated improvement.\n"
                "Consider the user instructions and the provided repo chunk.\n"
                'Return strict JSON: {"summary":"...","candidate_files":["path"],"proposed_changes":["..."]}\n\n'
                f"Instructions:\n{instructions}\n\n"
                f"Chunk {chunk.index} of {len(chunks)}\n{chunk.text}"
            )
            analysis = _run_json_completion(
                client=self.ref.client,
                settings=self.settings,
                prompt=prompt,
                temperature=0.2,
                label=f"Improvement chunk {chunk.index}",
            )
            chunk_analyses.append(analysis)
            raw_candidates = analysis.get("candidate_files", [])
            if isinstance(raw_candidates, list):
                for raw in raw_candidates:
                    path = str(raw).strip().replace("\\", "/")
                    if path and path not in candidate_paths:
                        candidate_paths.append(path)
        if not candidate_paths:
            candidate_paths = included[: min(12, len(included))]
        candidate_paths = candidate_paths[:MAX_REPO_EDIT_FILES]
        candidate_context_parts: list[str] = []
        for relative in candidate_paths:
            target = workspace / relative
            if not target.exists() or not target.is_file() or not is_llm_text_file(target, workspace):
                continue
            candidate_context_parts.append(f"=== {relative} ===\n{_read_text_safe(target)[:MAX_REPO_FILE_CHARS]}")
        candidate_context = "\n\n".join(candidate_context_parts)
        synthesis_prompt = (
            "You are improving a complete software project using chunked full-repo analysis.\n"
            "Use the instructions, chunk analyses, and current content of candidate files to produce one consolidated edit plan.\n"
            'Return strict JSON: {"summary":"...","edits":[{"path":"relative/path","content":"full new file content"}]}\n'
            "Only include files you are changing. Paths must be relative to the project root. Do not use absolute paths or '..'.\n\n"
            f"Instructions:\n{instructions}\n\n"
            f"Repo included text files: {len(included)}\n"
            f"Repo skipped files: {len(skipped)}\n"
            f"Chunk analyses:\n{json.dumps(chunk_analyses, indent=2)}\n\n"
            f"Candidate files:\n{candidate_context}"
        )
        try:
            data = _run_json_completion(
                client=self.ref.client,
                settings=self.settings,
                prompt=synthesis_prompt,
                temperature=0.2,
                label="Improvement synthesis",
            )
        except Exception as exc:
            raise LLMRequestError(f"Improvement step failed: {exc}") from exc
        edits = data.get("edits") or []
        if not isinstance(edits, list):
            edits = []
        changed: list[str] = []
        skipped_edit_paths = 0
        for item in edits:
            if not isinstance(item, dict):
                continue
            rel = (item.get("path") or "").strip().replace("\\", "/")
            if (
                ".." in rel
                or rel.startswith("/")
                or not rel
                or any(part in EXCLUDED_REPO_DIRS for part in Path(rel).parts)
            ):
                skipped_edit_paths += 1
                continue
            content = item.get("content")
            if content is None:
                continue
            target = (workspace / rel).resolve()
            try:
                target.relative_to(workspace)
            except ValueError:
                skipped_edit_paths += 1
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content if isinstance(content, str) else str(content), encoding="utf-8")
            changed.append(rel)
        llm_summary = str(data.get("summary", "")).strip()
        project.last_cycle_at = _now_iso()
        if llm_summary:
            project.last_accepted_summary = llm_summary
        self.projects.save_project(project)
        self.projects.append_attempt(
            project,
            ProjectAttempt(
                attempt_key=fingerprint_for_text("github-improve", instructions, ",".join(changed), llm_summary),
                stage_name="improvement",
                builder_name="Full Repo LLM",
                summary=llm_summary or "Full-project LLM improvement run.",
                changed_files=changed,
                baseline_score=project.current_score,
                candidate_score=project.current_score,
                decision="accepted" if changed else "no_change",
                reason=llm_summary or "No edits returned or applied.",
                validation_status=project.validation_status,
                timestamp=project.last_cycle_at,
                instructions_used=instructions,
                files_considered=len(included),
                chunk_count=len(chunks),
                skipped_files=len(skipped) + skipped_edit_paths,
                llm_summary=llm_summary or None,
            ),
        )
        return {
            "project": self.projects.project_summary(self.projects.get_project(project_id) or project),
            "changed_files": changed,
            "message": f"Applied improvements to {len(changed)} file(s)." if changed else "No edits returned or applied.",
            "summary": llm_summary,
            "files_considered": len(included),
            "chunk_count": len(chunks),
            "skipped_files": len(skipped) + skipped_edit_paths,
            "run_at": project.last_cycle_at,
        }

    def _should_accept_candidate(
        self,
        *,
        changed_files: list[str],
        baseline_score: int,
        baseline_validation: ValidationSummary,
        candidate_score: RefScore,
        candidate_validation: ValidationSummary,
    ) -> tuple[bool, str]:
        if not changed_files:
            return False, "No meaningful file changes were proposed."
        if docs_only_change(changed_files):
            return False, "README-only or metadata-only changes do not count as MVP improvement."
        if not all_hard_gates_pass(candidate_validation):
            return False, "Candidate still fails one or more deterministic MVP hard gates."
        if not all_hard_gates_pass(baseline_validation):
            return True, "Candidate upgrades the project to a fully validated MVP."
        if candidate_score.score > baseline_score:
            return True, "Candidate improves the validated project score."
        return False, "Candidate did not beat the current validated score."

    def _record_skipped_duplicate(
        self,
        project: ActiveProject,
        baseline_score: int,
        baseline_validation: ValidationSummary,
    ) -> dict[str, Any]:
        self.projects.append_attempt(
            project,
            ProjectAttempt(
                attempt_key=fingerprint_for_text("duplicate", project.id, project.stage),
                stage_name="pipeline",
                builder_name="Build Pipeline",
                summary="Skipped duplicate pipeline attempt.",
                changed_files=[],
                baseline_score=baseline_score,
                candidate_score=None,
                decision="skipped_duplicate",
                reason="The same failed-or-no-op pipeline attempt was already recorded.",
                validation_status=baseline_validation.status,
                failed_checks=baseline_validation.failing_checks,
                next_task=baseline_validation.next_task,
                timestamp=_now_iso(),
            ),
        )
        return {
            "project": self.projects.project_summary(project),
            "baseline_score": baseline_score,
            "accepted_candidate_score": None,
            "decision": "skipped_duplicate",
            "accepted_summary": None,
            "run_at": _now_iso(),
        }


def _lane_defaults(lane: SupportedLane) -> dict[str, Any]:
    shared = {
        "acceptance_criteria": [
            "Project boots with seeded demo data and a runnable README.",
            "Homepage loads and demonstrates the lane's core workflow.",
            "At least one end-to-end workflow test passes under pytest.",
        ]
    }
    defaults: dict[SupportedLane, dict[str, Any]] = {
        "ops-copilot": {
            "summary": "An internal operations copilot that helps teams manage a live priority queue and capture follow-up actions.",
            "target_user": "Operations managers coordinating internal queues",
            "job_to_be_done": "Review the queue, capture context, and move operational tasks forward quickly.",
            "manual_workaround": "Teams manage the queue in shared spreadsheets and chat threads.",
            "roi": "Reduce time spent triaging operational bottlenecks and missed follow-ups.",
            "must_have_flow": "Review the queue, open a task, record the latest note, and save the next action.",
            "icp": "Small and midsize service businesses with recurring back-office workflow queues.",
            "problem": "Ops teams lose context and momentum when queue work lives across spreadsheets, inboxes, and chat.",
            "success_metric": "Queue items are updated with clear next actions in under two minutes.",
            "required_entities": ["Task", "Owner", "Status", "Follow-up note"],
            "must_have_screens": ["Priority queue", "Task detail", "Queue health summary"],
            "must_have_actions": ["Update note", "Record action taken", "Review queue stats"],
            "demo_scenario": "An ops lead reviews an escalated queue item and records the follow-up taken.",
            "acceptance_criteria": shared["acceptance_criteria"]
            + ["A priority queue and task-detail workflow both work with seeded data."],
        },
        "intake-approval": {
            "summary": "An intake and approval workspace that helps reviewers move submissions through a structured queue.",
            "target_user": "Team leads or coordinators reviewing incoming requests",
            "job_to_be_done": "Review submissions, capture a decision, and keep an audit-friendly queue.",
            "manual_workaround": "Reviewers juggle intake forms, email threads, and ad hoc approval spreadsheets.",
            "roi": "Shorten approval cycle time and reduce dropped submissions.",
            "must_have_flow": "Review the intake queue, open a submission, record reviewer notes, and save a decision.",
            "icp": "Growing businesses with frequent internal approvals or onboarding reviews.",
            "problem": "Intake processes stall when submissions, reviewer notes, and decisions are fragmented.",
            "success_metric": "A reviewer can process a submission with clear status and notes in one session.",
            "required_entities": ["Submission", "Requester", "Reviewer note", "Decision"],
            "must_have_screens": ["Review queue", "Submission detail", "Approval status summary"],
            "must_have_actions": ["Capture note", "Save approval decision", "Track pending submissions"],
            "demo_scenario": "A reviewer approves a vendor onboarding packet after confirming missing information.",
            "acceptance_criteria": shared["acceptance_criteria"]
            + ["The review queue supports saving a decision and preserving reviewer notes."],
        },
        "reporting-dashboard": {
            "summary": "A reporting dashboard that turns seeded team data into a practical review workflow with follow-up actions.",
            "target_user": "Operations analysts or managers reviewing KPI trends",
            "job_to_be_done": "Spot trends, inspect a team, and create follow-up actions from the dashboard.",
            "manual_workaround": "Managers review stale exports and maintain separate action trackers.",
            "roi": "Cut reporting prep time and turn insights into tracked next steps.",
            "must_have_flow": "Review KPI cards, inspect a team, then create a follow-up action or export the current view.",
            "icp": "B2B teams that need lightweight KPI visibility without a full BI stack.",
            "problem": "Teams see metrics but fail to convert them into accountable follow-up work.",
            "success_metric": "A manager can review metrics, filter the view, and create a follow-up in one place.",
            "required_entities": ["Team metric", "Trend", "Follow-up action", "Owner"],
            "must_have_screens": ["Dashboard", "Team detail", "Follow-up action list"],
            "must_have_actions": ["Filter view", "Create follow-up", "Export current view"],
            "demo_scenario": "An analyst spots a struggling team and creates a follow-up action from the dashboard.",
            "acceptance_criteria": shared["acceptance_criteria"]
            + ["The dashboard supports exporting the current view and creating a follow-up action."],
        },
        "unsupported": {
            "summary": "",
            "target_user": "",
            "job_to_be_done": "",
            "manual_workaround": "",
            "roi": "",
            "must_have_flow": "",
            "icp": "",
            "problem": "",
            "success_metric": "",
            "required_entities": [],
            "must_have_screens": [],
            "must_have_actions": [],
            "demo_scenario": "",
            "acceptance_criteria": shared["acceptance_criteria"],
        },
    }
    return defaults[lane]


def _workspace_matches_template(workspace: Path, required_paths: list[str]) -> bool:
    return all((workspace / relative_path).exists() for relative_path in required_paths)


def _write_full_bundle(workspace: Path, bundle: TemplateBundle) -> list[str]:
    changed_files: list[str] = []
    for relative_path, content in bundle.files.items():
        destination = workspace / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        current = _read_text_safe(destination) if destination.exists() else None
        if current != content:
            destination.write_text(content, encoding="utf-8")
            changed_files.append(relative_path)
    return changed_files


def _write_bundle_subset(workspace: Path, bundle: TemplateBundle, paths: list[str]) -> list[str]:
    changed_files: list[str] = []
    for relative_path in sorted(set(paths)):
        content = bundle.files.get(relative_path)
        if content is None:
            continue
        destination = workspace / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        current = _read_text_safe(destination) if destination.exists() else None
        if current != content:
            destination.write_text(content, encoding="utf-8")
            changed_files.append(relative_path)
    return changed_files


def _read_text_safe(path: Path) -> str:
    """Read path as text; use UTF-8 with replacement for invalid bytes so binary/non-UTF-8 files don't crash."""
    return path.read_text(encoding="utf-8", errors="replace")


def is_llm_text_file(path: Path, workspace: Path | None = None) -> bool:
    if not path.is_file():
        return False
    if path.name in EXCLUDED_REPO_FILES:
        return False
    if any(part in EXCLUDED_REPO_DIRS for part in path.parts):
        return False
    if workspace is not None:
        try:
            relative = path.relative_to(workspace)
        except ValueError:
            return False
        if any(part in EXCLUDED_REPO_DIRS for part in relative.parts):
            return False
        if relative.name in EXCLUDED_REPO_FILES:
            return False
    try:
        if path.stat().st_size > MAX_REPO_FILE_BYTES:
            return False
    except OSError:
        return False
    suffix = path.suffix.lower()
    if suffix in TEXT_FILE_EXTENSIONS:
        return True
    if "." not in path.name and path.name in {"Dockerfile", "Makefile"}:
        return True
    if path.name.lower().startswith("readme"):
        return True
    return False


def build_repo_manifest(workspace: Path) -> tuple[str, list[str], list[str]]:
    included: list[str] = []
    skipped: list[str] = []
    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(workspace).as_posix()
        if is_llm_text_file(path, workspace):
            included.append(relative)
        else:
            skipped.append(relative)
    lines = ["Repo manifest:", *included]
    if skipped:
        lines.append("")
        lines.append(f"Skipped files: {len(skipped)}")
    return "\n".join(lines), included, skipped


def build_repo_chunks(
    workspace: Path,
    *,
    max_chars_per_chunk: int = MAX_REPO_CHUNK_CHARS,
    max_chars_per_file: int = MAX_REPO_FILE_CHARS,
    max_total_chars: int = MAX_REPO_TOTAL_CHARS,
) -> tuple[list[RepoChunk], list[str], list[str]]:
    manifest, included, skipped = build_repo_manifest(workspace)
    chunks: list[RepoChunk] = []
    current_lines = [manifest, ""]
    current_files: list[str] = []
    current_chars = len(manifest) + 1
    total_chars = 0

    for relative in included:
        path = workspace / relative
        content = _read_text_safe(path)
        if len(content) > max_chars_per_file:
            content = content[:max_chars_per_file].rstrip() + "\n...<truncated>"
        entry = f"=== {relative} ===\n{content}\n"
        entry_len = len(entry)
        if total_chars + entry_len > max_total_chars:
            skipped.append(relative)
            continue
        if current_files and current_chars + entry_len > max_chars_per_chunk:
            chunks.append(RepoChunk(index=len(chunks) + 1, text="\n".join(current_lines).strip(), file_paths=current_files))
            current_lines = [manifest, ""]
            current_files = []
            current_chars = len(manifest) + 1
        current_lines.append(entry)
        current_files.append(relative)
        current_chars += entry_len
        total_chars += entry_len

    if current_files:
        chunks.append(RepoChunk(index=len(chunks) + 1, text="\n".join(current_lines).strip(), file_paths=current_files))
    return chunks, included, skipped


def _workspace_file_map(workspace: Path) -> dict[str, str]:
    files: dict[str, str] = {}
    for path in sorted(workspace.rglob("*")):
        if not path.is_file():
            continue
        relative_path = path.relative_to(workspace).as_posix()
        if relative_path == "records.json":
            continue
        files[relative_path] = _read_text_safe(path)
    return files
