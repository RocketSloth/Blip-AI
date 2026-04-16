"""
FastAPI wizard server.

Serves a browser-based guided setup UI backed by the same planner, installer,
verifier, and config generator used by the CLI.  Install jobs run in a
background thread and stream progress to the browser via Server-Sent Events.
"""

from __future__ import annotations

import asyncio
import json
import os
import queue
import threading
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    StreamingResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..config_gen import preview_config, write_config
from ..detector import run_detection
from ..installer import execute_plan
from ..manifests import CHANNELS, PROFILES, PROVIDERS
from ..planner import InstallPlan, build_plan
from ..verifier import run_verification


STATIC_DIR = Path(__file__).parent / "static"


# ---------------------------------------------------------------------------
# Friendly labels / copy (plain English, no jargon)
# ---------------------------------------------------------------------------

PROFILE_COPY = {
    "personal_bot": {
        "title": "On my computer",
        "blurb": "A private AI chat that runs on this machine. Nothing leaves your device except the chats you send to the AI.",
        "icon": "💻",
    },
    "telegram_bot": {
        "title": "On Telegram",
        "blurb": "Chat with your AI from Telegram, like any other bot. Works on your phone too.",
        "icon": "✈️",
    },
    "whatsapp_bot": {
        "title": "On WhatsApp",
        "blurb": "Talk to your AI from WhatsApp. You'll scan a QR code to link it.",
        "icon": "💬",
    },
    "remote_gateway": {
        "title": "On a server",
        "blurb": "Advanced. Headless setup for a VPS or home server.",
        "icon": "🖥️",
    },
    "dev_setup": {
        "title": "For development",
        "blurb": "Advanced. Verbose logging, no background service.",
        "icon": "🧰",
    },
}

PROVIDER_COPY = {
    "openai": {
        "title": "OpenAI",
        "blurb": "ChatGPT's maker. Most popular — works well out of the box.",
        "key_url": "https://platform.openai.com/api-keys",
        "key_label": "API key",
        "key_hint": "Starts with sk-",
    },
    "anthropic": {
        "title": "Anthropic",
        "blurb": "Claude's maker. Great for long conversations and writing.",
        "key_url": "https://console.anthropic.com/settings/keys",
        "key_label": "API key",
        "key_hint": "Starts with sk-ant-",
    },
    "openrouter": {
        "title": "OpenRouter",
        "blurb": "One key to access many different AI models.",
        "key_url": "https://openrouter.ai/keys",
        "key_label": "API key",
        "key_hint": "Starts with sk-or-",
    },
    "local": {
        "title": "Run locally (free)",
        "blurb": "Uses Ollama to run AI on your own machine. No API key, no cost — but slower.",
        "key_url": "https://ollama.com/download",
        "key_label": "",
        "key_hint": "Download Ollama first, then come back here.",
    },
}

ENV_COPY = {
    "OPENAI_API_KEY": {
        "label": "Your OpenAI API key",
        "help": "Get one at https://platform.openai.com/api-keys",
        "placeholder": "sk-...",
    },
    "ANTHROPIC_API_KEY": {
        "label": "Your Anthropic API key",
        "help": "Get one at https://console.anthropic.com/settings/keys",
        "placeholder": "sk-ant-...",
    },
    "OPENROUTER_API_KEY": {
        "label": "Your OpenRouter API key",
        "help": "Get one at https://openrouter.ai/keys",
        "placeholder": "sk-or-...",
    },
    "TELEGRAM_BOT_TOKEN": {
        "label": "Your Telegram bot token",
        "help": "Open @BotFather in Telegram, send /newbot, and paste the token it gives you.",
        "placeholder": "123456789:AAH...",
    },
}


# ---------------------------------------------------------------------------
# Job management
# ---------------------------------------------------------------------------

@dataclass
class Job:
    id: str
    status: str = "pending"                # pending, running, done, failed
    events: queue.Queue = field(default_factory=queue.Queue)
    plan: Optional[InstallPlan] = None
    success_count: int = 0
    fail_count: int = 0
    skip_count: int = 0
    halted: bool = False
    halt_reason: str = ""
    verification_ready: bool = False


_JOBS: dict = {}
_JOBS_LOCK = threading.Lock()


def _emit(job: Job, event_type: str, data: dict) -> None:
    payload = {"type": event_type, **data}
    job.events.put(payload)


