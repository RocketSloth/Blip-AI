"""
Capability planner.

Given the user's profile, provider, and channel choices (plus the system
detection results), builds an ordered InstallPlan — a dependency graph of
exactly what needs to happen and in which order.

Rule set (from the design doc):
  1. core CLI first
  2. provider auth second
  3. exactly one channel next
  4. optional skills last
"""

from dataclasses import dataclass, field
from typing import Optional

from .detector import SystemInfo
from .manifests import (
    CHANNELS,
    OPENCLAW_BIN,
    PROFILES,
    PROVIDERS,
    BinaryRequirement,
    ChannelManifest,
    InstallMethod,
    ProfileManifest,
    ProviderManifest,
)


# ---------------------------------------------------------------------------
# Plan step types
# ---------------------------------------------------------------------------

STEP_INSTALL_OPENCLAW = "install_openclaw"
STEP_INSTALL_BIN = "install_bin"
STEP_SET_ENV = "set_env"
STEP_WRITE_CONFIG = "write_config"
STEP_RUN_ONBOARD = "run_onboard"
STEP_INSTALL_SERVICE = "install_service"
STEP_INSTALL_CHANNEL = "install_channel"
STEP_VERIFY = "verify"
STEP_DOCTOR = "doctor"


@dataclass
class PlanStep:
    action: str           # one of the STEP_* constants
    label: str            # human-readable description
    args: dict = field(default_factory=dict)
    critical: bool = True  # if True, halt on failure


@dataclass
class InstallPlan:
    profile: ProfileManifest
    provider: ProviderManifest
    channel: Optional[ChannelManifest]
    install_service: bool
    system: SystemInfo
    steps: list           # list[PlanStep] — ordered execution plan
    missing_env: list     # list[str] — env vars user must set manually
    notes: list           # list[str] — additional guidance notes


def _best_install_method(req: BinaryRequirement, available_pkg_managers: list) -> Optional[str]:
    """
    Pick the best install command for a binary given available package managers.
    Preference order follows the manifest's install_methods list.
    Falls back to the first available method.
    """
    for method in req.install_methods:
        if method.tool in available_pkg_managers or method.tool in ("script", "download"):
            return method.command
    if req.install_methods:
        return req.install_methods[0].command
    return None


