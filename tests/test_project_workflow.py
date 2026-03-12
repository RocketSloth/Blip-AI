from __future__ import annotations

import os
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from zipfile import ZipFile

from fastapi.testclient import TestClient

from app import main as main_module
from app.agent import (
    ProjectBuilderAgent,
    ProjectQualifierAgent,
    QualificationDecision,
    RefScore,
)
from app.bucket import BucketStore, ProjectIdea
from app.config import AgentSettings
from app.main import AgentRuntime
from app.project_store import (
    ActiveProjectStore,
    HardGateResult,
    ProductBrief,
    ProjectAttempt,
    ProjectFileOperation,
    ValidationSummary,
    idea_id_for_project,
)

os.environ.setdefault("OPENAI_API_KEY", "test-key")


def _supported_decision(lane: str) -> QualificationDecision:
    return QualificationDecision(
        supported=True,
        lane=lane,
        target_user="Operations lead",
        job_to_be_done="Run one clear workflow from queue to action",
        manual_workaround="Spreadsheet plus email",
        pain_severity="High",
        roi="Cuts follow-up time and missed work",
        must_have_flow="Open the main record and save the next step.",
        reason="Deterministic test qualification",
    )


def _brief_for_lane(title: str, lane: str) -> ProductBrief:
    if lane == "reporting-dashboard":
        return ProductBrief(
            lane=lane,
            title=title,
            opportunity_summary="A KPI dashboard with demo actions.",
            target_user="Operations analyst",
            job_to_be_done="Review metrics and create follow-up actions.",
            manual_workaround="Spreadsheet exports and a separate action tracker.",
            pain_severity="High",
            roi="Shortens reporting review cycles.",
            must_have_flow="Review KPIs, filter a team, and create a follow-up.",
            icp="SMB operations teams",
            problem="Metrics are disconnected from accountable next actions.",
            success_metric="Managers can inspect metrics and create a follow-up in one place.",
            required_entities=["Team metric", "Follow-up action"],
            must_have_screens=["Dashboard", "Detail", "Action list"],
            must_have_actions=["Filter", "Create action", "Export CSV"],
            demo_scenario="An analyst flags a team and creates a follow-up action.",
            acceptance_criteria=[
                "Dashboard renders seeded KPI data.",
                "A follow-up action can be created from the UI.",
                "Export works for the current view.",
            ],
        )
    if lane == "intake-approval":
        return ProductBrief(
            lane=lane,
            title=title,
            opportunity_summary="A reviewer queue for incoming requests.",
            target_user="Review coordinator",
            job_to_be_done="Review requests and record a decision.",
            manual_workaround="Email threads and approval spreadsheets.",
            pain_severity="High",
            roi="Cuts approval delays.",
            must_have_flow="Open a request, write a reviewer note, and save a decision.",
            icp="Teams with repeatable approval flows",
            problem="Approval status and reviewer notes live in different tools.",
            success_metric="A reviewer can process a request in one session.",
            required_entities=["Submission", "Decision", "Reviewer note"],
            must_have_screens=["Review queue", "Submission detail", "Status summary"],
            must_have_actions=["Approve", "Reject", "Capture note"],
            demo_scenario="A reviewer approves a vendor onboarding packet.",
            acceptance_criteria=[
                "Review queue shows seeded submissions.",
                "Saving a decision updates the record.",
                "Reviewer notes persist.",
            ],
        )
    return ProductBrief(
        lane=lane,
        title=title,
        opportunity_summary="An internal operations queue with follow-up tracking.",
        target_user="Operations lead",
        job_to_be_done="Review a queue item and save the next action.",
        manual_workaround="Shared spreadsheet and chat messages.",
        pain_severity="High",
        roi="Cuts queue triage time.",
        must_have_flow="Open a record, capture a note, and save an action taken.",
        icp="Operations-heavy SMBs",
        problem="Queue work loses context across spreadsheets and inboxes.",
        success_metric="A user can review and update a task in under two minutes.",
        required_entities=["Task", "Owner", "Status", "Follow-up note"],
        must_have_screens=["Priority queue", "Task detail", "Queue summary"],
        must_have_actions=["Update note", "Record action", "Review stats"],
        demo_scenario="An ops lead logs the next action on an escalated queue item.",
        acceptance_criteria=[
            "Priority queue renders seeded tasks.",
            "Detail page can save a new note and action.",
            "Workflow test passes under pytest.",
        ],
    )


