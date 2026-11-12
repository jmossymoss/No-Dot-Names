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

"""Bone renaming: turns Blender's ``Bone.001`` into ``Bone_01`` (configurable).

Bones are not ID datablocks, so they are not covered by the regular
``bpy.data`` scan. This module tracks bone names per armature and renames
newly created / renamed bones that carry a Blender-style duplicate suffix.

Mirror side markers (``.L``, ``_R``, ``-Left`` ...) can be kept at the very end
of the name (``Arm.L.001`` -> ``Arm_01.L``) so Blender's X-Mirror and
Symmetrize keep pairing left/right bones.
"""

import re

# Blender-generated duplicate suffix: any separator followed by 3+ digits.
_DUP_RE = re.compile(r"^(?P<base>.+?)[._\- ](?P<num>\d{3,})$")
# Strict Blender dot suffix (.001), used by the "fix existing" operator.
_DOT_RE = re.compile(r"^(?P<base>.+?)\.(?P<num>\d{3,})$")
# Mirror side marker at the end of a name (what Blender's flip-name looks for).
_SIDE_RE = re.compile(r"^(?P<stem>.+?)(?P<side>[._\- ](?:L|R|l|r|Left|Right|left|right|LEFT|RIGHT))$")


def _split_side(base: str, keep_side: bool) -> tuple[str, str]:
    if not keep_side:
        return base, ""
    match = _SIDE_RE.match(base)
    if not match:
        return base, ""
    return match.group("stem"), match.group("side")


def _format(root: str, sep: str, number: int, width: int, side: str) -> str:
    return f"{root}{sep}{number:0{max(1, width)}d}{side}"


def _resolve(
    current_name: str,
    existing_names: set[str],
    *,
    separator: str,
    padding: int,
    keep_side: bool,
    require_base: bool,
):
    """Parse a duplicate-style name into ``(root, side, start_number, width, sep)``."""
    pattern = _DUP_RE if require_base else _DOT_RE
    match = pattern.match(current_name)
    if not match:
        return None
    base = match.group("base")
    number = int(match.group("num"))
    if require_base and base not in existing_names:
        return None

    sep = separator or "_"
    width = max(1, int(padding))
    stem, side = _split_side(base, keep_side)

    # Continue an existing sequence: duplicating Bone_01 gives Bone_01.001,
    # which should become Bone_02, not Bone_01_01.
    root = stem
    seq = re.match(rf"^(?P<root>.+?){re.escape(sep)}(?P<n>\d+)$", stem)
    if seq:
        root = seq.group("root")
        number = int(seq.group("n")) + 1
        width = max(width, len(seq.group("n")))
    return root, side, max(1, number), width, sep


def _first_free(root, sep, number, width, side, taken) -> tuple[str, int]:
    candidate = _format(root, sep, number, width, side)
    while candidate in taken:
        number += 1
        candidate = _format(root, sep, number, width, side)
    return candidate, number


def build_bone_name(
    current_name: str,
    existing_names: set[str],
    *,
    separator: str = "_",
    padding: int = 2,
    keep_side: bool = True,
    require_base: bool = True,
) -> str | None:
    """Return the new name for a single bone, or ``None`` when it should stay as is.

    ``require_base`` mirrors the add-on's rule for objects: only touch names that
    look like duplicates of a bone that still exists (``Bone.001`` while ``Bone``
    exists). The fix-existing operator turns it off.
    """
    res = _resolve(
        current_name, existing_names,
        separator=separator, padding=padding, keep_side=keep_side, require_base=require_base,
    )
    if res is None:
        return None
    root, side, number, width, sep = res
    candidate, _n = _first_free(root, sep, number, width, side, set(existing_names) - {current_name})
    return None if candidate == current_name else candidate


def _depth(bone) -> int:
    depth = 0
    parent = getattr(bone, "parent", None)
    while parent is not None and depth < 10000:
        depth += 1
        parent = getattr(parent, "parent", None)
    return depth


# --------------------------------------------------------------------------
# Blender integration
# --------------------------------------------------------------------------

_BONE_CACHE: dict[int, frozenset[str]] = {}


def _bone_collection(armature):
    """Edit bones while the armature is in Edit Mode, regular bones otherwise."""
    if getattr(armature, "is_editmode", False):
        return armature.edit_bones
    return armature.bones