def build_plan(
    profile_id: str,
    provider_id: str,
    install_service: bool,
    system: SystemInfo,
    dry_run: bool = False,
) -> InstallPlan:
    """
    Build a full install plan for the given choices + system state.

    profile_id:      one of PROFILES keys
    provider_id:     one of PROVIDERS keys
    install_service: whether to install the openclaw daemon
    system:          SystemInfo from detector.run_detection()
    dry_run:         if True, no destructive steps are added
    """
    profile = PROFILES[profile_id]
    provider = PROVIDERS[provider_id]
    channel = CHANNELS[profile.channel_id] if profile.channel_id else None

    steps: list = []
    missing_env: list = []
    notes: list = []

    # --- Step 1: OpenClaw CLI ---
    if system.openclaw_version is None:
        install_cmd = _best_install_method(OPENCLAW_BIN, system.package_managers)
        steps.append(
            PlanStep(
                action=STEP_INSTALL_OPENCLAW,
                label="Install OpenClaw CLI",
                args={"cmd": install_cmd or "npm install -g openclaw"},
                critical=True,
            )
        )

    # --- Step 2: Runtime binaries required by provider ---
    for req in provider.required_bins:
        if req.name not in system.found_bins:
            cmd = _best_install_method(req, system.package_managers)
            steps.append(
                PlanStep(
                    action=STEP_INSTALL_BIN,
                    label=f"Install {req.name}",
                    args={"binary": req.name, "cmd": cmd or f"# install {req.name} manually"},
                    critical=True,
                )
            )

    # --- Step 3: Runtime binaries required by channel ---
    if channel:
        for req in channel.required_bins:
            if req.name not in system.found_bins:
                cmd = _best_install_method(req, system.package_managers)
                steps.append(
                    PlanStep(
                        action=STEP_INSTALL_BIN,
                        label=f"Install {req.name} (required by {channel.label})",
                        args={"binary": req.name, "cmd": cmd or f"# install {req.name} manually"},
                        critical=True,
                    )
                )

    # --- Step 4: Provider env vars ---
    for env_name in provider.required_env:
        if env_name not in system.present_env:
            missing_env.append(env_name)
            notes.extend(provider.setup_notes)
            steps.append(
                PlanStep(
                    action=STEP_SET_ENV,
                    label=f"Set {env_name}",
                    args={"name": env_name, "guidance": provider.setup_notes},
                    critical=True,
                )
            )

    # --- Step 5: Channel env vars ---
    if channel:
        for env_name in channel.required_env:
            if env_name not in system.present_env:
                missing_env.append(env_name)
                notes.extend(channel.setup_steps)
                steps.append(
                    PlanStep(
                        action=STEP_SET_ENV,
                        label=f"Set {env_name}",
                        args={"name": env_name, "guidance": channel.setup_steps},
                        critical=True,
                    )
                )

    # --- Step 6: Write minimal config ---
    config_fields: dict = {}
    config_fields.update(provider.config_fields)
    if channel:
        config_fields.update(channel.config_fields)
    config_fields["workspace"] = "~/.openclaw"
    if install_service:
        config_fields["service.enabled"] = True

    steps.append(
        PlanStep(
            action=STEP_WRITE_CONFIG,
            label="Write minimal OpenClaw config",
            args={"fields": config_fields},
            critical=True,
        )
    )

    # --- Step 7: Run openclaw onboard non-interactively ---
    gateway_mode = config_fields.get("gateway.mode", "local")
    steps.append(
        PlanStep(
            action=STEP_RUN_ONBOARD,
            label="Run openclaw onboard (non-interactive)",
            args={
                "cmd": f"openclaw onboard --mode {gateway_mode} --no-interactive",
                "fallback": f"openclaw setup --wizard",
            },
            critical=False,  # fall back to wizard if non-interactive flag not supported
        )
    )

    # --- Step 8: Install channel plugin ---
    if channel and channel.id != "local":
        steps.append(
            PlanStep(
                action=STEP_INSTALL_CHANNEL,
                label=f"Install OpenClaw {channel.label} plugin",
                args={
                    "channel": channel.id,
                    "cmd": f"openclaw plugin install {channel.id}",
                },
                critical=True,
            )
        )

    # --- Step 9: Install background service ---
    if install_service:
        steps.append(
            PlanStep(
                action=STEP_INSTALL_SERVICE,
                label="Install OpenClaw gateway service",
                args={"cmd": "openclaw service install"},
                critical=False,
            )
        )

    # --- Step 10: Verify ---
    steps.append(
        PlanStep(
            action=STEP_VERIFY,
            label="Check gateway status",
            args={"cmd": "openclaw gateway status"},
            critical=False,
        )
    )

    # --- Step 11: Doctor ---
    steps.append(
        PlanStep(
            action=STEP_DOCTOR,
            label="Run openclaw doctor",
            args={"cmd": "openclaw doctor"},
            critical=False,
        )
    )

    # Channel-level smoke test
    if channel and channel.smoke_test_cmd:
        steps.append(
            PlanStep(
                action=STEP_VERIFY,
                label=f"Smoke test: {channel.label}",
                args={"cmd": channel.smoke_test_cmd},
                critical=False,
            )
        )

    return InstallPlan(
        profile=profile,
        provider=provider,
        channel=channel,
        install_service=install_service,
        system=system,
        steps=steps,
        missing_env=missing_env,
        notes=list(dict.fromkeys(notes)),  # deduplicate while preserving order
    )


def summarise_plan(plan: InstallPlan) -> str:
    """Return a human-readable summary of the plan."""
    lines = [
        f"Profile  : {plan.profile.label}",
        f"Provider : {plan.provider.label}",
        f"Channel  : {plan.channel.label if plan.channel else 'none'}",
        f"Service  : {'yes' if plan.install_service else 'no'}",
        "",
        "Steps:",
    ]
    for i, step in enumerate(plan.steps, 1):
        lines.append(f"  {i:2d}. {step.label}")
    if plan.missing_env:
        lines += ["", "Env vars you must supply:"]
        for name in plan.missing_env:
            lines.append(f"  - {name}")
    if plan.notes:
        lines += ["", "Notes:"]
        for note in plan.notes:
            lines.append(f"  • {note}")
    return "\n".join(lines)