def _passing_validation() -> ValidationSummary:
    gates = [
        HardGateResult(key="scaffold_contract", label="Scaffold", passed=True),
        HardGateResult(key="run_command", label="Run", passed=True),
        HardGateResult(key="smoke_test", label="Smoke", passed=True),
        HardGateResult(key="seed_data", label="Seed", passed=True),
        HardGateResult(key="workflow_test", label="Workflow", passed=True),
        HardGateResult(key="readme_instructions", label="README", passed=True),
    ]
    return ValidationSummary(
        status="passed",
        summary="All MVP validation gates passed.",
        hard_gate_results=gates,
        passed_checks=[gate.key for gate in gates],
        failing_checks=[],
    )


class ActiveProjectStoreTests(unittest.TestCase):
    def test_create_project_creates_workspace_and_rejects_duplicates(self) -> None:
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            store = ActiveProjectStore(
                manifest_path=str(base / "active_projects.json"),
                projects_root=str(base / "projects"),
            )
            idea = ProjectIdea(
                title="Ops Queue Helper",
                description="Lane: ops-copilot | User: ops lead",
                created_at="2026-03-12T00:00:00+00:00",
            )

            project = store.create_project(idea)

            self.assertTrue(store.workspace_path(project).exists())
            self.assertTrue(store.records_path(project).exists())
            self.assertTrue(store.product_brief_path(project).exists())
            self.assertTrue(store.validation_path(project).exists())

            with self.assertRaises(ValueError):
                store.create_project(idea)

    def test_attempts_are_recorded_and_returned_in_summary(self) -> None:
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            store = ActiveProjectStore(
                manifest_path=str(base / "active_projects.json"),
                projects_root=str(base / "projects"),
            )
            idea = ProjectIdea(
                title="Ops Queue Helper",
                description="Lane: ops-copilot | User: ops lead",
                created_at="2026-03-12T00:00:00+00:00",
            )
            project = store.create_project(idea)
            store.append_attempt(
                project,
                ProjectAttempt(
                    attempt_key="first-pass",
                    stage_name="pipeline",
                    builder_name="Build Pipeline",
                    summary="Refreshed scaffold and validation.",
                    changed_files=["README.md"],
                    baseline_score=0,
                    candidate_score=22,
                    decision="accepted",
                    reason="Improved MVP structure",
                    timestamp="2026-03-12T00:10:00+00:00",
                ),
            )

            summary = store.project_summary(project)

            self.assertEqual(len(summary["recent_attempts"]), 1)
            self.assertEqual(summary["recent_attempts"][0]["attempt_key"], "first-pass")
            self.assertEqual(store.known_attempt_fingerprints(project), {"first-pass"})

    def test_apply_file_operations_rejects_escape_paths(self) -> None:
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            with self.assertRaises(ValueError):
                ActiveProjectStore.apply_file_operations(
                    base,
                    [ProjectFileOperation(path="../escape.txt", action="create", content="bad")],
                )

    def test_build_project_archive_includes_workspace_files(self) -> None:
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            store = ActiveProjectStore(
                manifest_path=str(base / "active_projects.json"),
                projects_root=str(base / "projects"),
            )
            idea = ProjectIdea(
                title="Ops Queue Helper",
                description="Lane: ops-copilot | User: ops lead",
                created_at="2026-03-12T00:00:00+00:00",
            )
            project = store.create_project(idea)
            ActiveProjectStore.apply_file_operations(
                store.workspace_path(project),
                [
                    ProjectFileOperation(path="README.md", action="create", content="# Test"),
                    ProjectFileOperation(path="src/app.py", action="create", content="print('ok')"),
                ],
            )

            archive_bytes = store.build_project_archive(project)

            archive_path = base / "project.zip"
            archive_path.write_bytes(archive_bytes)
            with ZipFile(archive_path) as archive:
                names = set(archive.namelist())

            self.assertIn(f"{project.slug}/README.md", names)
            self.assertIn(f"{project.slug}/src/app.py", names)