def _is_editable(armature) -> bool:
    if getattr(armature, "library", None) is not None:
        return False
    override = getattr(armature, "override_library", None)
    if override is not None and getattr(override, "is_system_override", False):
        return False
    return True


def bone_settings_from_prefs(preferences) -> dict:
    mapping = {"UNDERSCORE": "_", "DOT": ".", "DASH": "-", "SPACE": " "}
    style = getattr(preferences, "bone_separator_style", "UNDERSCORE")
    if style == "CUSTOM":
        sep = getattr(preferences, "bone_custom_separator", "") or "_"
    else:
        sep = mapping.get(style, "_")
    return {
        "separator": sep,
        "padding": max(1, int(getattr(preferences, "bone_padding", 2))),
        "keep_side": bool(getattr(preferences, "bone_keep_side_last", True)),
    }


def rename_bones_in_armature(armature, settings: dict, *, only_names=None, require_base=True, is_ignored=None) -> int:
    """Rename matching bones of one armature. Returns number of renamed bones.

    Bones that end up in the same sequence (e.g. the pieces of a subdivided
    bone) are numbered in hierarchy order, parent first. Blender's subdivide
    creates them tail-first, so keeping its numbers would reverse the chain.
    """
    if not _is_editable(armature):
        return 0
    bones = _bone_collection(armature)
    existing = {bone.name for bone in bones}

    groups: dict[tuple, list] = {}
    for bone in bones:
        if only_names is not None and bone.name not in only_names:
            continue
        if is_ignored is not None and is_ignored(bone.name):
            continue
        res = _resolve(bone.name, existing, require_base=require_base, **settings)
        if res is None:
            continue
        root, side, number, width, sep = res
        groups.setdefault((root, side, sep), []).append((bone, number, width))

    renamed = 0
    for (root, side, sep), items in groups.items():
        start = min(number for _b, number, _w in items)
        width = max(w for _b, _n, w in items)
        items.sort(key=lambda item: (_depth(item[0]), item[1], item[0].name))
        next_number = start
        for bone, _number, _w in items:
            old = bone.name
            taken = existing - {old}
            new, used = _first_free(root, sep, next_number, width, side, taken)
            next_number = used + 1
            if new == old:
                continue
            try:
                # Setting .name goes through Blender's bone rename, which also
                # updates vertex groups, constraints, drivers and action channels.
                bone.name = new
            except Exception as exc:  # pragma: no cover - Blender runtime guard.
                print(f"[NoDotNames] Could not rename bone {old!r}: {exc!r}")
                continue
            existing.discard(old)
            existing.add(bone.name)
            renamed += 1
    return renamed


def reset_bone_cache(bpy_data) -> None:
    """Remember current bone names so only future changes get renamed."""
    _BONE_CACHE.clear()
    for armature in getattr(bpy_data, "armatures", []):
        try:
            _BONE_CACHE[armature.as_pointer()] = frozenset(b.name for b in _bone_collection(armature))
        except Exception:
            continue


def live_rename_bones(bpy_data, preferences, is_ignored=None) -> int:
    """Called from the live-rename timer: rename only new/changed bone names."""
    settings = bone_settings_from_prefs(preferences)
    renamed = 0
    seen = set()
    for armature in getattr(bpy_data, "armatures", []):
        try:
            pointer = armature.as_pointer()
            seen.add(pointer)
            names = frozenset(b.name for b in _bone_collection(armature))
            previous = _BONE_CACHE.get(pointer)
            if previous is None:
                # First time we see this armature (file load, append, undo):
                # don't rewrite an existing rig behind the user's back.
                _BONE_CACHE[pointer] = names
                continue
            if names == previous:
                continue
            changed = names - previous
            if changed:
                renamed += rename_bones_in_armature(
                    armature, settings, only_names=changed, is_ignored=is_ignored
                )
                names = frozenset(b.name for b in _bone_collection(armature))
            _BONE_CACHE[pointer] = names
        except Exception as exc:  # pragma: no cover - Blender runtime guard.
            print(f"[NoDotNames] Live bone rename failed: {exc!r}")
    for stale in set(_BONE_CACHE) - seen:
        _BONE_CACHE.pop(stale, None)
    return renamed
