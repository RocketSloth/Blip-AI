from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import re
from typing import Iterable

PROJECT_PATTERN = re.compile(r"^- \[(?P<ts>[^\]]+)\] \*\*(?P<title>[^*]+)\*\* — (?P<desc>.+)$")


@dataclass
class ProjectIdea:
    title: str
    description: str
    created_at: str


class BucketStore:
    def __init__(self, file_path: str = "data/BUCKET.md") -> None:
        self.path = Path(file_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if not self.path.exists():
            self.path.write_text(self._default_content(), encoding="utf-8")

    @staticmethod
    def _default_content() -> str:
        return "# Bucket\n\n## Project Ideas\n\n## Run History\n"

    def read(self) -> str:
        return self.path.read_text(encoding="utf-8")

    def _split_sections(self) -> tuple[list[str], list[str]]:
        content = self.read().splitlines()
        if "## Project Ideas" not in content or "## Run History" not in content:
            self.path.write_text(self._default_content(), encoding="utf-8")
            content = self.read().splitlines()

        ideas_start = content.index("## Project Ideas")
        history_start = content.index("## Run History")
        ideas_lines = content[ideas_start + 1 : history_start]
        history_lines = content[history_start + 1 :]
        return ideas_lines, history_lines

    def list_projects(self) -> list[ProjectIdea]:
        ideas_lines, _ = self._split_sections()
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

    def append_run(self, added: Iterable[ProjectIdea], skipped_titles: Iterable[str]) -> None:
        ideas_lines, history_lines = self._split_sections()
        now = datetime.now(timezone.utc).isoformat()

        new_idea_lines = [
            f"- [{idea.created_at}] **{idea.title}** — {idea.description}" for idea in added
        ]

        run_lines = [f"### {now}", f"- Added {len(new_idea_lines)} project(s)."]
        skipped_titles = list(skipped_titles)
        if skipped_titles:
            run_lines.append(f"- Skipped duplicate title(s): {', '.join(skipped_titles)}.")

        updated = ["# Bucket", "", "## Project Ideas"]
        updated.extend(ideas_lines)
        if ideas_lines and ideas_lines[-1] != "":
            updated.append("")
        updated.extend(new_idea_lines)
        updated.extend(["", "## Run History"])
        updated.extend(history_lines)
        if history_lines and history_lines[-1] != "":
            updated.append("")
        updated.extend(run_lines)
        updated.append("")

        self.path.write_text("\n".join(updated), encoding="utf-8")
