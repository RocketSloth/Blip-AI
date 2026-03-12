from pydantic import BaseModel, Field


class AgentSettings(BaseModel):
    model: str = Field(default="gpt-4o-mini")
    heartbeat_seconds: int = Field(default=120, ge=30)
    ideas_per_run: int = Field(default=3, ge=1, le=10)
    builder_candidates_per_run: int = Field(default=3, ge=1, le=5)
    project_target_score: int = Field(default=95, ge=1, le=100)
    usable_mvp_score: int = Field(default=70, ge=1, le=100)
    openai_timeout_seconds: int = Field(default=45, ge=10, le=300)
    openai_request_retries: int = Field(default=2, ge=0, le=5)
    validation_timeout_seconds: int = Field(default=60, ge=10, le=300)
