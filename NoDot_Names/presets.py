# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 3
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, see <https://www.gnu.org/licenses/>.
#
# ##### END GPL LICENSE BLOCK #####

"""Naming convention presets: save/load, import/export JSON."""

import json
from pathlib import Path

from .core import DEFAULT_PREFIX_MAP, NamingPreset

BUILTIN_PRESETS: dict[str, NamingPreset] = {
    "Unreal": NamingPreset(
        name="Unreal",
        separator="_",
        padding=3,
        case_mode="PRESERVE",
        prefix_map={
            **DEFAULT_PREFIX_MAP,
            "meshes": "SM_",
            "materials": "M_",
            "textures": "T_",
            "images": "T_",
            "objects": "",
            "armatures": "SK_",
            "collections": "COL_",
        },
    ),
    "Unity": NamingPreset(
        name="Unity",
        separator="_",
        padding=2,
        case_mode="PRESERVE",
        prefix_map={
            **DEFAULT_PREFIX_MAP,
            "meshes": "Mesh_",
            "materials": "Mat_",
            "textures": "Tex_",
            "images": "Tex_",
            "objects": "",
            "armatures": "Armature_",
        },
    ),
    "Studio Pipeline": NamingPreset(
        name="Studio Pipeline",
        separator="_",
        padding=3,
        case_mode="TITLE",
        prefix_map={
            **DEFAULT_PREFIX_MAP,
            "meshes": "Geo_",
            "materials": "Mat_",
            "textures": "Tx_",
            "images": "Tx_",
            "objects": "Prop_",
            "armatures": "Rig_",
        },
    ),
}


def preset_to_dict(preset: NamingPreset) -> dict:
    """Serialize a preset to a JSON-serializable dict."""
    return {
        "name": preset.name,
        "separator": preset.separator,
        "padding": preset.padding,
        "case_mode": preset.case_mode,
        "prefix_map": dict(preset.prefix_map),
    }


def preset_from_dict(data: dict) -> NamingPreset:
    """Deserialize a preset from a dict (e.g. from JSON)."""
    return NamingPreset(
        name=str(data.get("name", "Custom")),
        separator=str(data.get("separator", "_")),
        padding=int(data.get("padding", 3)),
        case_mode=str(data.get("case_mode", "PRESERVE")),
        prefix_map=dict(data.get("prefix_map", DEFAULT_PREFIX_MAP)),
    )


def export_preset_json(preset: NamingPreset, filepath: str | Path) -> None:
    """Write a preset to a JSON file."""
    path = Path(filepath)
    path.write_text(json.dumps(preset_to_dict(preset), indent=2), encoding="utf-8")


def import_preset_json(filepath: str | Path) -> NamingPreset:
    """Load a preset from a JSON file."""
    path = Path(filepath)
    data = json.loads(path.read_text(encoding="utf-8"))
    return preset_from_dict(data)
