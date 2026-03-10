from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any

from openai import OpenAI

from app.bucket import BucketStore, ProjectIdea
from app.config import AgentSettings

logger = logging.getLogger(__name__)


class TrendResearchAgent:
    def __init__(self, settings: AgentSettings, bucket: BucketStore):
        self.settings = settings
        self.bucket = bucket

    def run_once(self) -> dict[str, Any]:
        existing_titles = self.bucket.existing_titles()
        ideas = self._generate_ideas(existing_titles)

        added: list[ProjectIdea] = []
        skipped: list[str] = []
        now = datetime.now(timezone.utc).isoformat()

        for idea in ideas:
            title = idea.get("title", "").strip()
            description = idea.get("description", "").strip()
            if not title or not description:
                continue
            normalized = title.lower()
            if normalized in existing_titles:
                skipped.append(title)
                continue
            project = ProjectIdea(title=title, description=description, created_at=now)
            added.append(project)
            existing_titles.add(normalized)

        self.bucket.append_run(added=added, skipped_titles=skipped)
        return {
            "added": [project.__dict__ for project in added],
            "skipped": skipped,
            "run_at": now,
        }

    def _generate_ideas(self, existing_titles: set[str]) -> list[dict[str, str]]:
        prompt = (
            "You are a trend research assistant. Find the latest practical software trends and "
            "propose project ideas with short descriptions. Avoid duplicates from existing titles. "
            f"Existing titles: {sorted(existing_titles)}. Return strict JSON with key 'ideas', where ideas "
            "is a list of objects: {title, description}. Keep descriptions under 25 words."
        )

        client = OpenAI()
        response = client.responses.create(
            model=self.settings.model,
            tools=[{"type": "web_search_preview"}],
            input=prompt,
            temperature=0.7,
        )
        text = response.output_text.strip()
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start == -1 or end == -1:
                logger.warning("Failed to parse model output as JSON; output=%s", text)
                return []
            try:
                data = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                logger.warning("Failed to parse model output as JSON; output=%s", text)
                return []

        ideas = data.get("ideas", [])
        return ideas[: self.settings.ideas_per_run]
