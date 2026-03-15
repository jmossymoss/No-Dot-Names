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

"""Blender addon entry-point for No.Dot Names."""

bl_info = {
    "name": "NoDot Names",
    "author": "Jordan Moss",
    "version": (2, 0, 1),
    "blender": (4, 5, 0),
    "location": "View3D > Sidebar > No.Dot",
    "description": (
        "Naming conventions, presets, validation, hierarchy rename, and batch rename "
        "with prefix rules, regex, and token templates"
    ),
    "warning": "",
    "doc_url": "",
    "tracker_url": "",
    "support": "COMMUNITY",
    "category": "System",
}

import json
import hashlib
import re

import bpy
from bpy.props import BoolProperty, CollectionProperty, EnumProperty, IntProperty, StringProperty
from bpy.types import AddonPreferences

from .constants import IGNORE_NAME_PREFIXES, TRACKED_BLEND_DATA_COLLECTIONS, VALIDATOR_DEFAULT_INCLUDE
from .core import (
    DEFAULT_PREFIX_MAP,
    NamingOptions,
    NamingPreset,
    apply_case,
    build_unique_duplicate_name,
    expand_rename_template,
    validate_name_against_convention,
)
from .presets import (
    BUILTIN_PRESETS,
    preset_from_dict,
    preset_to_dict,
)


_STATE = {
    "cache": {},
    "name_cache": {},
    "lock": False,
}


def _get_preferences() -> AddonPreferences | None:
    try:
        context = getattr(bpy, "context", None)
        if context is None or getattr(context, "preferences", None) is None:
            return None
        addon = context.preferences.addons.get(__name__)
        if not addon:
            return None
        return addon.preferences
    except Exception:
        return None


def _resolved_separator(preferences: AddonPreferences) -> str:
    mapping = {
        "UNDERSCORE": "_",
        "DOT": ".",
        "DASH": "-",
        "SPACE": " ",
    }
    style = getattr(preferences, "separator_style", "UNDERSCORE")
    if style == "CUSTOM":
        return getattr(preferences, "custom_separator", None) or "_"
    return mapping.get(style, "_")


def _build_options(preferences: AddonPreferences) -> NamingOptions:
    return NamingOptions(
        separator=_resolved_separator(preferences),
        padding=max(1, int(getattr(preferences, "padding", 3))),
        case_mode=getattr(preferences, "case_mode", "PRESERVE"),
    )


def _preset_enum_id(name: str, *, is_builtin: bool) -> str:
    """Create a stable, RNA-safe enum identifier for a preset name."""
    slug = re.sub(r"[^A-Z0-9_]", "_", name.upper()).strip("_") or "PRESET"
    digest = hashlib.md5(name.encode("utf-8")).hexdigest()[:8]
    prefix = "B" if is_builtin else "U"
    return f"{prefix}_{slug}_{digest}"


def _preset_choice_map(preferences: AddonPreferences | None) -> dict[str, str]:
    """Map enum identifiers to display preset names."""
    mapping = {"CUSTOM": "Custom"}
    for name in BUILTIN_PRESETS:
        mapping[_preset_enum_id(name, is_builtin=True)] = name
    if preferences:
        for name in _load_custom_presets(preferences):
            if name not in BUILTIN_PRESETS:
                mapping[_preset_enum_id(name, is_builtin=False)] = name
    return mapping


def _preset_name_from_enum_value(value: str, preferences: AddonPreferences | None) -> str:
    """Resolve enum value to concrete preset name (supports legacy saved values)."""
    if not value:
        return "Custom"
    # Legacy values from older versions stored the display name directly.
    if value == "Custom":
        return "Custom"
    if value in BUILTIN_PRESETS:
        return value
    if preferences:
        custom = _load_custom_presets(preferences)
        if value in custom:
            return value
    mapping = _preset_choice_map(preferences)
    return mapping.get(value, "Custom")


def _preset_enum_value_for_name(name: str, preferences: AddonPreferences | None) -> str:
    """Return enum value for a preset display name."""
    if not name or name == "Custom":
        return "CUSTOM"
    for enum_value, display_name in _preset_choice_map(preferences).items():
        if display_name == name:
            return enum_value
    return "CUSTOM"


def _get_active_preset(preferences: AddonPreferences | None) -> NamingPreset:
    """Return the active naming preset (built-in or custom)."""
    if not preferences:
        return NamingPreset()
    raw = getattr(preferences, "active_preset", "CUSTOM") or "CUSTOM"
    key = _preset_name_from_enum_value(raw, preferences)
    if key == "Custom":
        # Use editor as single source of truth when available
        owner = getattr(getattr(bpy, "context", None), "scene", None)
        if owner is not None:
            try:
                from .editor_preset import build_editor_preset
                preset = build_editor_preset(owner)
                return NamingPreset(
                    name="Custom",
                    separator=preset.separator,
                    padding=preset.padding,
                    case_mode=preset.case_mode,
                    prefix_map=preset.prefix_map,
                )
            except Exception:
                pass
        return NamingPreset(
            name="Custom",
            separator=_resolved_separator(preferences),
            padding=max(1, int(getattr(preferences, "padding", 3))),
            case_mode=getattr(preferences, "case_mode", "PRESERVE"),
        )
    if key in BUILTIN_PRESETS:
        return BUILTIN_PRESETS[key]
    custom = _load_custom_presets(preferences)
    if key in custom:
        return custom[key]
    return NamingPreset()


