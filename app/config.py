from pydantic import BaseModel, Field


class AgentSettings(BaseModel):
    model: str = Field(default="gpt-4o-mini")
    heartbeat_seconds: int = Field(default=120, ge=30)
    ideas_per_run: int = Field(default=3, ge=1, le=10)
