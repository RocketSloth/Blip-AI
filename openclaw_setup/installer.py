"""
Needs-based installer.

Executes an InstallPlan step by step.  Each step handler knows how to run
the underlying shell command, capture output, and report success or failure.
Steps marked critical=True halt the plan on failure; others log a warning and
continue.
"""

import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Callable, Optional

from .planner import (
    STEP_DOCTOR,
    STEP_INSTALL_BIN,
    STEP_INSTALL_CHANNEL,
    STEP_INSTALL_OPENCLAW,
    STEP_INSTALL_SERVICE,
    STEP_RUN_ONBOARD,
    STEP_SET_ENV,
    STEP_VERIFY,
    STEP_WRITE_CONFIG,
    InstallPlan,
    PlanStep,
)


# ---------------------------------------------------------------------------
# Step result
# ---------------------------------------------------------------------------

@dataclass
class StepResult:
    step: PlanStep
    success: bool
    output: str = ""
    error: str = ""
    skipped: bool = False
    skip_reason: str = ""


@dataclass
class ExecutionReport:
    plan: InstallPlan
    results: list              # list[StepResult]
    halted: bool = False
    halt_reason: str = ""

    @property
    def succeeded(self) -> list:
        return [r for r in self.results if r.success and not r.skipped]

    @property
    def failed(self) -> list:
        return [r for r in self.results if not r.success and not r.skipped]

    @property
    def skipped(self) -> list:
        return [r for r in self.results if r.skipped]


# ---------------------------------------------------------------------------
# Shell runner
# ---------------------------------------------------------------------------