def _load_custom_presets(preferences: AddonPreferences) -> dict[str, NamingPreset]:
    raw = getattr(preferences, "custom_presets_json", "") or "{}"
    try:
        data = json.loads(raw)
        return {k: preset_from_dict(v) for k, v in data.items()}
    except (json.JSONDecodeError, TypeError):
        return {}


def _save_custom_preset(preferences: AddonPreferences, preset: NamingPreset) -> None:
    # _load_custom_presets returns NamingPreset instances; convert back to plain
    # dict payloads before serializing to JSON.
    custom = {name: preset_to_dict(value) for name, value in _load_custom_presets(preferences).items()}
    custom[preset.name] = preset_to_dict(preset)
    preferences.custom_presets_json = json.dumps(custom)


def _all_known_prefixes(preferences: AddonPreferences | None, collection_name: str) -> list[str]:
    prefixes = set()
    for preset in BUILTIN_PRESETS.values():
        pref = preset.prefix_map.get(collection_name, "")
        if pref:
            prefixes.add(pref)
    if preferences:
        for preset in _load_custom_presets(preferences).values():
            pref = preset.prefix_map.get(collection_name, "")
            if pref:
                prefixes.add(pref)
    default = DEFAULT_PREFIX_MAP.get(collection_name, "")
    if default:
        prefixes.add(default)
    return sorted(prefixes, key=len, reverse=True)


def _all_known_prefixes_any(preferences: AddonPreferences | None) -> list[str]:
    """All prefixes from all presets and collections, for stripping when switching presets."""
    prefixes = set()
    for preset in BUILTIN_PRESETS.values():
        for pref in preset.prefix_map.values():
            if pref:
                prefixes.add(pref)
    if preferences:
        for preset in _load_custom_presets(preferences).values():
            for pref in preset.prefix_map.values():
                if pref:
                    prefixes.add(pref)
    for pref in DEFAULT_PREFIX_MAP.values():
        if pref:
            prefixes.add(pref)
    return sorted(prefixes, key=len, reverse=True)


def _split_suffix(name: str) -> tuple[str, int | None, int]:
    match = re.match(r"^(?P<base>.+?)(?P<sep>[._\- ])(?P<num>\d+)$", name)
    if not match:
        return name, None, 0
    return match.group("base"), int(match.group("num")), len(match.group("num"))


def _parse_any_numeric_suffix(name: str) -> tuple[str, str, int, int] | None:
    return _parse_trailing_number(name, ("_", ".", "-", " "))


def _has_numeric_suffix(name: str) -> bool:
    return _parse_any_numeric_suffix(name) is not None


def _parse_duplicate_token(name: str) -> tuple[str, str, int, int, str] | None:
    """
    Parse duplicate token even when additional suffix text exists.

    Examples:
    - BeltClip_001 -> ("BeltClip", "_", 1, 3, "")
    - BeltClip.001_high -> ("BeltClip", ".", 1, 3, "_high")
    """
    match = re.match(r"^(?P<base>.+?)(?P<sep>[._\- ])(?P<num>\d{3,})(?P<tail>(?:[._\- ].+)?)$", name)
    if not match:
        return None
    number_text = match.group("num")
    return (
        match.group("base"),
        match.group("sep"),
        int(number_text),
        len(number_text),
        match.group("tail") or "",
    )


def _strip_known_prefix(name: str, collection_name: str, preferences: AddonPreferences | None) -> str:
    """Strip any known preset prefix from any collection (so SM_Magazine -> Magazine when switching)."""
    result = name
    prefixes = _all_known_prefixes_any(preferences)
    while True:
        changed = False
        for prefix in prefixes:
            if prefix and result.startswith(prefix):
                result = result[len(prefix) :]
                changed = True
                break
        if not changed:
            break
    return result


def _strip_prefix_chain(text: str, prefix: str) -> str:
    result = text
    while prefix and result.startswith(prefix):
        result = result[len(prefix) :]
    return result


def _expected_name_for_preset(
    current_name: str,
    collection_name: str,
    preset: NamingPreset,
    preferences: AddonPreferences | None,
) -> str:
    stem = _strip_known_prefix(current_name, collection_name, preferences)
    stem, suffix_num, suffix_width = _split_suffix(stem)
    if suffix_num is not None and suffix_num > 999:
        # Avoid carrying oversized legacy suffixes into new convention output.
        suffix_num = None
        suffix_width = 0
    if not stem:
        stem = "Unnamed"
    stem = apply_case(stem, preset.case_mode)
    target_prefix = preset.prefix_map.get(collection_name, "")
    stem = _strip_prefix_chain(stem, target_prefix)
    expected = f"{target_prefix}{stem}"
    if suffix_num is not None:
        width = int(preset.padding)
        expected = f"{expected}{preset.separator}{suffix_num:0{max(1, width)}d}"
    return expected


def _compose_expected_name(
    *,
    collection_name: str,
    base_stem: str,
    suffix_num: int | None,
    suffix_width: int,
    preset: NamingPreset,
) -> str:
    target_prefix = preset.prefix_map.get(collection_name, "")
    base = apply_case(base_stem or "Unnamed", preset.case_mode)
    base = _strip_prefix_chain(base, target_prefix)
    expected = f"{target_prefix}{base}"
    if suffix_num is not None:
        if suffix_num > 999:
            suffix_num = None
        else:
            width = int(preset.padding)
            expected = f"{expected}{preset.separator}{suffix_num:0{max(1, width)}d}"
    return expected