def _run_job(job: Job) -> None:
    """Run the install plan in a background thread, pushing events as it goes."""
    job.status = "running"
    step_index = [0]

    def step_print(msg: str) -> None:
        # Heuristic: lines starting with '[' are step headers
        line = msg.rstrip()
        if not line:
            return
        if line.startswith("[RUN]") or line.startswith("[DRY-RUN]"):
            label = line.split("] ", 1)[-1]
            _emit(job, "step_start", {"index": step_index[0], "label": label})
            step_index[0] += 1
        else:
            _emit(job, "log", {"text": line})

    try:
        assert job.plan is not None
        report = execute_plan(
            plan=job.plan,
            config_writer=write_config,
            print_fn=step_print,
            dry_run=False,
        )

        job.success_count = len(report.succeeded)
        job.fail_count = len(report.failed)
        job.skip_count = len(report.skipped)
        job.halted = report.halted
        job.halt_reason = report.halt_reason

        _emit(job, "install_done", {
            "succeeded": job.success_count,
            "failed": job.fail_count,
            "skipped": job.skip_count,
            "halted": job.halted,
            "halt_reason": job.halt_reason,
        })

        if not job.halted:
            _emit(job, "log", {"text": "Running verification..."})
            vr = run_verification(job.plan)
            job.verification_ready = vr.fully_ready
            _emit(job, "verification", {
                "ready": vr.fully_ready,
                "gateway_running": vr.gateway_running,
                "doctor_passed": vr.doctor_passed,
                "channel_ok": vr.channel_ok,
                "checks": [
                    {
                        "name": c.name,
                        "status": c.status,
                        "detail": c.detail,
                        "fix": c.fix_suggestion,
                    }
                    for c in vr.checks
                ],
            })

        job.status = "done" if not job.halted else "failed"
        _emit(job, "done", {"status": job.status})
    except Exception as exc:
        job.status = "failed"
        _emit(job, "error", {"message": str(exc)})
        _emit(job, "done", {"status": "failed"})


# ---------------------------------------------------------------------------
# Request/response schemas
# ---------------------------------------------------------------------------

class StartRequest(BaseModel):
    profile: str
    provider: str
    install_service: bool = True
    env_vars: dict = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

