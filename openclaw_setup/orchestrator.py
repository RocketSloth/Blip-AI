"""
Main setup orchestrator.

Coordinates the full guided setup flow:
  1. Welcome banner
  2. Interactive Q&A (profile, provider, service)
  3. System detection
  4. Dependency planning
  5. Plan preview + confirmation
  6. Installation
  7. Verification
  8. Final report

Can also run in non-interactive mode (all args supplied upfront) or
dry-run mode (plan only, no execution).
"""

import sys
from dataclasses import dataclass
from typing import Optional

from .config_gen import preview_config, write_config
from .detector import run_detection
from .installer import ExecutionReport, execute_plan, format_report
from .manifests import CHANNELS, PROFILES, PROVIDERS, BinaryRequirement
from .planner import InstallPlan, build_plan, summarise_plan
from .verifier import VerificationReport, format_verification, run_verification


# ---------------------------------------------------------------------------
# ANSI helpers (no external deps)
# ---------------------------------------------------------------------------

_USE_COLOR = sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    if not _USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"


def green(t: str) -> str:  return _c(t, "32")
def red(t: str) -> str:    return _c(t, "31")
def yellow(t: str) -> str: return _c(t, "33")
def bold(t: str) -> str:   return _c(t, "1")
def dim(t: str) -> str:    return _c(t, "2")


def _print(msg: str = "") -> None:
    print(msg)


def _banner() -> None:
    _print(bold("=" * 56))
    _print(bold("  clawup — OpenClaw guided setup orchestrator"))
    _print(bold("=" * 56))
    _print()


# ---------------------------------------------------------------------------
# Q&A helpers
# ---------------------------------------------------------------------------

def _pick(prompt: str, choices: list, default: int = 0) -> int:
    """
    Display a numbered menu and return the chosen index (0-based).
    choices: list of (id, label) tuples
    """
    _print(prompt)
    for i, (cid, label) in enumerate(choices, 1):
        marker = "  " if i - 1 != default else "> "
        _print(f"{marker}{i}. {label}")
    _print()
    while True:
        raw = input(f"Choice [1-{len(choices)}] (default {default + 1}): ").strip()
        if not raw:
            return default
        try:
            n = int(raw)
            if 1 <= n <= len(choices):
                return n - 1
        except ValueError:
            pass
        _print(f"  Enter a number between 1 and {len(choices)}.")


def _confirm(prompt: str, default: bool = True) -> bool:
    suffix = "[Y/n]" if default else "[y/N]"
    raw = input(f"{prompt} {suffix}: ").strip().lower()
    if not raw:
        return default
    return raw in ("y", "yes")


# ---------------------------------------------------------------------------
# Setup flow
# ---------------------------------------------------------------------------

@dataclass
class SetupChoices:
    profile_id: str
    provider_id: str
    install_service: bool


def _ask_questions(
    profile_id: Optional[str] = None,
    provider_id: Optional[str] = None,
    install_service: Optional[bool] = None,
) -> SetupChoices:
    """Interactive Q&A. Pre-supplied args skip those questions."""

    # Profile
    if profile_id is None:
        profile_choices = [(pid, p.label) for pid, p in PROFILES.items()]
        idx = _pick("What do you want to use OpenClaw for?", profile_choices)
        profile_id = profile_choices[idx][0]
    profile = PROFILES[profile_id]
    _print(f"  → {green(profile.label)}: {profile.description}")
    _print()

    # Provider
    if provider_id is None:
        provider_choices = [
            (pid, PROVIDERS[pid].label)
            for pid in profile.provider_choices
            if pid in PROVIDERS
        ]
        idx = _pick("Which model provider?", provider_choices)
        provider_id = provider_choices[idx][0]
    _print(f"  → Provider: {green(PROVIDERS[provider_id].label)}")
    _print()

    # Service
    if install_service is None:
        install_service = _confirm(
            "Install background service (gateway daemon)?",
            default=profile.install_service_default,
        )
    _print()

    return SetupChoices(
        profile_id=profile_id,
        provider_id=provider_id,
        install_service=install_service,
    )