def _collapse_repeated_literal_prefix(name: str, literal_prefix: str) -> str:
    """Collapse repeated literal prefixes at the start (e.g. SM_SM_Name -> SM_Name)."""
    if not literal_prefix:
        return name
    # Skip dynamic replacement strings that use regex backreferences/escapes.
    if "\\" in literal_prefix or "$" in literal_prefix:
        return name
    pattern = rf"^(?:{re.escape(literal_prefix)}){{2,}}"
    return re.sub(pattern, literal_prefix, name)


def _extract_explicit_regex(pattern: str) -> str | None:
    """
    Return the inner regex when pattern uses explicit wrapper: { ... }.

    If not wrapped, return None so callers can treat the pattern as literal text.
    """
    text = (pattern or "").strip()
    if len(text) >= 2 and text.startswith("{") and text.endswith("}"):
        return text[1:-1]
    return None


def _batch_regex_rename_name(name: str, find_pattern: str, replace_pattern: str) -> str | None:
    """Apply find/replace with explicit regex wrapper support."""
    if not find_pattern:
        return None
    regex_pattern = _extract_explicit_regex(find_pattern)
    if regex_pattern is not None:
        try:
            new_name = re.sub(regex_pattern, replace_pattern, name)
        except re.error:
            return None
    else:
        new_name = name.replace(find_pattern, replace_pattern)
    new_name = _collapse_repeated_literal_prefix(new_name, replace_pattern)
    return new_name if new_name != name else None


def _pointer_to_collection_name_map() -> dict[int, str]:
    pointer_map: dict[int, str] = {}
    for collection_name, collection in _iter_tracked_collections():
        for item in collection:
            pointer_map[item.as_pointer()] = collection_name
    return pointer_map


def _sync_object_and_data_names(
    *,
    preset: NamingPreset,
    preferences: AddonPreferences | None,
    options: NamingOptions,
) -> int:
    """Keep object and linked data names aligned under active prefix rules."""
    changed = 0
    pointer_map = _pointer_to_collection_name_map()
    existing_by_coll: dict[str, set[str]] = {}
    for coll_name, collection in _iter_tracked_collections():
        existing_by_coll[coll_name] = {item.name for item in collection}

    objects = getattr(bpy.data, "objects", None)
    if objects is None:
        return 0

    for obj in objects:
        data = getattr(obj, "data", None)
        if data is None or not hasattr(data, "as_pointer"):
            continue
        data_coll_name = pointer_map.get(data.as_pointer())
        if not data_coll_name:
            continue
        if _is_ignored_name(obj.name) or _is_ignored_name(data.name):
            continue

        obj_raw = _strip_known_prefix(obj.name, "objects", preferences)
        data_raw = _strip_known_prefix(data.name, data_coll_name, preferences)
        obj_base, obj_num, obj_width = _split_suffix(obj_raw)
        data_base, data_num, data_width = _split_suffix(data_raw)

        # Object name is the source-of-truth stem; linked data follows it.
        base_stem = (obj_base or data_base or "Unnamed").strip() or "Unnamed"
        suffix_num = obj_num if obj_num is not None else data_num
        suffix_width = max(int(preset.padding), int(data_width), int(obj_width))

        desired_data = _compose_expected_name(
            collection_name=data_coll_name,
            base_stem=base_stem,
            suffix_num=suffix_num,
            suffix_width=suffix_width,
            preset=preset,
        )
        data_taken = existing_by_coll.setdefault(data_coll_name, {item.name for item in getattr(bpy.data, data_coll_name)})
        if desired_data == data.name:
            final_data = data.name
        else:
            final_data = _next_name_from_seed(desired_data, data_taken - {data.name}, options)
        if final_data != data.name:
            data_taken.discard(data.name)
            data.name = final_data
            data_taken.add(final_data)
            changed += 1

        # Keep object name aligned to its linked data convention name.
        # This ensures meshes/material-backed objects are renamed together.
        desired_obj = desired_data
        obj_taken = existing_by_coll.setdefault("objects", {item.name for item in bpy.data.objects})
        if desired_obj == obj.name:
            final_obj = obj.name
        else:
            final_obj = _next_name_from_seed(desired_obj, obj_taken - {obj.name}, options)
        if final_obj != obj.name:
            obj_taken.discard(obj.name)
            obj.name = final_obj
            obj_taken.add(final_obj)
            changed += 1

    return changed


def _name_stem_any_prefix(name: str, preferences: AddonPreferences | None) -> str:
    all_prefixes = set()
    for coll_name in TRACKED_BLEND_DATA_COLLECTIONS:
        for pref in _all_known_prefixes(preferences, coll_name):
            if pref:
                all_prefixes.add(pref)
    result = name
    for prefix in sorted(all_prefixes, key=len, reverse=True):
        if result.startswith(prefix):
            result = result[len(prefix) :]
            break
    result, _num, _width = _split_suffix(result)
    return result


def _is_ignored_name(name: str) -> bool:
    """Return True if the datablock name should be skipped (addon-generated, etc.)."""
    if not name:
        return False
    lower = name.lower()
    prefixes = list(IGNORE_NAME_PREFIXES)
    prefs = _get_preferences()
    if prefs and getattr(prefs, "custom_ignore_prefixes", ""):
        custom = (getattr(prefs, "custom_ignore_prefixes", "") or "").strip()
        if custom:
            prefixes.extend(p.strip().lower() for p in custom.split(",") if p.strip())
    return any(lower.startswith(p) for p in prefixes if p)


