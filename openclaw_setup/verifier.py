"""
Post-setup verification and repair layer.

After the installer finishes, this runs the full readiness suite:
  1. Binary presence check (required bins from plan)
  2. openclaw gateway status
  3. openclaw doctor
  4. Channel-level smoke test (if applicable)
  5. Env var validation

Produces a VerificationReport with a clear status for each check.
"""

import os
import subprocess
from dataclasses import dataclass, field
from typing import Optional

from .planner import InstallPlan


# ---------------------------------------------------------------------------
# Check status constants
# ---------------------------------------------------------------------------

STATUS_OK = "ok"
STATUS_MISSING = "missing"
STATUS_MISCONFIGURED = "misconfigured"
STATUS_FIXED = "fixed"
STATUS_NEEDS_INPUT = "needs_input"
STATUS_SKIPPED = "skipped"


@dataclass
class CheckResult:
    name: str
    status: str           # one of the STATUS_* constants
    detail: str = ""
    fix_suggestion: str = ""


@dataclass
class VerificationReport:
    checks: list          # list[CheckResult]
    gateway_running: bool = False
    doctor_passed: bool = False
    channel_ok: bool = False

    @property
    def fully_ready(self) -> bool:
        bad = {STATUS_MISSING, STATUS_MISCONFIGURED, STATUS_NEEDS_INPUT}
        return all(c.status not in bad for c in self.checks)

    def summary_lines(self) -> list:
        lines = []
        for c in self.checks:
            icon = {
                STATUS_OK: "✓",
                STATUS_MISSING: "✗",
                STATUS_MISCONFIGURED: "!",
                STATUS_FIXED: "~",
                STATUS_NEEDS_INPUT: "?",
                STATUS_SKIPPED: "-",
            }.get(c.status, "?")
            line = f"  {icon} {c.name}"
            if c.detail:
                line += f": {c.detail}"
            lines.append(line)
            if c.fix_suggestion and c.status not in (STATUS_OK, STATUS_SKIPPED):
                lines.append(f"      fix: {c.fix_suggestion}")
        return lines


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _run(cmd: str, timeout: int = 30) -> tuple:
    try:
        r = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except Exception as exc:
        return False, "", str(exc)


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_binary(name: str, check_cmd: str) -> CheckResult:
    ok, out, err = _run(check_cmd, timeout=5)
    if ok:
        version = out.split("\n")[0][:60]
        return CheckResult(name=f"binary:{name}", status=STATUS_OK, detail=version)
    return CheckResult(
        name=f"binary:{name}",
        status=STATUS_MISSING,
        detail=f"'{name}' not found or not working",
        fix_suggestion=f"Install {name} and ensure it is on PATH",
    )


def _check_env_var(name: str) -> CheckResult:
    val = os.environ.get(name)
    if val:
        masked = val[:4] + "..." if len(val) > 4 else "***"
        return CheckResult(name=f"env:{name}", status=STATUS_OK, detail=masked)
    return CheckResult(
        name=f"env:{name}",
        status=STATUS_NEEDS_INPUT,
        detail="not set",
        fix_suggestion=f"export {name}=<your-value>",
    )


def _check_gateway_status() -> CheckResult:
    ok, out, err = _run("openclaw gateway status", timeout=15)
    if ok:
        return CheckResult(name="gateway:status", status=STATUS_OK, detail=out[:120] or "running")
    detail = (out or err)[:120]
    fix = "Run: openclaw gateway start  or  openclaw onboard --mode local"
    return CheckResult(
        name="gateway:status",
        status=STATUS_MISCONFIGURED,
        detail=detail or "gateway not running",
        fix_suggestion=fix,
    )


def _check_doctor() -> CheckResult:
    ok, out, err = _run("openclaw doctor", timeout=30)
    combined = (out + " " + err).strip()[:200]
    if ok:
        return CheckResult(name="openclaw:doctor", status=STATUS_OK, detail=combined or "all clear")
    return CheckResult(
        name="openclaw:doctor",
        status=STATUS_MISCONFIGURED,
        detail=combined or "doctor reported issues",
        fix_suggestion="Follow the suggestions printed by 'openclaw doctor'",
    )


def _check_channel(channel_id: str, smoke_cmd: str) -> CheckResult:
    ok, out, err = _run(smoke_cmd, timeout=20)
    if ok:
        return CheckResult(name=f"channel:{channel_id}", status=STATUS_OK, detail="smoke test passed")
    detail = (out or err)[:120]
    return CheckResult(
        name=f"channel:{channel_id}",
        status=STATUS_MISCONFIGURED,
        detail=detail or "smoke test failed",
        fix_suggestion=f"Check channel config or run: openclaw plugin install {channel_id}",
    )


# ---------------------------------------------------------------------------
# Main verifier
# ---------------------------------------------------------------------------

def run_verification(plan: InstallPlan) -> VerificationReport:
    """
    Run the full verification suite against the installed plan.
    Returns a VerificationReport with per-check statuses.
    """
    checks: list = []

    # 1. Required binaries (from provider + channel)
    all_bins = list(plan.provider.required_bins)
    if plan.channel:
        all_bins += plan.channel.required_bins

    # Always check openclaw itself
    from .manifests import OPENCLAW_BIN
    all_bins = [OPENCLAW_BIN] + all_bins

    seen_bins: set = set()
    for req in all_bins:
        if req.name in seen_bins:
            continue
        seen_bins.add(req.name)
        checks.append(_check_binary(req.name, req.check_cmd))

    # 2. Env vars
    all_env = list(plan.provider.required_env)
    if plan.channel:
        all_env += plan.channel.required_env
    for name in all_env:
        checks.append(_check_env_var(name))

    # 3. Gateway status
    gw_check = _check_gateway_status()
    checks.append(gw_check)
    gateway_running = gw_check.status == STATUS_OK

    # 4. Doctor
    doc_check = _check_doctor()
    checks.append(doc_check)
    doctor_passed = doc_check.status == STATUS_OK

    # 5. Channel smoke test
    channel_ok = False
    if plan.channel and plan.channel.smoke_test_cmd:
        ch_check = _check_channel(plan.channel.id, plan.channel.smoke_test_cmd)
        checks.append(ch_check)
        channel_ok = ch_check.status == STATUS_OK
    elif plan.channel:
        checks.append(CheckResult(
            name=f"channel:{plan.channel.id}",
            status=STATUS_SKIPPED,
            detail="no smoke test defined",
        ))

    return VerificationReport(
        checks=checks,
        gateway_running=gateway_running,
        doctor_passed=doctor_passed,
        channel_ok=channel_ok,
    )


def format_verification(report: VerificationReport) -> str:
    """Return a human-readable verification summary."""
    lines = ["", "Verification:", ""]
    lines.extend(report.summary_lines())
    lines.append("")
    if report.fully_ready:
        lines.append("System ready.")
    else:
        bad = [c for c in report.checks if c.status in (STATUS_MISSING, STATUS_MISCONFIGURED, STATUS_NEEDS_INPUT)]
        lines.append(f"{len(bad)} issue(s) require attention.")
        lines.append("Run 'openclaw doctor' for automated repair suggestions.")
    return "\n".join(lines)