class ProjectBuilderAgentTests(unittest.TestCase):
    def _make_agent(self, base: Path, lane: str = "ops-copilot") -> tuple[ProjectBuilderAgent, ActiveProjectStore]:
        bucket = BucketStore(file_path=str(base / "BUCKET.md"))
        store = ActiveProjectStore(
            manifest_path=str(base / "active_projects.json"),
            projects_root=str(base / "projects"),
        )
        settings = AgentSettings(openai_request_retries=0, openai_timeout_seconds=10, validation_timeout_seconds=40)
        agent = ProjectBuilderAgent(settings=settings, bucket=bucket, projects=store)
        agent.qualifier.qualify = lambda idea: _supported_decision(lane)
        agent.planner.plan = lambda idea, decision: _brief_for_lane(idea.title, lane)
        agent.ref.score = lambda project, workspace, validation: RefScore(
            score=82,
            reason="Deterministic passing score for test coverage.",
            strengths=["Runnable", "Seeded demo data", "Workflow passes"],
            gaps=["Could use more polish"],
        )
        return agent, store

    def test_qualification_fallback_rejects_unsupported_ideas(self) -> None:
        qualifier = ProjectQualifierAgent(AgentSettings(openai_request_retries=0))
        decision = qualifier._fallback_decision(
            ProjectIdea(
                title="AI negotiation coach",
                description="A coach for personal negotiation practice",
                created_at="2026-03-12T00:00:00+00:00",
            )
        )

        self.assertFalse(decision.supported)
        self.assertEqual(decision.lane, "unsupported")

    def test_promote_project_scaffolds_validated_workspace(self) -> None:
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            agent, store = self._make_agent(base, lane="ops-copilot")
            idea = ProjectIdea(
                title="Inspection queue copilot",
                description="Lane: ops-copilot | User: ops lead",
                created_at="2026-03-12T00:00:00+00:00",
            )

            result = agent.promote_project(idea)
            project = store.get_project(idea_id_for_project(idea))
            self.assertIsNotNone(project)
            assert project is not None

            workspace = store.workspace_path(project)
            self.assertTrue((workspace / "README.md").exists())
            self.assertTrue((workspace / "PROJECT_PLAN.md").exists())
            self.assertTrue((workspace / "app/main.py").exists())
            self.assertTrue((workspace / "tests/test_app.py").exists())
            self.assertTrue((workspace / "PRODUCT_BRIEF.json").exists())
            self.assertTrue((workspace / "VALIDATION.json").exists())
            self.assertEqual(project.lane, "ops-copilot")
            self.assertIn(project.stage, {"usable_mvp", "completed"})
            self.assertEqual(project.validation_status, "passed")
            self.assertGreater(project.current_score, 0)
            self.assertEqual(result["decision"], "accepted")

    def test_docs_only_changes_do_not_count_as_mvp_progress(self) -> None:
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            agent, _ = self._make_agent(base)

            accept, reason = agent._should_accept_candidate(
                changed_files=["README.md", "PROJECT_PLAN.md"],
                baseline_score=82,
                baseline_validation=_passing_validation(),
                candidate_score=RefScore(score=90, reason="Looks nicer"),
                candidate_validation=_passing_validation(),
            )

            self.assertFalse(accept)
            self.assertIn("README-only", reason)

    def test_duplicate_pipeline_attempt_is_skipped(self) -> None:
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            agent, store = self._make_agent(base, lane="ops-copilot")
            idea = ProjectIdea(
                title="Inspection queue copilot",
                description="Lane: ops-copilot | User: ops lead",
                created_at="2026-03-12T00:00:00+00:00",
            )
            agent.promote_project(idea)
            project_id = idea_id_for_project(idea)

            first = agent.run_cycle(project_id, manual=True)
            second = agent.run_cycle(project_id, manual=True)

            self.assertEqual(first["decision"], "no_change")
            self.assertEqual(second["decision"], "skipped_duplicate")
            project = store.get_project(project_id)
            assert project is not None
            attempts = store.load_attempts(project)
            self.assertEqual(attempts[-1].decision, "skipped_duplicate")