def _collect_violations(
    preferences,
    included_collections: set[str] | None = None,
) -> list[tuple[str, str, str, str]]:
    """Return list of (collection_name, item_name, expected_name, violation_message)."""
    preset = _get_active_preset(preferences)
    violations: list[tuple[str, str, str, str]] = []
    include = None if not included_collections else set(included_collections)
    for coll_name, collection in _iter_tracked_collections():
        if include is not None and coll_name not in include:
            continue
        for item in collection:
            if _is_ignored_name(item.name):
                continue
            expected = _expected_name_for_preset(item.name, coll_name, preset, preferences)
            msg = validate_name_against_convention(item.name, coll_name, preset)
            if not msg:
                parsed = _parse_duplicate_token(item.name)
                if parsed:
                    _base, separator, _number, _width, _tail = parsed
                    if separator != preset.separator:
                        msg = (
                            f"Duplicate delimiter should be '{preset.separator}' "
                            f"(found '{separator}')"
                        )
            if msg:
                violations.append((coll_name, item.name, expected, msg))

    # Cross-check object names against their datablock name stems.
    objects = getattr(bpy.data, "objects", None)
    if objects is not None:
        if include is not None and "objects" not in include:
            return violations
        pointer_to_collection: dict[int, str] = {}
        for coll_name, collection in _iter_tracked_collections():
            for item in collection:
                pointer_to_collection[item.as_pointer()] = coll_name
        for obj in objects:
            data = getattr(obj, "data", None)
            data_name = getattr(data, "name", "") if data else ""
            if not data_name:
                continue
            if _is_ignored_name(obj.name) or _is_ignored_name(data_name):
                continue
            if data is not None and hasattr(data, "as_pointer") and include is not None:
                data_collection = pointer_to_collection.get(data.as_pointer())
                if data_collection and data_collection not in include:
                    continue
            # Keep validator focused on duplicate suffix naming issues.
            obj_dup = _parse_duplicate_token(obj.name)
            data_dup = _parse_duplicate_token(data_name)
            if not (obj_dup or data_dup):
                continue
            # Names like BeltClip_001_high are valid and should not trigger
            # object/data mismatch noise here.
            if (obj_dup and obj_dup[4]) or (data_dup and data_dup[4]):
                continue
            obj_stem = _name_stem_any_prefix(obj.name, preferences)
            data_stem = _name_stem_any_prefix(data_name, preferences)
            if obj_stem != data_stem:
                fixed = _expected_name_for_preset(obj.name, "objects", preset, preferences)
                violations.append(
                    (
                        "objects",
                        obj.name,
                        fixed,
                        f"Object/data mismatch (object='{obj_stem}', data='{data_stem}')",
                    )
                )
    return violations


def _selected_validator_collections(scene) -> set[str]:
    selected: set[str] = set()
    for collection_name in TRACKED_BLEND_DATA_COLLECTIONS:
        prop_name = f"nct_validator_include_{collection_name}"
        if getattr(scene, prop_name, True):
            selected.add(collection_name)
    return selected

def _iter_tracked_collections():
    for name in TRACKED_BLEND_DATA_COLLECTIONS:
        collection = getattr(bpy.data, name, None)
        if collection is not None:
            yield name, collection


def _reset_pointer_cache() -> None:
    _STATE["cache"] = {}
    _STATE["name_cache"] = {}
    for collection_name, collection in _iter_tracked_collections():
        ptrs = set()
        names: dict[int, str] = {}
        for item in collection:
            pointer = item.as_pointer()
            ptrs.add(pointer)
            names[pointer] = item.name
        _STATE["cache"][collection_name] = ptrs
        _STATE["name_cache"][collection_name] = names


def _normalize_in_collection(collection, options: NamingOptions, targets=None) -> int:
    existing_names = {item.name for item in collection}
    target_ptrs = None if targets is None else {item.as_pointer() for item in targets}
    renamed = 0
    for item in collection:
        if _is_ignored_name(item.name):
            continue
        if target_ptrs is not None and item.as_pointer() not in target_ptrs:
            continue
        new_name = build_unique_duplicate_name(
            current_name=item.name,
            existing_names=existing_names,
            options=options,
        )
        if not new_name or new_name == item.name:
            continue
        existing_names.discard(item.name)
        item.name = new_name
        existing_names.add(item.name)
        renamed += 1
    return renamed


def _normalize_new_ids_only() -> int:
    preferences = _get_preferences()
    if not preferences or not getattr(preferences, "enable_live_renaming", True):
        return 0
    if _STATE["lock"]:
        return 0

    _STATE["lock"] = True
    renamed = 0
    try:
        options = _build_options(preferences)
        cache = _STATE["cache"]
        name_cache = _STATE.setdefault("name_cache", {})
        for collection_name, collection in _iter_tracked_collections():
            known_ptrs = cache.setdefault(collection_name, set())
            known_names = name_cache.setdefault(collection_name, {})
            current_ptrs = set()
            current_names: dict[int, str] = {}
            new_or_changed_items = []
            for item in collection:
                pointer = item.as_pointer()
                current_ptrs.add(pointer)
                current_names[pointer] = item.name
                if pointer not in known_ptrs or known_names.get(pointer) != item.name:
                    new_or_changed_items.append(item)
            if new_or_changed_items:
                renamed += _normalize_in_collection(collection, options, targets=new_or_changed_items)
                # Refresh current names after possible renames.
                current_names = {item.as_pointer(): item.name for item in collection}
            cache[collection_name] = current_ptrs
            name_cache[collection_name] = current_names
    finally:
        _STATE["lock"] = False
    return renamed


