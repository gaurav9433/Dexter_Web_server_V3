# -*- coding: utf-8 -*-
"""
dexter_config.py — Settings loader for Dexter HMS

ARCH-03 FIX: Single entry point for all Dexter configuration.
Loads settings.yaml and merges settings.local.yaml overrides (if present).
Validates required keys at startup so misconfiguration fails fast.

Usage:
    from dexter_config import settings

    broker  = settings.mqtt.broker        # via secrets_manager
    max_buf = settings.buffer.max_rows     # 50000
    hb_int  = settings.nvr.cp_plus_heartbeat_interval_min  # 2

The settings object supports dot-notation access (settings.mqtt.port)
as well as dict-style access (settings["mqtt"]["port"]).

secrets (MQTT_TOKEN, MQTT_BROKER, NVR passwords) are NOT in settings.yaml.
Use secrets_manager.get_secret() directly for those.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Optional

log = logging.getLogger(__name__)

# ── Optional YAML support — falls back to stdlib if PyYAML not installed ─────
try:
    import yaml as _yaml
    def _load_yaml(path: Path) -> dict:
        with open(path, encoding="utf-8") as f:
            return _yaml.safe_load(f) or {}
except ImportError:
    _yaml = None
    # Fallback: minimal YAML reader for simple key: value lines.
    # Install PyYAML for full support: pip3 install pyyaml --break-system-packages
    log.warning("PyYAML not installed — using minimal YAML parser. "
                "Run: pip3 install pyyaml --break-system-packages")
    def _load_yaml(path: Path) -> dict:
        """
        Minimal YAML loader that handles flat and one-level nested key: value.
        Sufficient for settings.yaml; does not support sequences or multi-line.
        """
        result: dict = {}
        current_section: dict = result
        current_key: Optional[str] = None

        with open(path, encoding="utf-8") as f:
            for raw_line in f:
                line = raw_line.rstrip()
                # Skip blank lines and comments
                if not line or line.lstrip().startswith("#"):
                    continue

                indent = len(line) - len(line.lstrip())

                # Top-level section header: "section:"
                if indent == 0 and line.endswith(":") and " " not in line.rstrip(":"):
                    current_key = line.rstrip(":")
                    result[current_key] = {}
                    current_section = result[current_key]
                    continue

                # Key-value pair
                if ":" in line:
                    k, _, v = line.lstrip().partition(":")
                    k = k.strip()
                    v = v.strip()
                    # Remove inline comment
                    v = v.split("#")[0].strip()
                    # Type coercion
                    if v.lower() in ("true", "yes"):
                        v = True
                    elif v.lower() in ("false", "no"):
                        v = False
                    elif v.isdigit():
                        v = int(v)
                    else:
                        try:
                            v = float(v)
                        except ValueError:
                            v = v.strip('"\'') if v else None

                    if indent == 0:
                        result[k] = v
                        current_section = result
                        current_key = None
                    else:
                        current_section[k] = v

        return result


class _SettingsNode:
    """
    Dot-notation wrapper around a nested dict.
    settings.mqtt.port  is equivalent to  raw_dict["mqtt"]["port"]
    """

    def __init__(self, data: dict) -> None:
        object.__setattr__(self, "_data", data)

    def __getattr__(self, key: str) -> Any:
        data = object.__getattribute__(self, "_data")
        if key not in data:
            raise AttributeError(
                f"settings: key '{key}' not found. "
                f"Available: {sorted(data.keys())}"
            )
        val = data[key]
        if isinstance(val, dict):
            return _SettingsNode(val)
        return val

    def __getitem__(self, key: str) -> Any:
        return self.__getattr__(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self.__getattr__(key)
        except AttributeError:
            return default

    def __repr__(self) -> str:
        data = object.__getattribute__(self, "_data")
        return f"_SettingsNode({list(data.keys())})"


def _merge(base: dict, override: dict) -> dict:
    """Deep-merge override into base. Returns merged dict (base is mutated)."""
    for k, v in override.items():
        if k in base and isinstance(base[k], dict) and isinstance(v, dict):
            _merge(base[k], v)
        else:
            base[k] = v
    return base


def _find_settings_file() -> Path:
    """
    Locate settings.yaml by searching:
    1. /home/pi/Test3/settings.yaml    — production deployment path
    2. Same directory as this file     — development/testing
    3. Current working directory
    """
    candidates = [
        Path("/home/pi/Test3/settings.yaml"),
        Path(__file__).parent / "settings.yaml",
        Path.cwd() / "settings.yaml",
    ]
    for p in candidates:
        if p.exists():
            return p
    raise FileNotFoundError(
        "settings.yaml not found. Checked:\n" +
        "\n".join(f"  {p}" for p in candidates)
    )


def _load() -> _SettingsNode:
    """Load, merge, and return the settings object."""
    base_path = _find_settings_file()
    data = _load_yaml(base_path)
    log.info("[dexter_config] Loaded settings from %s", base_path)

    # Merge local overrides if present (never committed to git)
    local_path = base_path.parent / "settings.local.yaml"
    if local_path.exists():
        overrides = _load_yaml(local_path)
        _merge(data, overrides)
        log.info("[dexter_config] Merged local overrides from %s", local_path)

    return _SettingsNode(data)


# ── Startup validation ────────────────────────────────────────────────────────
_REQUIRED_KEYS = [
    ("mqtt", "port"),
    ("buffer", "max_rows"),
    ("database", "base_dir"),
    ("watchdog", "default_timeout_sec"),
    ("nvr", "health_check_timeout_sec"),
    ("logging", "log_file"),
]


def _validate(node: _SettingsNode) -> None:
    """Fail fast at startup if any required key is missing."""
    errors = []
    for section, key in _REQUIRED_KEYS:
        try:
            val = getattr(getattr(node, section), key)
            if val is None:
                errors.append(f"  settings.{section}.{key} is null")
        except AttributeError as e:
            errors.append(f"  {e}")

    if errors:
        raise RuntimeError(
            "settings.yaml validation failed — missing required keys:\n" +
            "\n".join(errors) +
            "\nCheck settings.yaml against the template."
        )
    log.info("[dexter_config] Settings validated OK")


# ── Module-level singleton ────────────────────────────────────────────────────
try:
    settings: _SettingsNode = _load()
    _validate(settings)
except FileNotFoundError as _e:
    # Settings file not found during import — warn but don't crash.
    # Modules that need settings will fail when they access them.
    log.warning("[dexter_config] %s", _e)
    settings = _SettingsNode({})
except RuntimeError as _e:
    log.error("[dexter_config] %s", _e)
    raise
