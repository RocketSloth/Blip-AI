"""
Minimal config generator.

Writes a known-good openclaw config file before any advanced setup runs.
Uses YAML when PyYAML is available, falls back to JSON.

Config shape follows openclaw's expected structure:
  gateway.mode, workspace, provider, model, channel, service.enabled
"""

import json
import os
from pathlib import Path
from typing import Optional


_DEFAULT_CONFIG_PATH = Path.home() / ".openclaw" / "config.yaml"


def _flatten_to_nested(flat: dict) -> dict:
    """
    Convert flat dot-notation keys to nested dict.
    e.g. {"gateway.mode": "local", "service.enabled": True}
      -> {"gateway": {"mode": "local"}, "service": {"enabled": True}}
    """
    nested: dict = {}
    for key, value in flat.items():
        parts = key.split(".")
        node = nested
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node[parts[-1]] = value
    return nested


def _write_yaml(data: dict, path: Path) -> None:
    try:
        import yaml  # type: ignore
        with open(path, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)
    except ImportError:
        # Fall back to JSON with .yaml extension — openclaw should handle both
        with open(path, "w") as f:
            json.dump(data, f, indent=2)


def _write_json(data: dict, path: Path) -> None:
    with open(path, "w") as f:
        json.dump(data, f, indent=2)


def write_config(
    fields: dict,
    config_path: Optional[Path] = None,
    force: bool = False,
) -> str:
    """
    Write a minimal openclaw config from a flat dot-notation fields dict.

    fields:      dict of config keys (may use dot notation or be pre-nested)
    config_path: override default ~/.openclaw/config.yaml
    force:       overwrite even if file exists

    Returns the path written to.
    """
    path = Path(config_path) if config_path else _DEFAULT_CONFIG_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists() and not force:
        # Merge into existing config rather than overwriting
        try:
            existing = _load_existing(path)
        except Exception:
            existing = {}
        merged = _deep_merge(existing, _flatten_to_nested(fields))
        data = merged
    else:
        data = _flatten_to_nested(fields)

    if path.suffix in (".yaml", ".yml"):
        _write_yaml(data, path)
    else:
        _write_json(data, path)

    return str(path)


def _load_existing(path: Path) -> dict:
    """Load existing config, supporting YAML and JSON."""
    with open(path) as f:
        content = f.read().strip()
    if not content:
        return {}
    try:
        import yaml  # type: ignore
        return yaml.safe_load(content) or {}
    except ImportError:
        pass
    return json.loads(content)


def _deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override into base, returning a new dict."""
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def preview_config(fields: dict) -> str:
    """Return a human-readable preview of what will be written."""
    nested = _flatten_to_nested(fields)
    try:
        import yaml  # type: ignore
        return yaml.dump(nested, default_flow_style=False, sort_keys=False)
    except ImportError:
        return json.dumps(nested, indent=2)