def _normalize_all_ids() -> int:
    preferences = _get_preferences()
    if not preferences:
        return 0
    options = _build_options(preferences)
    renamed = 0
    for _collection_name, collection in _iter_tracked_collections():
        renamed += _normalize_in_collection(collection, options)
    _reset_pointer_cache()
    return renamed


def _normalize_all_ids_with_options(options: NamingOptions) -> int:
    renamed = 0
    for _collection_name, collection in _iter_tracked_collections():
        renamed += _normalize_in_collection(collection, options)
    _reset_pointer_cache()
    return renamed


def _parse_trailing_number(name: str, separators: tuple[str, ...]) -> tuple[str, str, int, int] | None:
    for separator in separators:
        if not separator:
            continue
        split_at = name.rfind(separator)
        if split_at <= 0:
            continue
        suffix = name[split_at + len(separator) :]
        if not suffix.isdigit():
            continue
        base = name[:split_at]
        return base, separator, int(suffix), len(suffix)
    return None


def _next_name_from_seed(seed_name: str, taken_names: set[str], options: NamingOptions) -> str:
    if seed_name not in taken_names:
        return seed_name

    separators = tuple(dict.fromkeys((options.separator, "_", ".", "-", " ")))
    parsed = _parse_trailing_number(seed_name, separators)
    if parsed:
        base, separator, number, width = parsed
        next_number = max(1, number + 1)
        while True:
            candidate = f"{base}{separator}{next_number:0{max(1, width)}d}"
            if candidate not in taken_names:
                return candidate
            next_number += 1

    # Fallback for names that do not already end with numbers.
    next_number = 1
    while True:
        candidate = f"{seed_name}{options.separator}{next_number:0{max(1, int(options.padding))}d}"
        if candidate not in taken_names:
            return candidate
        next_number += 1


def _strip_repeated_affix(value: str, affix: str, *, from_start: bool) -> str:
    if not affix:
        return value
    result = value
    if from_start:
        while result.startswith(affix):
            result = result[len(affix) :]
    else:
        while result.endswith(affix):
            result = result[: -len(affix)]
    return result


def _apply_affixes_to_name(
    *,
    current_name: str,
    prefix: str,
    suffix: str,
    options: NamingOptions,
    preset_prefix: str,
    prefix_position: str,
    suffix_position: str,
) -> str:
    """Apply prefix/suffix while keeping suffix ordered before numeric indices."""
    name = current_name
    parsed = _parse_trailing_number(name, tuple(dict.fromkeys((options.separator, "_", ".", "-", " "))))
    base = name
    trailing_number = None
    trailing_width = max(1, int(options.padding))
    trailing_separator = options.separator
    if parsed:
        base, trailing_separator, trailing_number, trailing_width = parsed

    if prefix:
        stem = _strip_repeated_affix(base, prefix, from_start=True)
        if preset_prefix:
            stem = _strip_prefix_chain(stem, preset_prefix)
            if prefix_position == "AFTER_PRESET":
                base = f"{preset_prefix}{prefix}{stem}"
            else:
                base = f"{prefix}{preset_prefix}{stem}"
        else:
            base = f"{prefix}{stem}"

    if trailing_number is not None:
        numeric_part = f"{trailing_separator}{trailing_number:0{max(1, trailing_width)}d}"
        if suffix and suffix_position == "BEFORE_NUMBER":
            base = _strip_repeated_affix(base, suffix, from_start=False)
            return f"{base}{suffix}{numeric_part}"
        result = f"{base}{numeric_part}"
        if suffix and suffix_position == "AFTER_NUMBER":
            result = _strip_repeated_affix(result, suffix, from_start=False)
            return f"{result}{suffix}"
        return result

    result = base
    if suffix:
        result = _strip_repeated_affix(result, suffix, from_start=False)
        result = f"{result}{suffix}"
    return result


def _live_timer():
    try:
        _normalize_new_ids_only()
    except Exception as exc:  # pragma: no cover - Blender runtime guard.
        print(f"[NoDotNames] Live rename failed: {exc!r}")
    return 0.35


def _on_live_renaming_toggled(self, context):
    """Refresh caches and normalize when live-rename gets enabled."""
    _reset_pointer_cache()
    if getattr(self, "enable_live_renaming", False):
        try:
            _normalize_all_ids()
        except Exception as exc:  # pragma: no cover - Blender runtime guard.
            print(f"[NoDotNames] Live rename toggle failed: {exc!r}")