class ApiSmokeTests(unittest.TestCase):
    def test_select_build_validate_and_artifact_routes(self) -> None:
        with TemporaryDirectory() as tmpdir:
            base = Path(tmpdir)
            runtime = AgentRuntime()
            runtime.bucket = BucketStore(file_path=str(base / "BUCKET.md"))
            runtime.project_store = ActiveProjectStore(
                manifest_path=str(base / "active_projects.json"),
                projects_root=str(base / "projects"),
            )
            runtime.project_agent = ProjectBuilderAgent(
                settings=runtime.settings,
                bucket=runtime.bucket,
                projects=runtime.project_store,
            )
            runtime.project_agent.qualifier.qualify = lambda idea: _supported_decision("reporting-dashboard")
            runtime.project_agent.planner.plan = lambda idea, decision: _brief_for_lane(idea.title, "reporting-dashboard")
            runtime.project_agent.ref.score = lambda project, workspace, validation: RefScore(
                score=85,
                reason="API test score",
                strengths=["Renders", "Validates"],
                gaps=[],
            )

            async def _noop() -> None:
                return None

            runtime.start = _noop
            runtime.stop = _noop

            idea = ProjectIdea(
                title="Productivity analytics dashboard",
                description="Lane: reporting-dashboard | User: ops analyst",
                created_at="2026-03-12T00:00:00+00:00",
            )
            runtime.bucket.append_run([idea], [])

            original_runtime = main_module.runtime
            main_module.runtime = runtime
            try:
                with TestClient(main_module.app) as client:
                    select_response = client.post(
                        "/api/projects/select",
                        json={"idea_id": idea_id_for_project(idea)},
                    )
                    self.assertEqual(select_response.status_code, 200)

                    state_response = client.get("/api/state")
                    self.assertEqual(state_response.status_code, 200)
                    state_payload = state_response.json()
                    self.assertEqual(len(state_payload["active_projects"]), 1)
                    project = state_payload["active_projects"][0]
                    self.assertEqual(project["lane"], "reporting-dashboard")
                    self.assertIn(project["stage"], {"usable_mvp", "completed"})

                    project_id = project["id"]
                    build_response = client.post(f"/api/projects/{project_id}/build")
                    self.assertEqual(build_response.status_code, 200)

                    validate_response = client.post(f"/api/projects/{project_id}/validate")
                    self.assertEqual(validate_response.status_code, 200)

                    detail_response = client.get(f"/api/projects/{project_id}")
                    self.assertEqual(detail_response.status_code, 200)
                    detail_payload = detail_response.json()
                    self.assertTrue(detail_payload["hard_gate_results"])

                    artifact_path = detail_payload["validation_artifacts"].get("import_check")
                    self.assertTrue(artifact_path)
                    artifact_response = client.get(f"/api/projects/{project_id}/artifacts/{artifact_path}")
                    self.assertEqual(artifact_response.status_code, 200)

                    download_response = client.get(f"/api/projects/{project_id}/download")
                    self.assertEqual(download_response.status_code, 200)
            finally:
                main_module.runtime = original_runtime


if __name__ == "__main__":
    unittest.main()
