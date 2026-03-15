"""Preset/profile file helpers (.ndot)."""

import json
from pathlib import Path

from .core import NamingPreset
from .presets import preset_from_dict, preset_to_dict


def profile_to_dict(preset: NamingPreset) -> dict:
    return {
        "format": "nodot_profile",
        "version": 1,
        "preset": preset_to_dict(preset),
    }


def export_profile_file(preset: NamingPreset, filepath: str) -> None:
    path = Path(filepath)
    path.write_text(json.dumps(profile_to_dict(preset), indent=2), encoding="utf-8")


def import_profile_file(filepath: str) -> NamingPreset:
    path = Path(filepath)
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and data.get("format") == "nodot_profile":
        payload = data.get("preset", {})
        if not isinstance(payload, dict):
            raise ValueError("Invalid .ndot profile: 'preset' must be an object")
        return preset_from_dict(payload)
    if isinstance(data, dict):
        # Backward compatibility: plain preset-style dict.
        return preset_from_dict(data)
    raise ValueError("Invalid profile format")