def _ensure_scene_properties() -> None:
    """Define scene properties if they are missing (partial registration guard)."""
    if not hasattr(bpy.types.Scene, "nct_find_text"):
        bpy.types.Scene.nct_find_text = StringProperty(
            name="Find",
            description="Text to find in duplicated object names before replacement",
            default="_low",
        )
    if not hasattr(bpy.types.Scene, "nct_replace_text"):
        bpy.types.Scene.nct_replace_text = StringProperty(
            name="Replace",
            description="Replacement text used in duplicated object names",
            default="_high",
        )
    if not hasattr(bpy.types.Scene, "nct_affix_prefix"):
        bpy.types.Scene.nct_affix_prefix = StringProperty(
            name="Prefix",
            description="Prefix to add to object names",
            default="",
            maxlen=64,
        )
    if not hasattr(bpy.types.Scene, "nct_affix_suffix"):
        bpy.types.Scene.nct_affix_suffix = StringProperty(
            name="Suffix",
            description="Suffix to add before trailing numeric sequence (e.g. _low)",
            default="",
            maxlen=64,
        )
    if not hasattr(bpy.types.Scene, "nct_affix_scope"):
        bpy.types.Scene.nct_affix_scope = EnumProperty(
            name="Scope",
            items=(
                ("SELECTED", "Selected", "Only selected objects"),
                ("ALL", "All", "All objects in file"),
            ),
            default="SELECTED",
        )
    if not hasattr(bpy.types.Scene, "nct_affix_prefix_position"):
        bpy.types.Scene.nct_affix_prefix_position = EnumProperty(
            name="Prefix Placement",
            items=(
                ("BEFORE_PRESET", "Before Preset Prefix", "Place custom prefix before preset prefix"),
                ("AFTER_PRESET", "After Preset Prefix", "Place custom prefix after preset prefix"),
            ),
            default="AFTER_PRESET",
        )
    if not hasattr(bpy.types.Scene, "nct_affix_suffix_position"):
        bpy.types.Scene.nct_affix_suffix_position = EnumProperty(
            name="Suffix Placement",
            items=(
                ("BEFORE_NUMBER", "Before Number", "Place suffix before trailing numeric index"),
                ("AFTER_NUMBER", "After Number", "Place suffix after trailing numeric index"),
            ),
            default="AFTER_NUMBER",
        )
    if not hasattr(bpy.types.Scene, "nct_linked_data_duplicate"):
        bpy.types.Scene.nct_linked_data_duplicate = BoolProperty(
            name="Linked Data",
            description="Keep duplicated objects linked to the same object data",
            default=False,
        )
    if not hasattr(bpy.types.Scene, "nct_hierarchy_parent_name"):
        bpy.types.Scene.nct_hierarchy_parent_name = StringProperty(
            name="Base Name",
            description="Root name for hierarchy (e.g. Arm_L, Spine, Prop_Chair)",
            default="Root",
            maxlen=64,
        )
    if not hasattr(bpy.types.Scene, "nct_hierarchy_mode"):
        bpy.types.Scene.nct_hierarchy_mode = EnumProperty(
            name="Mode",
            description="Chain: sequential index for controls/bones. Branch: cascading part names",
            items=(
                ("CHAIN", "Chain", "Sequential index (Ctrl_Spine_01, Ctrl_Spine_02) - for control/bone chains"),
                ("BRANCH", "Branch", "Cascading names (Arm_L, Arm_L_Upper, Arm_L_Hand) - for skeletal hierarchy"),
            ),
            default="BRANCH",
        )
    if not hasattr(bpy.types.Scene, "nct_hierarchy_prefix"):
        bpy.types.Scene.nct_hierarchy_prefix = StringProperty(
            name="Prefix",
            description="Optional prefix (e.g. CTRL_, MCH_, DEF_). Leave empty to use preset",
            default="",
            maxlen=16,
        )
    if not hasattr(bpy.types.Scene, "nct_batch_mode"):
        bpy.types.Scene.nct_batch_mode = EnumProperty(
            name="Mode",
            items=(
                ("REGEX", "Regex", "Find/replace with regex"),
                ("TEMPLATE", "Template", "Token-based template"),
            ),
            default="TEMPLATE",
        )
    if not hasattr(bpy.types.Scene, "nct_batch_scope"):
        bpy.types.Scene.nct_batch_scope = EnumProperty(
            name="Scope",
            items=(
                ("ALL", "All", "All datablocks"),
                ("SELECTED", "Selected", "Selected objects only"),
            ),
            default="ALL",
        )
    if not hasattr(bpy.types.Scene, "nct_batch_find"):
        bpy.types.Scene.nct_batch_find = StringProperty(
            name="Find",
            description=(
                "Find text to replace. Plain text is literal. "
                "For regex, wrap pattern in braces: {pattern}. "
                "Examples: {\\.\\d{3}$}, {^(SM_|M_|T_)}, {(_low|_high)$}. "
                "Use capture groups for replacements like \\1, \\2."
            ),
            default=r"{\.\d{3}$}",
            maxlen=256,
        )
    if not hasattr(bpy.types.Scene, "nct_batch_replace"):
        bpy.types.Scene.nct_batch_replace = StringProperty(
            name="Replace",
            description=(
                "Replacement text for regex matches. Use backreferences like "
                "\\\\1, \\\\2 from capture groups in Find. Examples: '_' or "
                "'SM_\\\\1'. Leave empty to remove matches."
            ),
            default="_",
            maxlen=256,
        )
    if not hasattr(bpy.types.Scene, "nct_batch_template"):
        bpy.types.Scene.nct_batch_template = StringProperty(
            name="Template",
            description="Tokens: {type}, {basename}, {index}, {sep}",
            default="{type}_{basename}_{index}",
            maxlen=256,
        )
    if not hasattr(bpy.types.Scene, "nct_batch_preview"):
        bpy.types.Scene.nct_batch_preview = CollectionProperty(type=NCT_PG_batch_preview_item)
    if not hasattr(bpy.types.Scene, "nct_batch_preview_index"):
        bpy.types.Scene.nct_batch_preview_index = IntProperty(default=0)
    if not hasattr(bpy.types.Scene, "nct_validation_report"):
        bpy.types.Scene.nct_validation_report = CollectionProperty(type=NCT_PG_violation_item)
    if not hasattr(bpy.types.Scene, "nct_validation_report_index"):
        bpy.types.Scene.nct_validation_report_index = IntProperty(default=0)
    if not hasattr(bpy.types.Scene, "nct_validator_filter_foldout"):
        bpy.types.Scene.nct_validator_filter_foldout = BoolProperty(
            name="Validator Data Types",
            description="Show/hide validator data-type filter options",
            default=False,
        )
    if not hasattr(bpy.types.Scene, "nct_validator_search_filter"):
        bpy.types.Scene.nct_validator_search_filter = StringProperty(
            name="Search",
            description="Filter violations by name or collection type",
            default="",
            maxlen=128,
        )
    for collection_name in TRACKED_BLEND_DATA_COLLECTIONS:
        prop_name = f"nct_validator_include_{collection_name}"
        if not hasattr(bpy.types.Scene, prop_name):
            setattr(
                bpy.types.Scene,
                prop_name,
                BoolProperty(
                    name=collection_name.replace("_", " ").title(),
                    description=f"Include {collection_name.replace('_', ' ')} in validator checks/fixes",
                    default=collection_name in VALIDATOR_DEFAULT_INCLUDE,
                ),
            )
    if not hasattr(bpy.types.Scene, "nct_affix_foldout"):
        bpy.types.Scene.nct_affix_foldout = BoolProperty(
            name="Affix Tools",
            description="Show/hide affix tools",
            default=False,
        )
    if not hasattr(bpy.types.Scene, "nct_duplicate_foldout"):
        bpy.types.Scene.nct_duplicate_foldout = BoolProperty(
            name="Duplicate + Replace",
            description="Show/hide duplicate+replace tools",
            default=False,
        )
    if not hasattr(bpy.types.Scene, "nct_hierarchy_foldout"):
        bpy.types.Scene.nct_hierarchy_foldout = BoolProperty(
            name="Hierarchy Rename",
            description="Show/hide hierarchy rename tools",
            default=False,
        )
    if not hasattr(bpy.types.Scene, "nct_batch_foldout"):
        bpy.types.Scene.nct_batch_foldout = BoolProperty(
            name="Batch Rename",
            description="Show/hide batch rename tools",
            default=False,
        )
    if not hasattr(bpy.types.Scene, "nct_editor_foldout"):
        bpy.types.Scene.nct_editor_foldout = BoolProperty(
            name="Naming Convention Editor",
            description="Show/hide naming convention editor",
            default=False,
        )
    if not hasattr(bpy.types.Scene, "nct_editor_preset_name"):
        bpy.types.Scene.nct_editor_preset_name = StringProperty(
            name="Profile Name",
            description="Name of the convention profile being edited",
            default="Studio Profile",
            maxlen=64,
        )
    if not hasattr(bpy.types.Scene, "nct_editor_separator_style"):
        bpy.types.Scene.nct_editor_separator_style = EnumProperty(
            name="Separator",
            items=(
                ("UNDERSCORE", "Underscore (_)", ""),
                ("DOT", "Dot (.)", ""),
                ("DASH", "Dash (-)", ""),
                ("SPACE", "Space ( )", ""),
                ("CUSTOM", "Custom", ""),
            ),
            default="UNDERSCORE",
        )
    if not hasattr(bpy.types.Scene, "nct_editor_custom_separator"):
        bpy.types.Scene.nct_editor_custom_separator = StringProperty(
            name="Custom Separator",
            default="_",
            maxlen=8,
        )
    if not hasattr(bpy.types.Scene, "nct_editor_padding"):
        bpy.types.Scene.nct_editor_padding = IntProperty(name="Padding", default=3, min=1, max=8)
    if not hasattr(bpy.types.Scene, "nct_editor_case_mode"):
        bpy.types.Scene.nct_editor_case_mode = EnumProperty(
            name="Case",
            items=(
                ("PRESERVE", "Preserve", ""),
                ("UPPER", "UPPER", ""),
                ("LOWER", "lower", ""),
                ("TITLE", "Title", ""),
            ),
            default="PRESERVE",
        )
    if not hasattr(bpy.types.Scene, "nct_editor_prefix_meshes"):
        bpy.types.Scene.nct_editor_prefix_meshes = StringProperty(name="Meshes", default="SM_", maxlen=24)
    if not hasattr(bpy.types.Scene, "nct_editor_prefix_materials"):
        bpy.types.Scene.nct_editor_prefix_materials = StringProperty(name="Materials", default="M_", maxlen=24)
    if not hasattr(bpy.types.Scene, "nct_editor_prefix_textures"):
        bpy.types.Scene.nct_editor_prefix_textures = StringProperty(name="Textures", default="T_", maxlen=24)
    if not hasattr(bpy.types.Scene, "nct_editor_prefix_images"):
        bpy.types.Scene.nct_editor_prefix_images = StringProperty(name="Images", default="T_", maxlen=24)
    if not hasattr(bpy.types.Scene, "nct_editor_prefix_objects"):
        bpy.types.Scene.nct_editor_prefix_objects = StringProperty(
            name="Objects + Mesh Data",
            default="SM_",
            maxlen=24,
        )
    if not hasattr(bpy.types.Scene, "nct_editor_prefix_armatures"):
        bpy.types.Scene.nct_editor_prefix_armatures = StringProperty(name="Armatures", default="SK_", maxlen=24)
    if not hasattr(bpy.types.Scene, "nct_editor_prefix_collections"):
        bpy.types.Scene.nct_editor_prefix_collections = StringProperty(name="Collections", default="COL_", maxlen=24)
    for collection_name in TRACKED_BLEND_DATA_COLLECTIONS:
        if collection_name in {"meshes", "objects"}:
            continue
        prop_name = f"nct_editor_prefix_{collection_name}"
        if not hasattr(bpy.types.Scene, prop_name):
            setattr(
                bpy.types.Scene,
                prop_name,
                StringProperty(
                    name=collection_name.replace("_", " ").title(),
                    default=DEFAULT_PREFIX_MAP.get(collection_name, ""),
                    maxlen=24,
                ),
            )


