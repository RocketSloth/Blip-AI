from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent import TrendResearchAgent
from app.bucket import BucketStore
from app.config import AgentSettings


class HeartbeatUpdate(BaseModel):
    heartbeat_seconds: int = Field(ge=30, le=3600)


class AgentRuntime:
    def __init__(self) -> None:
        self.settings = AgentSettings()
        self.bucket = BucketStore()
        self.agent = TrendResearchAgent(settings=self.settings, bucket=self.bucket)
        self.last_run: str | None = None
        self.last_result: dict[str, Any] | None = None
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        self._task = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        while True:
            try:
                self.run_once()
            except Exception:
                # Keep looping even if one run fails.
                pass
            await asyncio.sleep(self.settings.heartbeat_seconds)

    def run_once(self) -> dict[str, Any]:
        result = self.agent.run_once()
        self.last_run = datetime.now(timezone.utc).isoformat()
        self.last_result = result
        return result


runtime = AgentRuntime()


@asynccontextmanager
async def lifespan(_: FastAPI):
    await runtime.start()
    yield
    await runtime.stop()


app = FastAPI(title="Trend Bucket Agent", lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/")
def index() -> FileResponse:
    return FileResponse(Path("static/index.html"))


@app.get("/api/state")
def state() -> dict[str, Any]:
    projects = [project.__dict__ for project in runtime.bucket.list_projects()]
    return {
        "heartbeat_seconds": runtime.settings.heartbeat_seconds,
        "last_run": runtime.last_run,
        "last_result": runtime.last_result,
        "projects": projects,
    }


@app.post("/api/run")
def run_now() -> dict[str, Any]:
    try:
        return runtime.run_once()
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/heartbeat")
def update_heartbeat(payload: HeartbeatUpdate) -> dict[str, Any]:
    runtime.settings.heartbeat_seconds = payload.heartbeat_seconds
    return {"heartbeat_seconds": runtime.settings.heartbeat_seconds}
