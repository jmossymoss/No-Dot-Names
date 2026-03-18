"""Naming convention editor helpers."""

from .constants import TRACKED_BLEND_DATA_COLLECTIONS
from .core import DEFAULT_PREFIX_MAP, NamingPreset


def separator_style_from_value(separator: str) -> str:
    reverse = {"_": "UNDERSCORE", ".": "DOT", "-": "DASH", " ": "SPACE"}
    return reverse.get(separator, "CUSTOM")


def _nct(owner):
    return getattr(owner, "nct", None)


def editor_separator(owner) -> str:
    nct = _nct(owner)
    if nct is None:
        return "_"
    style = getattr(nct, "editor_separator_style", "UNDERSCORE")
    if style == "CUSTOM":
        return getattr(nct, "editor_custom_separator", "_") or "_"
    return {"UNDERSCORE": "_", "DOT": ".", "DASH": "-", "SPACE": " "}.get(style, "_")


def editor_prefix_from_owner(owner, collection_name: str) -> str:
    nct = _nct(owner)
    if nct is None:
        return DEFAULT_PREFIX_MAP.get(collection_name, "")
    if collection_name == "meshes":
        return getattr(nct, "editor_prefix_objects", DEFAULT_PREFIX_MAP.get("meshes", "SM_"))
    prop_name = f"editor_prefix_{collection_name}"
    return getattr(nct, prop_name, DEFAULT_PREFIX_MAP.get(collection_name, ""))


def build_editor_preset(owner) -> NamingPreset:
    nct = _nct(owner)
    if nct is None:
        return NamingPreset(name="Custom", prefix_map=dict(DEFAULT_PREFIX_MAP))
    shared_object_mesh_prefix = getattr(nct, "editor_prefix_objects", "SM_")
    prefix_map = dict(DEFAULT_PREFIX_MAP)
    for collection_name in TRACKED_BLEND_DATA_COLLECTIONS:
        if collection_name in {"objects", "meshes"}:
            prefix_map[collection_name] = shared_object_mesh_prefix
        else:
            prefix_map[collection_name] = editor_prefix_from_owner(owner, collection_name)
    return NamingPreset(
        name=(getattr(nct, "editor_preset_name", "Custom") or "Custom").strip() or "Custom",
        separator=editor_separator(owner),
        padding=max(1, int(getattr(nct, "editor_padding", 3))),
        case_mode=getattr(nct, "editor_case_mode", "PRESERVE"),
        prefix_map=prefix_map,
    )


def apply_preset_to_editor(owner, preset: NamingPreset) -> None:
    nct = _nct(owner)
    if nct is None:
        return
    nct.editor_preset_name = preset.name or "Imported"
    nct.editor_separator_style = separator_style_from_value(preset.separator)
    nct.editor_custom_separator = preset.separator if preset.separator else "_"
    nct.editor_padding = max(1, int(preset.padding))
    nct.editor_case_mode = preset.case_mode or "PRESERVE"
    shared = preset.prefix_map.get("meshes", preset.prefix_map.get("objects", "SM_"))
    nct.editor_prefix_meshes = shared
    nct.editor_prefix_objects = shared
    for collection_name in TRACKED_BLEND_DATA_COLLECTIONS:
        if collection_name in {"meshes", "objects"}:
            continue
        prop_name = f"editor_prefix_{collection_name}"
        if hasattr(nct, prop_name):
            setattr(nct, prop_name, preset.prefix_map.get(collection_name, DEFAULT_PREFIX_MAP.get(collection_name, "")))