def _show_detection(system) -> None:
    _print(bold("Checking system..."))
    _print(f"  OS   : {system.os_name} ({system.arch})")
    _print(f"  Pkg  : {', '.join(system.package_managers) or 'none detected'}")
    _print()

    if system.openclaw_version:
        _print(f"  {green('✓')} openclaw {system.openclaw_version}")
    else:
        _print(f"  {red('✗')} openclaw not installed")

    for name, path in system.found_bins.items():
        _print(f"  {green('✓')} {name} ({path})")

    for req in system.missing_bins:
        _print(f"  {red('✗')} {req.name} not found")

    for name in system.missing_env:
        _print(f"  {yellow('?')} {name} not set")

    _print()


def _show_plan(plan: InstallPlan) -> None:
    _print(bold("Plan:"))
    for step in plan.steps:
        _print(f"  - {step.label}")
    if plan.missing_env:
        _print()
        _print(yellow("  You will be prompted for:"))
        for name in plan.missing_env:
            _print(f"    • {name}")
    _print()


def _config_writer(fields: dict) -> str:
    """Passed to installer as the config_writer callable."""
    return write_config(fields)


def run_setup(
    profile_id: Optional[str] = None,
    provider_id: Optional[str] = None,
    install_service: Optional[bool] = None,
    dry_run: bool = False,
    fix_only: bool = False,
    non_interactive: bool = False,
    config_path: Optional[str] = None,
) -> int:
    """
    Main setup entry point.

    Returns an exit code: 0 = success, 1 = failure.
    """
    _banner()

    # --- Fix-only mode: run doctor and verify without full setup ---
    if fix_only:
        _print(bold("Running repair mode..."))
        _print()
        import subprocess
        subprocess.run("openclaw doctor", shell=True)
        return 0

    # --- Q&A ---
    if non_interactive:
        # Use defaults if not supplied
        profile_id = profile_id or "personal_bot"
        provider_id = provider_id or "openai"
        if install_service is None:
            install_service = PROFILES[profile_id].install_service_default
        choices = SetupChoices(profile_id, provider_id, install_service)
    else:
        try:
            choices = _ask_questions(profile_id, provider_id, install_service)
        except (EOFError, KeyboardInterrupt):
            _print("\nSetup cancelled.")
            return 1

    # --- Detection ---
    profile = PROFILES[choices.profile_id]
    provider = PROVIDERS[choices.provider_id]
    channel = CHANNELS[profile.channel_id] if profile.channel_id else None

    all_bins: list = []
    all_bins += provider.required_bins
    if channel:
        all_bins += channel.required_bins

    all_env: list = list(provider.required_env)
    if channel:
        all_env += channel.required_env

    system = run_detection(required_bins=all_bins, required_env=all_env)
    _show_detection(system)

    # --- Plan ---
    plan = build_plan(
        profile_id=choices.profile_id,
        provider_id=choices.provider_id,
        install_service=choices.install_service,
        system=system,
        dry_run=dry_run,
    )
    _show_plan(plan)

    # --- Config preview ---
    if plan.steps:
        config_fields: dict = {}
        config_fields.update(provider.config_fields)
        if channel:
            config_fields.update(channel.config_fields)
        config_fields["workspace"] = "~/.openclaw"
        if choices.install_service:
            config_fields["service.enabled"] = True

        _print(dim("Config to be written:"))
        for line in preview_config(config_fields).splitlines():
            _print(dim(f"  {line}"))
        _print()

    # --- Confirm before executing ---
    if not dry_run and not non_interactive:
        try:
            if not _confirm("Proceed with setup?", default=True):
                _print("Setup cancelled.")
                return 0
        except (EOFError, KeyboardInterrupt):
            _print("\nSetup cancelled.")
            return 1
        _print()

    # --- Execute ---
    if dry_run:
        _print(bold("[DRY RUN — no changes will be made]"))
        _print()

    report: ExecutionReport = execute_plan(
        plan=plan,
        config_writer=_config_writer,
        print_fn=_print,
        dry_run=dry_run,
    )

    _print(format_report(report))

    if report.halted:
        return 1

    # --- Verify ---
    if not dry_run:
        _print()
        _print(bold("Verifying..."))
        vr: VerificationReport = run_verification(plan)
        _print(format_verification(vr))

        if not vr.fully_ready:
            return 1

    return 0
