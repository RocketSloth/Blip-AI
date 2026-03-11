from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Iterable

PROJECT_PATTERN = re.compile(
    r"^- \[(?P<ts>[^\]]+)\] \*\*(?P<title>[^*]+)\*\* (?:-|--|—) (?P<desc>.+)$"
)
SECTION_PATTERN = re.compile(r"^### (?P<name>.+)$")
SECTION_HEADERS = ("## Project Ideas", "## Organized Projects", "## Run History")


@dataclass
class ProjectIdea:
    title: str
    description: str
    created_at: str


@dataclass
class ProjectSection:
    name: str
    projects: list[ProjectIdea]


class BucketStore:
    def __init__(self, file_path: str = "data/BUCKET.md") -> None:
        self.path = Path(file_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(self._default_content(), encoding="utf-8")

    @staticmethod
    def _default_content() -> str:
        return "# Bucket\n\n## Project Ideas\n\n## Organized Projects\n\n## Run History\n"

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")

    @staticmethod
    def _trim_blank_lines(lines: Iterable[str]) -> list[str]:
        trimmed = list(lines)
        while trimmed and not trimmed[0].strip():
            trimmed.pop(0)
        while trimmed and not trimmed[-1].strip():
            trimmed.pop()
        return trimmed

    def _section_indices(self, lines: list[str]) -> dict[str, int]:
        return {line: index for index, line in enumerate(lines) if line in SECTION_HEADERS}

    def _section_lines(
        self,
        lines: list[str],
        indices: dict[str, int],
        header: str,
    ) -> list[str]:
        if header not in indices:
            return []

        start = indices[header] + 1
        end = len(lines)
        for candidate in SECTION_HEADERS:
            candidate_index = indices.get(candidate)
            if candidate_index is not None and candidate_index > indices[header]:
                end = min(end, candidate_index)
        return lines[start:end]

    def _split_sections(self) -> tuple[list[str], list[str], list[str]]:
        lines = self.read().splitlines()
        indices = self._section_indices(lines)
        if "## Project Ideas" not in indices or "## Run History" not in indices:
            self.path.write_text(self._default_content(), encoding="utf-8")
            lines = self.read().splitlines()
            indices = self._section_indices(lines)

        ideas_lines = self._section_lines(lines, indices, "## Project Ideas")
        organized_lines = self._section_lines(lines, indices, "## Organized Projects")
        history_lines = self._section_lines(lines, indices, "## Run History")
        return ideas_lines, organized_lines, history_lines

    @staticmethod
    def _format_project(project: ProjectIdea) -> str:
        return f"- [{project.created_at}] **{project.title}** - {project.description}"

    @staticmethod
    def _append_history_lines(
        history_lines: Iterable[str],
        entry_lines: Iterable[str],
        run_at: str,
    ) -> list[str]:
        updated = BucketStore._trim_blank_lines(history_lines)
        if updated:
            updated.append("")
        updated.append(f"### {run_at}")
        updated.extend(line for line in entry_lines if line.strip())
        return updated

    def _write_sections(
        self,
        ideas_lines: Iterable[str],
        organized_lines: Iterable[str],
        history_lines: Iterable[str],
    ) -> None:
        ideas_block = self._trim_blank_lines(ideas_lines)
        organized_block = self._trim_blank_lines(organized_lines)
        history_block = self._trim_blank_lines(history_lines)

        updated = ["# Bucket", "", "## Project Ideas"]
        updated.extend(ideas_block)
        updated.extend(["", "## Organized Projects"])
        updated.extend(organized_block)
        updated.extend(["", "## Run History"])
        updated.extend(history_block)
        updated.append("")

        self.path.write_text("\n".join(updated), encoding="utf-8")

    def list_projects(self) -> list[ProjectIdea]:
        ideas_lines, _, _ = self._split_sections()
        projects: list[ProjectIdea] = []
        for line in ideas_lines:
            match = PROJECT_PATTERN.match(line)
            if not match:
                continue
            projects.append(
                ProjectIdea(
                    title=match.group("title").strip(),
                    description=match.group("desc").strip(),
                    created_at=match.group("ts").strip(),
                )
            )
        return projects

    def existing_titles(self) -> set[str]:
        return {project.title.lower().strip() for project in self.list_projects()}

    def list_organized_sections(self) -> list[ProjectSection]:
        _, organized_lines, _ = self._split_sections()
        sections: list[ProjectSection] = []
        current: ProjectSection | None = None

        for line in organized_lines:
            section_match = SECTION_PATTERN.match(line)
            if section_match:
                if current and current.projects:
                    sections.append(current)
                current = ProjectSection(name=section_match.group("name").strip(), projects=[])
                continue

            project_match = PROJECT_PATTERN.match(line)
            if not project_match:
                continue

            if current is None:
                current = ProjectSection(name="Other Ideas", projects=[])

            current.projects.append(
                ProjectIdea(
                    title=project_match.group("title").strip(),
                    description=project_match.group("desc").strip(),
                    created_at=project_match.group("ts").strip(),
                )
            )

        if current and current.projects:
            sections.append(current)

        return sections

    def append_run(self, added: Iterable[ProjectIdea], skipped_titles: Iterable[str]) -> None:
        ideas_lines, organized_lines, history_lines = self._split_sections()
        now = datetime.now(timezone.utc).isoformat()

        new_idea_lines = [self._format_project(idea) for idea in added]
        updated_ideas = self._trim_blank_lines(ideas_lines)
        if updated_ideas and new_idea_lines:
            updated_ideas.append("")
        updated_ideas.extend(new_idea_lines)

        run_lines = [f"- Added {len(new_idea_lines)} project(s)."]
        skipped_titles = list(skipped_titles)
        if skipped_titles:
            run_lines.append(f"- Skipped duplicate title(s): {', '.join(skipped_titles)}.")
        updated_history = self._append_history_lines(history_lines, run_lines, now)

        self._write_sections(updated_ideas, organized_lines, updated_history)

    def write_organized_sections(
        self,
        sections: Iterable[ProjectSection],
        run_at: str | None = None,
    ) -> None:
        ideas_lines, _, history_lines = self._split_sections()
        cleaned_sections = [section for section in sections if section.projects]

        organized_lines: list[str] = []
        for index, section in enumerate(cleaned_sections):
            if index:
                organized_lines.append("")
            organized_lines.append(f"### {section.name}")
            organized_lines.extend(self._format_project(project) for project in section.projects)

        updated_history = history_lines
        if run_at is not None:
            total_projects = sum(len(section.projects) for section in cleaned_sections)
            history_entry = [
                f"- Organized {total_projects} project(s) into {len(cleaned_sections)} section(s)."
            ]
            updated_history = self._append_history_lines(history_lines, history_entry, run_at)

        self._write_sections(ideas_lines, organized_lines, updated_history)