from .ops import (
    NCT_OT_duplicate_replace,
    NCT_OT_apply_affixes,
    NCT_OT_fix_all_violations,
    NCT_OT_fix_selected_violation,
    NCT_OT_validator_select_all,
    NCT_OT_validator_deselect_all,
    NCT_OT_hierarchy_rename,
    NCT_OT_batch_rename_preview,
    NCT_OT_batch_rename_apply,
    NCT_UL_batch_preview,
    NCT_OT_preset_save,
    NCT_PG_batch_preview_item,
    NCT_PG_violation_item,
    NCT_UL_validation_report,
    NCT_OT_validator_run,
    NCT_OT_validator_export_report,
    NCT_OT_switch_scene_to_preset,
    NCT_OT_editor_load_active_preset,
    NCT_OT_editor_save_profile,
    NCT_OT_editor_export_profile,
    NCT_OT_editor_import_profile,
    NCT_OT_preset_import,
    NCT_OT_preset_delete,
)


def _preset_enum_items(self, context):
    items = [("CUSTOM", "Custom", "Use settings below")]
    for k in BUILTIN_PRESETS:
        items.append((_preset_enum_id(k, is_builtin=True), k, ""))
    try:
        prefs = self if getattr(self, "custom_presets_json", None) is not None else _get_preferences()
        if prefs:
            for k in _load_custom_presets(prefs):
                if k not in BUILTIN_PRESETS:
                    items.append((_preset_enum_id(k, is_builtin=False), k, "Saved preset"))
    except Exception:
        pass  # Return base items only on context/prefs access errors during registration
    return items


