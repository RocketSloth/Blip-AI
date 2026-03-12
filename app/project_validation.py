from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
from typing import Iterable

from app.config import AgentSettings
from app.mvp_templates import build_template_bundle
from app.project_store import ActiveProject, HardGateResult, ValidationSummary


def validate_workspace(
    workspace: Path,
    project: ActiveProject,
    settings: AgentSettings,
    *,
    artifact_dir: Path | None = None,
) -> ValidationSummary:
    if project.lane == "unsupported":
        return ValidationSummary(
            status="failed",
            summary="Project lane is unsupported for MVP generation.",
            hard_gate_results=[
                HardGateResult(
                    key="supported_lane",
                    label="Supported lane",
                    passed=False,
                    details="Only ops copilots, intake approvals, and reporting dashboards are supported.",
                )
            ],
            failing_checks=["supported_lane"],
            next_task="Choose a supported B2B lane before building.",
        )

    bundle = build_template_bundle(project.title, project.product_brief)
    gate_results: list[HardGateResult] = []
    artifacts: dict[str, str] = {}

    gate_results.append(
        HardGateResult(
            key="scaffold_contract",
            label="Scaffold contract present",
            passed=_required_paths_exist(workspace, bundle.required_paths),
            details="All template files must exist.",
        )
    )

    import_check = _run_process(
        [sys.executable, "-c", "from app.main import app; print(app.title)"],
        workspace,
        settings.validation_timeout_seconds,
    )
    artifacts["import_check"] = _write_artifact(artifact_dir, "import-check.log", import_check.rendered_output)
    gate_results.append(
        HardGateResult(
            key="run_command",
            label="Run command imports app",
            passed=import_check.returncode == 0,
            details=_trim(import_check.rendered_output),
            artifact_path=artifacts["import_check"] or None,
        )
    )

    smoke = _run_pytest_case(
        workspace,
        "tests/test_app.py::test_homepage_smoke",
        settings.validation_timeout_seconds,
    )
    artifacts["smoke_test"] = _write_artifact(artifact_dir, "smoke-test.log", smoke.rendered_output)
    gate_results.append(
        HardGateResult(
            key="smoke_test",
            label="Smoke test passes",
            passed=smoke.returncode == 0,
            details=_trim(smoke.rendered_output),
            artifact_path=artifacts["smoke_test"] or None,
        )
    )

    seed = _run_pytest_case(
        workspace,
        "tests/test_app.py::test_seeded_demo_data",
        settings.validation_timeout_seconds,
    )
    artifacts["seed_test"] = _write_artifact(artifact_dir, "seed-test.log", seed.rendered_output)
    gate_results.append(
        HardGateResult(
            key="seed_data",
            label="Seeded demo data loads",
            passed=seed.returncode == 0,
            details=_trim(seed.rendered_output),
            artifact_path=artifacts["seed_test"] or None,
        )
    )

    workflow = _run_pytest_case(
        workspace,
        "tests/test_app.py::test_primary_workflow",
        settings.validation_timeout_seconds,
    )
    artifacts["workflow_test"] = _write_artifact(
        artifact_dir,
        "workflow-test.log",
        workflow.rendered_output,
    )
    gate_results.append(
        HardGateResult(
            key="workflow_test",
            label="Primary workflow test passes",
            passed=workflow.returncode == 0,
            details=_trim(workflow.rendered_output),
            artifact_path=artifacts["workflow_test"] or None,
        )
    )

    readme_ok = _readme_has_instructions(workspace / "README.md", bundle.run_command, bundle.test_command)
    gate_results.append(
        HardGateResult(
            key="readme_instructions",
            label="README contains local run instructions",
            passed=readme_ok,
            details="README must include install, run, and test commands.",
        )
    )

    passed_checks = [result.key for result in gate_results if result.passed]
    failing_checks = [result.key for result in gate_results if not result.passed]
    status = "passed" if not failing_checks else "failed"
    summary = (
        "All MVP validation gates passed."
        if status == "passed"
        else "Validation is failing on one or more MVP hard gates."
    )
    next_task = None
    if failing_checks:
        next_task = _next_task_from_failures(failing_checks)

    return ValidationSummary(
        run_at=project.last_cycle_at,
        status=status,
        summary=summary,
        hard_gate_results=gate_results,
        passed_checks=passed_checks,
        failing_checks=failing_checks,
        next_task=next_task,
        artifact_paths={key: value for key, value in artifacts.items() if value},
    )


def validation_gate_keys(summary: ValidationSummary) -> set[str]:
    return {result.key for result in summary.hard_gate_results if result.passed}


def all_hard_gates_pass(summary: ValidationSummary) -> bool:
    return bool(summary.hard_gate_results) and all(result.passed for result in summary.hard_gate_results)


def docs_only_change(changed_files: Iterable[str]) -> bool:
    non_doc_files = [
        path
        for path in changed_files
        if not path.lower().endswith((".md", ".txt", ".json"))
        or path.endswith("PRODUCT_BRIEF.json")
        or path.endswith("VALIDATION.json")
    ]
    return len(non_doc_files) == 0


class _RunResult:
    def __init__(self, returncode: int, rendered_output: str) -> None:
        self.returncode = returncode
        self.rendered_output = rendered_output


def _run_pytest_case(workspace: Path, test_target: str, timeout_seconds: int) -> _RunResult:
    return _run_process(
        [sys.executable, "-m", "pytest", test_target, "-q"],
        workspace,
        timeout_seconds,
    )


def _run_process(command: list[str], workspace: Path, timeout_seconds: int) -> _RunResult:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(workspace)
    try:
        result = subprocess.run(
            command,
            cwd=workspace,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            env=env,
        )
        output = "\n".join(item for item in [result.stdout, result.stderr] if item).strip()
        return _RunResult(result.returncode, output)
    except subprocess.TimeoutExpired as exc:
        output = f"Command timed out after {timeout_seconds}s.\n{exc.stdout or ''}\n{exc.stderr or ''}".strip()
        return _RunResult(124, output)


def _required_paths_exist(workspace: Path, required_paths: Iterable[str]) -> bool:
    return all((workspace / path).exists() for path in required_paths)


def _readme_has_instructions(readme_path: Path, run_command: str, test_command: str) -> bool:
    if not readme_path.exists():
        return False
    text = readme_path.read_text(encoding="utf-8")
    normalized = text.lower()
    return "pip install -r requirements.txt" in normalized and run_command in text and test_command in text


def _trim(text: str, limit: int = 300) -> str:
    stripped = text.strip()
    if len(stripped) <= limit:
        return stripped
    return stripped[:limit].rstrip() + "..."


def _write_artifact(artifact_dir: Path | None, name: str, content: str) -> str:
    if artifact_dir is None:
        return ""
    artifact_dir.mkdir(parents=True, exist_ok=True)
    path = artifact_dir / name
    path.write_text(content or "No output captured.", encoding="utf-8")
    return path.relative_to(artifact_dir.parent).as_posix()


def _next_task_from_failures(failing_checks: list[str]) -> str:
    mapping = {
        "scaffold_contract": "Rebuild the canonical scaffold for the selected lane.",
        "run_command": "Repair the FastAPI app import path and dependency contract.",
        "smoke_test": "Fix the homepage route and basic rendering path.",
        "seed_data": "Repair seed loading so demo data appears on startup.",
        "workflow_test": "Implement or repair the main workflow for the lane.",
        "readme_instructions": "Rewrite the README with accurate local setup steps.",
    }
    return mapping.get(failing_checks[0], "Repair the failing validation gates.")
