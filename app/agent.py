from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from typing import Any

from openai import OpenAI

from app.bucket import BucketStore, ProjectIdea, ProjectSection
from app.config import AgentSettings

logger = logging.getLogger(__name__)


def _parse_json_object(text: str) -> dict[str, Any]:
    text = text.strip()
    if not text:
        return {}

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1:
            logger.warning("Failed to parse model output as JSON; output=%s", text)
            return {}
        try:
            return json.loads(text[start : end + 1])
        except json.JSONDecodeError:
            logger.warning("Failed to parse model output as JSON; output=%s", text)
            return {}


class TrendResearchAgent:
    def __init__(self, settings: AgentSettings, bucket: BucketStore):
        self.settings = settings
        self.bucket = bucket

    @property
    def client(self) -> OpenAI:
        return OpenAI()

    def run_once(self) -> dict[str, Any]:
        existing_titles = self.bucket.existing_titles()
        ideas = self._generate_ideas(existing_titles)

        added: list[ProjectIdea] = []
        skipped: list[str] = []
        now = datetime.now(timezone.utc).isoformat()

        for idea in ideas:
            title = str(idea.get("title", "")).strip()
            description = str(idea.get("description", "")).strip()
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

        response = self.client.chat.completions.create(
            model=self.settings.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.7,
        )
        text = response.choices[0].message.content or ""
        data = _parse_json_object(text)
        ideas = data.get("ideas", [])
        return ideas[: self.settings.ideas_per_run] if isinstance(ideas, list) else []


class BucketOrganizerAgent:
    def __init__(self, settings: AgentSettings, bucket: BucketStore):
        self.settings = settings
        self.bucket = bucket

    @property
    def client(self) -> OpenAI:
        return OpenAI()

    def run_once(self) -> dict[str, Any]:
        projects = self.bucket.list_projects()
        now = datetime.now(timezone.utc).isoformat()

        if not projects:
            return {
                "sections": [],
                "organized_count": 0,
                "section_count": 0,
                "run_at": now,
            }

        sections = self._generate_sections(projects)
        self.bucket.write_organized_sections(sections, run_at=now)
        return {
            "sections": [
                {
                    "name": section.name,
                    "projects": [project.__dict__ for project in section.projects],
                }
                for section in sections
            ],
            "organized_count": sum(len(section.projects) for section in sections),
            "section_count": len(sections),
            "run_at": now,
        }

    def _generate_sections(self, projects: list[ProjectIdea]) -> list[ProjectSection]:
        target_sections = max(2, min(8, len(projects) // 12 + 2))
        prompt = (
            "You organize a markdown bucket of software project ideas into clear sections.\n"
            f"Aim for about {target_sections} sections.\n"
            "Rules:\n"
            "- Group projects by actual use case or market, not by generic buzzwords.\n"
            "- Every project title must appear exactly once.\n"
            "- Reuse the exact titles provided.\n"
            "- Prefer concise section names with 2 to 5 words.\n"
            "- Avoid singleton sections unless a project clearly does not fit elsewhere.\n"
            "Return strict JSON with this shape:\n"
            '{"sections":[{"name":"Section Name","titles":["Exact Project Title"]}]}\n'
            f"Projects: {json.dumps([project.__dict__ for project in projects])}"
        )

        response = self.client.chat.completions.create(
            model=self.settings.model,
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        text = response.choices[0].message.content or ""
        data = _parse_json_object(text)
        raw_sections = data.get("sections", [])
        return self._normalize_sections(projects, raw_sections)

    def _normalize_sections(
        self,
        projects: list[ProjectIdea],
        raw_sections: Any,
    ) -> list[ProjectSection]:
        if not isinstance(raw_sections, list):
            raw_sections = []

        project_lookup = {project.title.lower().strip(): project for project in projects}
        assigned_titles: set[str] = set()
        used_names: set[str] = set()
        sections: list[ProjectSection] = []

        for raw_section in raw_sections:
            if not isinstance(raw_section, dict):
                continue

            name = self._unique_section_name(str(raw_section.get("name", "")).strip(), used_names)
            titles = raw_section.get("titles", [])
            if not isinstance(titles, list):
                continue

            section_projects: list[ProjectIdea] = []
            for raw_title in titles:
                normalized_title = str(raw_title).lower().strip()
                project = project_lookup.get(normalized_title)
                if project is None or normalized_title in assigned_titles:
                    continue
                section_projects.append(project)
                assigned_titles.add(normalized_title)

            if section_projects:
                sections.append(ProjectSection(name=name, projects=section_projects))

        if not sections:
            return [ProjectSection(name="All Projects", projects=projects)]

        unassigned_projects = [
            project for project in projects if project.title.lower().strip() not in assigned_titles
        ]
        if unassigned_projects:
            sections.append(
                ProjectSection(
                    name=self._unique_section_name("Other Ideas", used_names),
                    projects=unassigned_projects,
                )
            )

        return sections

    @staticmethod
    def _unique_section_name(name: str, used_names: set[str]) -> str:
        base_name = name or "Other Ideas"
        candidate = base_name
        suffix = 2
        while candidate.lower() in used_names:
            candidate = f"{base_name} {suffix}"
            suffix += 1
        used_names.add(candidate.lower())
        return candidate
