"""User-editable project types (lanes) config. Load/save data/lanes.json."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

KNOWN_LANE_IDS = ("ops-copilot", "intake-approval", "reporting-dashboard")

_DEFAULT_LANES = [
    {
        "id": "ops-copilot",
        "label": "Internal Ops Copilot",
        "enabled": True,
        "keywords": [
            "ops", "operations", "workflow", "queue", "inspection",
            "task", "assistant", "copilot",
        ],
    },
    {
        "id": "intake-approval",
        "label": "Intake And Approval Workflow",
        "enabled": True,
        "keywords": [
            "intake", "approval", "request", "submission", "review",
            "onboarding", "verification",
        ],
    },
    {
        "id": "reporting-dashboard",
        "label": "Reporting Dashboard",
        "enabled": True,
        "keywords": [
            "dashboard", "analytics", "metrics", "reporting",
            "productivity", "score", "kpi",
        ],
    },
]


def _project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _lanes_path() -> Path:
    return _project_root() / "data" / "lanes.json"


def get_lanes_config() -> list[dict[str, Any]]:
    """Return current lanes config: list of {id, label, enabled, keywords}. Uses defaults if file missing."""
    path = _lanes_path()
    if not path.exists():
        return list(_DEFAULT_LANES)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        lanes = data.get("lanes")
        if not isinstance(lanes, list):
            return list(_DEFAULT_LANES)
        # Normalize: only include known ids, merge with defaults for missing fields
        by_id = {d["id"]: d for d in _DEFAULT_LANES}
        out = []
        for item in lanes:
            if not isinstance(item, dict):
                continue
            lid = item.get("id")
            if lid not in by_id:
                continue
            default = by_id[lid]
            out.append({
                "id": lid,
                "label": item.get("label") if isinstance(item.get("label"), str) else default["label"],
                "enabled": item.get("enabled") if isinstance(item.get("enabled"), bool) else default["enabled"],
                "keywords": item.get("keywords") if isinstance(item.get("keywords"), list) else default["keywords"],
            })
        # Ensure all three present
        for d in _DEFAULT_LANES:
            if not any(o["id"] == d["id"] for o in out):
                out.append(dict(d))
        return out
    except (OSError, json.JSONDecodeError):
        return list(_DEFAULT_LANES)


def get_enabled_lanes() -> tuple[str, ...]:
    """Return tuple of enabled lane ids (for qualifier/templates)."""
    config = get_lanes_config()
    return tuple(c["id"] for c in config if c.get("enabled") is True)


def get_lane_keywords() -> dict[str, tuple[str, ...]]:
    """Return dict lane_id -> tuple of keywords (for fallback qualifier)."""
    config = get_lanes_config()
    return {
        c["id"]: tuple(c["keywords"]) if isinstance(c.get("keywords"), list) else ()
        for c in config
        if c.get("enabled") is True
    }


def get_lane_labels() -> dict[str, str]:
    """Return dict lane_id -> label (for UI and templates). Includes 'unsupported'."""
    config = get_lanes_config()
    labels = {c["id"]: c.get("label") or c["id"] for c in config}
    labels["unsupported"] = "Unsupported"
    return labels


def save_lanes_config(lanes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate and save lanes. Only known ids allowed. Returns saved config."""
    by_id = {d["id"]: d for d in _DEFAULT_LANES}
    to_save = []
    for item in lanes:
        if not isinstance(item, dict):
            continue
        lid = item.get("id")
        if lid not in KNOWN_LANE_IDS:
            continue
        default = by_id.get(lid, _DEFAULT_LANES[0])
        to_save.append({
            "id": lid,
            "label": item.get("label") if isinstance(item.get("label"), str) else default["label"],
            "enabled": bool(item.get("enabled")) if item.get("enabled") is not None else default["enabled"],
            "keywords": item.get("keywords") if isinstance(item.get("keywords"), list) else default["keywords"],
        })
    # Ensure all three
    for d in _DEFAULT_LANES:
        if not any(o["id"] == d["id"] for o in to_save):
            to_save.append(dict(d))
    path = _lanes_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"lanes": to_save}, indent=2), encoding="utf-8")
    return to_save