def create_app() -> FastAPI:
    app = FastAPI(title="clawup wizard", docs_url=None, redoc_url=None)

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/", include_in_schema=False)
    def root():
        return RedirectResponse("/wizard")

    @app.get("/wizard", response_class=HTMLResponse, include_in_schema=False)
    def wizard():
        return FileResponse(str(STATIC_DIR / "wizard.html"))

    @app.get("/api/profiles")
    def api_profiles():
        out = []
        for pid, p in PROFILES.items():
            copy = PROFILE_COPY.get(pid, {"title": p.label, "blurb": p.description, "icon": "•"})
            out.append({
                "id": pid,
                "title": copy["title"],
                "blurb": copy["blurb"],
                "icon": copy["icon"],
                "providers": p.provider_choices,
                "channel": p.channel_id,
                "service_default": p.install_service_default,
                "advanced": pid in ("remote_gateway", "dev_setup"),
            })
        return out

    @app.get("/api/providers")
    def api_providers(profile: str):
        if profile not in PROFILES:
            raise HTTPException(404, "unknown profile")
        p = PROFILES[profile]
        out = []
        for pid in p.provider_choices:
            if pid not in PROVIDERS:
                continue
            copy = PROVIDER_COPY.get(pid, {})
            out.append({
                "id": pid,
                "title": copy.get("title", PROVIDERS[pid].label),
                "blurb": copy.get("blurb", ""),
                "key_url": copy.get("key_url", ""),
                "key_label": copy.get("key_label", ""),
                "key_hint": copy.get("key_hint", ""),
                "required_env": PROVIDERS[pid].required_env,
            })
        return out

    @app.get("/api/channel-env")
    def api_channel_env(profile: str):
        """Return env vars the channel needs (e.g. TELEGRAM_BOT_TOKEN)."""
        if profile not in PROFILES:
            raise HTTPException(404, "unknown profile")
        p = PROFILES[profile]
        if not p.channel_id:
            return {"required_env": [], "steps": []}
        ch = CHANNELS.get(p.channel_id)
        if ch is None:
            return {"required_env": [], "steps": []}
        return {
            "required_env": ch.required_env,
            "steps": ch.setup_steps,
            "channel_id": p.channel_id,
            "channel_label": ch.label,
        }

    @app.get("/api/env-copy")
    def api_env_copy(name: str):
        return ENV_COPY.get(name, {
            "label": name,
            "help": f"Set the {name} environment variable.",
            "placeholder": "",
        })

    @app.post("/api/plan")
    def api_plan(req: StartRequest):
        """Build a plan (no execution). Used for the review step."""
        if req.profile not in PROFILES or req.provider not in PROVIDERS:
            raise HTTPException(400, "unknown profile or provider")

        profile = PROFILES[req.profile]
        provider = PROVIDERS[req.provider]
        channel = CHANNELS[profile.channel_id] if profile.channel_id else None

        # Collect required binaries and env vars for detection
        all_bins = list(provider.required_bins)
        if channel:
            all_bins += channel.required_bins
        all_env = list(provider.required_env)
        if channel:
            all_env += channel.required_env

        # Apply any env vars the user supplied so detection sees them
        merged_env = {**os.environ, **{k: v for k, v in req.env_vars.items() if v}}
        saved = os.environ.copy()
        try:
            os.environ.update({k: v for k, v in req.env_vars.items() if v})
            system = run_detection(required_bins=all_bins, required_env=all_env)
        finally:
            os.environ.clear()
            os.environ.update(saved)

        plan = build_plan(
            profile_id=req.profile,
            provider_id=req.provider,
            install_service=req.install_service,
            system=system,
        )

        # Build a config preview
        config_fields: dict = {}
        config_fields.update(provider.config_fields)
        if channel:
            config_fields.update(channel.config_fields)
        config_fields["workspace"] = "~/.openclaw"
        if req.install_service:
            config_fields["service.enabled"] = True

        return {
            "profile": {"id": profile.id, "title": PROFILE_COPY.get(profile.id, {}).get("title", profile.label)},
            "provider": {"id": provider.id, "title": PROVIDER_COPY.get(provider.id, {}).get("title", provider.label)},
            "channel": {"id": channel.id, "label": channel.label} if channel else None,
            "install_service": req.install_service,
            "system": {
                "os": system.os_name,
                "arch": system.arch,
                "package_managers": system.package_managers,
                "openclaw_installed": system.openclaw_version is not None,
                "openclaw_version": system.openclaw_version,
                "found_bins": list(system.found_bins.keys()),
                "missing_bins": [b.name for b in system.missing_bins],
                "missing_env": system.missing_env,
            },
            "steps": [{"label": s.label, "action": s.action} for s in plan.steps],
            "missing_env": plan.missing_env,
            "config_preview": preview_config(config_fields),
        }

    @app.post("/api/start")
    def api_start(req: StartRequest):
        if req.profile not in PROFILES or req.provider not in PROVIDERS:
            raise HTTPException(400, "unknown profile or provider")

        # Apply env vars globally so subprocess children inherit them
        for k, v in req.env_vars.items():
            if v:
                os.environ[k] = v

        # Build plan against current system state
        profile = PROFILES[req.profile]
        provider = PROVIDERS[req.provider]
        channel = CHANNELS[profile.channel_id] if profile.channel_id else None

        all_bins = list(provider.required_bins)
        if channel:
            all_bins += channel.required_bins
        all_env = list(provider.required_env)
        if channel:
            all_env += channel.required_env

        system = run_detection(required_bins=all_bins, required_env=all_env)
        plan = build_plan(
            profile_id=req.profile,
            provider_id=req.provider,
            install_service=req.install_service,
            system=system,
        )

        job = Job(id=uuid.uuid4().hex[:12], plan=plan)
        with _JOBS_LOCK:
            _JOBS[job.id] = job

        thread = threading.Thread(target=_run_job, args=(job,), daemon=True)
        thread.start()

        return {"job_id": job.id, "step_count": len(plan.steps)}

    @app.get("/api/jobs/{job_id}/events")
    async def api_events(job_id: str):
        with _JOBS_LOCK:
            job = _JOBS.get(job_id)
        if job is None:
            raise HTTPException(404, "unknown job")

        async def gen():
            while True:
                try:
                    event = await asyncio.to_thread(job.events.get, True, 1.0)
                    yield f"data: {json.dumps(event)}\n\n"
                    if event.get("type") == "done":
                        break
                except queue.Empty:
                    # keep-alive ping
                    yield ": ping\n\n"
                    if job.status in ("done", "failed"):
                        break

        return StreamingResponse(gen(), media_type="text/event-stream")

    @app.get("/api/jobs/{job_id}")
    def api_job_status(job_id: str):
        with _JOBS_LOCK:
            job = _JOBS.get(job_id)
        if job is None:
            raise HTTPException(404, "unknown job")
        return {
            "id": job.id,
            "status": job.status,
            "success_count": job.success_count,
            "fail_count": job.fail_count,
            "skip_count": job.skip_count,
            "halted": job.halted,
            "halt_reason": job.halt_reason,
            "verification_ready": job.verification_ready,
        }

    @app.post("/api/shutdown")
    def api_shutdown():
        def _exit():
            import time, os as _os
            time.sleep(0.25)
            _os._exit(0)
        threading.Thread(target=_exit, daemon=True).start()
        return {"ok": True}

    return app


# ---------------------------------------------------------------------------
# Server runner
# ---------------------------------------------------------------------------

def find_free_port(preferred: int = 7999) -> int:
    import socket
    for port in [preferred, 7998, 8765, 8787, 9001, 0]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                _, actual = s.getsockname()
                return actual
            except OSError:
                continue
    raise RuntimeError("no free port available")


def serve(port: int = 7999, open_browser: bool = True, host: str = "127.0.0.1") -> int:
    import uvicorn

    actual_port = find_free_port(port)
    url = f"http://{host}:{actual_port}/wizard"

    if open_browser:
        import webbrowser, threading
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    print(f"\n  clawup wizard running at: {url}")
    print(f"  Press Ctrl+C to stop\n")

    app = create_app()
    uvicorn.run(app, host=host, port=actual_port, log_level="warning")
    return 0