def _run_cmd(cmd: str, timeout: int = 120) -> tuple:
    """Run a shell command. Returns (success, stdout, stderr)."""
    try:
        result = subprocess.run(
            cmd,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", f"Command timed out after {timeout}s: {cmd}"
    except Exception as exc:
        return False, "", str(exc)


# ---------------------------------------------------------------------------
# Step handlers
# ---------------------------------------------------------------------------

PrintFn = Callable[[str], None]


def _handle_install_openclaw(step: PlanStep, print_fn: PrintFn) -> StepResult:
    cmd = step.args["cmd"]
    print_fn(f"  Running: {cmd}")
    ok, out, err = _run_cmd(cmd, timeout=300)
    return StepResult(step=step, success=ok, output=out, error=err)


def _handle_install_bin(step: PlanStep, print_fn: PrintFn) -> StepResult:
    cmd = step.args.get("cmd", "")
    if cmd.startswith("#"):
        # Manual step — can't automate
        print_fn(f"  Manual: {cmd.lstrip('# ')}")
        return StepResult(
            step=step,
            success=False,
            skipped=True,
            skip_reason="Manual installation required",
            error=cmd,
        )
    print_fn(f"  Running: {cmd}")
    ok, out, err = _run_cmd(cmd, timeout=300)
    return StepResult(step=step, success=ok, output=out, error=err)


def _handle_set_env(step: PlanStep, print_fn: PrintFn) -> StepResult:
    name = step.args["name"]
    val = os.environ.get(name)
    if val:
        return StepResult(step=step, success=True, output=f"{name} already set")
    guidance = step.args.get("guidance", [])
    msg = "\n    ".join(guidance) if guidance else f"Set the {name} environment variable."
    print_fn(f"  Waiting for {name}...")
    print_fn(f"  Guidance: {msg}")
    # Prompt interactively if stdin is a tty
    if sys.stdin.isatty():
        val = input(f"  Enter value for {name} (or press Enter to skip): ").strip()
        if val:
            os.environ[name] = val
            return StepResult(step=step, success=True, output=f"{name} set by user")
    return StepResult(
        step=step,
        success=False,
        skipped=True,
        skip_reason=f"{name} not set — configure manually before starting OpenClaw",
    )


def _handle_write_config(step: PlanStep, config_writer: Callable, print_fn: PrintFn) -> StepResult:
    fields = step.args["fields"]
    try:
        path = config_writer(fields)
        return StepResult(step=step, success=True, output=f"Config written to {path}")
    except Exception as exc:
        return StepResult(step=step, success=False, error=str(exc))


def _handle_run_onboard(step: PlanStep, print_fn: PrintFn) -> StepResult:
    cmd = step.args["cmd"]
    fallback = step.args.get("fallback", "openclaw setup --wizard")
    print_fn(f"  Running: {cmd}")
    ok, out, err = _run_cmd(cmd, timeout=120)
    if not ok:
        print_fn(f"  Non-interactive onboard failed, trying wizard...")
        ok, out, err = _run_cmd(fallback, timeout=300)
    return StepResult(step=step, success=ok, output=out, error=err)


def _handle_install_channel(step: PlanStep, print_fn: PrintFn) -> StepResult:
    cmd = step.args["cmd"]
    print_fn(f"  Running: {cmd}")
    ok, out, err = _run_cmd(cmd, timeout=120)
    return StepResult(step=step, success=ok, output=out, error=err)


def _handle_install_service(step: PlanStep, print_fn: PrintFn) -> StepResult:
    cmd = step.args["cmd"]
    print_fn(f"  Running: {cmd}")
    ok, out, err = _run_cmd(cmd, timeout=60)
    return StepResult(step=step, success=ok, output=out, error=err)


def _handle_verify(step: PlanStep, print_fn: PrintFn) -> StepResult:
    cmd = step.args["cmd"]
    print_fn(f"  Running: {cmd}")
    ok, out, err = _run_cmd(cmd, timeout=30)
    return StepResult(step=step, success=ok, output=out, error=err)


def _handle_doctor(step: PlanStep, print_fn: PrintFn) -> StepResult:
    cmd = step.args["cmd"]
    print_fn(f"  Running: {cmd}")
    ok, out, err = _run_cmd(cmd, timeout=60)
    return StepResult(step=step, success=ok, output=out, error=err)


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------

def execute_plan(
    plan: InstallPlan,
    config_writer: Callable,
    print_fn: Optional[PrintFn] = None,
    dry_run: bool = False,
) -> ExecutionReport:
    """
    Execute every step in the plan in order.

    config_writer: callable(fields: dict) -> path: str
    print_fn:      callable(msg: str) — defaults to print()
    dry_run:       if True, log steps without running them
    """
    if print_fn is None:
        print_fn = print

    report = ExecutionReport(plan=plan, results=[])

    handler_map = {
        STEP_INSTALL_OPENCLAW: lambda s: _handle_install_openclaw(s, print_fn),
        STEP_INSTALL_BIN: lambda s: _handle_install_bin(s, print_fn),
        STEP_SET_ENV: lambda s: _handle_set_env(s, print_fn),
        STEP_WRITE_CONFIG: lambda s: _handle_write_config(s, config_writer, print_fn),
        STEP_RUN_ONBOARD: lambda s: _handle_run_onboard(s, print_fn),
        STEP_INSTALL_CHANNEL: lambda s: _handle_install_channel(s, print_fn),
        STEP_INSTALL_SERVICE: lambda s: _handle_install_service(s, print_fn),
        STEP_VERIFY: lambda s: _handle_verify(s, print_fn),
        STEP_DOCTOR: lambda s: _handle_doctor(s, print_fn),
    }

    for step in plan.steps:
        print_fn(f"\n[{'DRY-RUN' if dry_run else 'RUN'}] {step.label}")

        if dry_run:
            result = StepResult(step=step, success=True, skipped=True, skip_reason="dry-run")
            report.results.append(result)
            continue

        handler = handler_map.get(step.action)
        if handler is None:
            result = StepResult(
                step=step,
                success=False,
                error=f"Unknown action: {step.action}",
            )
        else:
            result = handler(step)

        report.results.append(result)

        if result.skipped:
            print_fn(f"  SKIPPED: {result.skip_reason}")
            continue

        if result.success:
            if result.output:
                print_fn(f"  OK: {result.output[:200]}")
            else:
                print_fn("  OK")
        else:
            print_fn(f"  FAILED: {result.error[:300] if result.error else 'unknown error'}")
            if step.critical:
                report.halted = True
                report.halt_reason = f"Critical step failed: {step.label}"
                break

    return report


def format_report(report: ExecutionReport) -> str:
    """Return a human-readable final report."""
    lines = ["", "=" * 50, "Setup Report", "=" * 50]

    for result in report.results:
        if result.skipped:
            icon = "~"
        elif result.success:
            icon = "✓"
        else:
            icon = "✗"
        lines.append(f"  {icon} {result.step.label}")
        if not result.success and not result.skipped and result.error:
            lines.append(f"      → {result.error[:120]}")
        if result.skipped and result.skip_reason:
            lines.append(f"      → {result.skip_reason}")

    lines.append("")
    ok_count = len(report.succeeded)
    fail_count = len(report.failed)
    skip_count = len(report.skipped)

    lines.append(f"Installed: {ok_count}  Failed: {fail_count}  Skipped: {skip_count}")

    if report.halted:
        lines.append(f"\nSetup halted: {report.halt_reason}")
        lines.append("Run 'clawup --fix' or 'openclaw doctor' to diagnose.")
    elif fail_count == 0:
        lines.append("\nSetup complete.")
        lines.append("Next: openclaw logs --follow")
    else:
        lines.append("\nSetup finished with warnings.")
        lines.append("Run 'openclaw doctor' for repair suggestions.")

    lines.append("=" * 50)
    return "\n".join(lines)