from .ui import NCT_PT_tools, NamingConventionPreferences


CLASSES = (
    NCT_PG_batch_preview_item,
    NCT_PG_violation_item,
    NCT_UL_batch_preview,
    NCT_UL_validation_report,
    NCT_OT_batch_rename_apply,
    NCT_OT_batch_rename_preview,
    NCT_OT_apply_affixes,
    NCT_OT_duplicate_replace,
    NCT_OT_editor_export_profile,
    NCT_OT_editor_import_profile,
    NCT_OT_editor_load_active_preset,
    NCT_OT_editor_save_profile,
    NCT_OT_fix_all_violations,
    NCT_OT_fix_selected_violation,
    NCT_OT_validator_select_all,
    NCT_OT_validator_deselect_all,
    NCT_OT_hierarchy_rename,
    NCT_OT_preset_delete,
    NCT_OT_preset_import,
    NCT_OT_preset_save,
    NCT_OT_switch_scene_to_preset,
    NCT_OT_validator_run,
    NCT_OT_validator_export_report,
    NCT_PT_tools,
    NamingConventionPreferences,
)


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    _ensure_scene_properties()
    _reset_pointer_cache()
    if not bpy.app.timers.is_registered(_live_timer):
        bpy.app.timers.register(_live_timer, first_interval=0.35, persistent=True)


def unregister():
    if bpy.app.timers.is_registered(_live_timer):
        bpy.app.timers.unregister(_live_timer)
    _STATE["cache"] = {}
    for prop_name in (
        "nct_find_text",
        "nct_replace_text",
        "nct_affix_prefix",
        "nct_affix_suffix",
        "nct_affix_scope",
        "nct_affix_prefix_position",
        "nct_affix_suffix_position",
        "nct_linked_data_duplicate",
        "nct_hierarchy_parent_name",
        "nct_hierarchy_mode",
        "nct_hierarchy_prefix",
        "nct_batch_mode",
        "nct_batch_scope",
        "nct_batch_find",
        "nct_batch_replace",
        "nct_batch_template",
        "nct_batch_preview",
        "nct_batch_preview_index",
        "nct_validation_report",
        "nct_validation_report_index",
        "nct_validator_filter_foldout",
        "nct_validator_search_filter",
        "nct_affix_foldout",
        "nct_duplicate_foldout",
        "nct_hierarchy_foldout",
        "nct_batch_foldout",
        "nct_editor_foldout",
        "nct_editor_preset_name",
        "nct_editor_separator_style",
        "nct_editor_custom_separator",
        "nct_editor_padding",
        "nct_editor_case_mode",
        "nct_editor_prefix_meshes",
        "nct_editor_prefix_materials",
        "nct_editor_prefix_textures",
        "nct_editor_prefix_images",
        "nct_editor_prefix_objects",
        "nct_editor_prefix_armatures",
        "nct_editor_prefix_collections",
    ):
        if hasattr(bpy.types.Scene, prop_name):
            delattr(bpy.types.Scene, prop_name)
    for collection_name in TRACKED_BLEND_DATA_COLLECTIONS:
        prop_name = f"nct_editor_prefix_{collection_name}"
        if hasattr(bpy.types.Scene, prop_name):
            delattr(bpy.types.Scene, prop_name)
        include_prop = f"nct_validator_include_{collection_name}"
        if hasattr(bpy.types.Scene, include_prop):
            delattr(bpy.types.Scene, include_prop)
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)
