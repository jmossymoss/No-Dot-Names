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

"""Core naming helpers shared by the Blender integration and tests."""

from dataclasses import dataclass, field
import re
from typing import Iterable


_DUPLICATE_SUFFIX_RE = re.compile(r"^(?P<base>.+?)(?P<separator>[._\- ])(?P<number>\d{3,})$")


# Common collection -> prefix mappings for game engine conventions
DEFAULT_PREFIX_MAP: dict[str, str] = {
    "meshes": "SM_",
    "materials": "M_",
    "textures": "T_",
    "images": "T_",
    "objects": "",
    "armatures": "SK_",
    "actions": "A_",
    "collections": "COL_",
    "cameras": "CAM_",
    "lights": "L_",
    "worlds": "W_",
    "node_groups": "NG_",
    "curves": "CRV_",
    "volumes": "V_",
}


@dataclass(frozen=True)
class NamingOptions:
    """Configuration used when formatting duplicate names."""

    separator: str = "_"
    padding: int = 3
    case_mode: str = "PRESERVE"


@dataclass
class NamingPreset:
    """Named convention profile with per-type prefixes and rules."""

    name: str = "Custom"
    separator: str = "_"
    padding: int = 3
    case_mode: str = "PRESERVE"
    prefix_map: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_PREFIX_MAP))


def parse_duplicate_suffix(name: str) -> tuple[str, str, int] | None:
    """Return ``(base, separator, number)`` when ``name`` has a duplicate suffix."""
    match = _DUPLICATE_SUFFIX_RE.match(name)
    if not match:
        return None
    return (
        match.group("base"),
        match.group("separator"),
        int(match.group("number")),
    )


def apply_case(name: str, case_mode: str) -> str:
    """Apply the configured case transform to the duplicate base name."""
    mode = (case_mode or "PRESERVE").upper()
    if mode == "UPPER":
        return name.upper()
    if mode == "LOWER":
        return name.lower()
    if mode == "TITLE":
        return name.title()
    return name


def format_duplicate_name(base: str, number: int, options: NamingOptions) -> str:
    """Format a duplicate name from its base + index."""
    transformed_base = apply_case(base, options.case_mode)
    number_text = f"{number:0{max(1, int(options.padding))}d}"
    return f"{transformed_base}{options.separator}{number_text}"


def _candidate_separators(options: NamingOptions) -> tuple[str, ...]:
    # Try longer separators first so custom values like "__" are parsed correctly.
    ordered = [options.separator, "_", ".", "-", " "]
    unique = [sep for sep in dict.fromkeys(ordered) if sep]
    return tuple(sorted(unique, key=len, reverse=True))


def _parse_suffix_with_separators(name: str, separators: tuple[str, ...]) -> tuple[str, int, int] | None:
    for separator in separators:
        pattern = re.compile(rf"^(?P<base>.+?){re.escape(separator)}(?P<number>\d+)$")
        match = pattern.match(name)
        if not match:
            continue
        number_text = match.group("number")
        return match.group("base"), int(number_text), len(number_text)
    return None


def _has_sequence_names(root: str, names: set[str], separators: tuple[str, ...]) -> bool:
    for separator in separators:
        prefix = f"{root}{separator}"
        for name in names:
            if not name.startswith(prefix):
                continue
            suffix = name[len(prefix) :]
            if suffix.isdigit():
                return True
    return False


def _resolve_sequence_base(
    base: str,
    names: set[str],
    options: NamingOptions,
) -> tuple[str, int | None, int | None]:
    """
    Collapse nested bases like ``Cube_001`` into ``Cube`` when that sequence exists.

    This avoids generating names such as ``Cube_001_001`` when users duplicate an
    already-normalized name, and keeps numbered names advancing naturally.
    """
    separators = _candidate_separators(options)
    parsed = _parse_suffix_with_separators(base, separators)
    if not parsed:
        return base, None, None

    root, number, width = parsed
    if root in names or _has_sequence_names(root, names, separators):
        return root, (number + 1), width

    return base, None, None


def _next_available_name(
    *,
    base: str,
    starting_number: int,
    taken: set[str],
    options: NamingOptions,
) -> str:
    number = max(1, int(starting_number))
    candidate = format_duplicate_name(base, number, options)
    while candidate in taken:
        number += 1
        candidate = format_duplicate_name(base, number, options)
    return candidate


def build_unique_duplicate_name(
    *,
    current_name: str,
    existing_names: Iterable[str],
    options: NamingOptions,
) -> str | None:
    """
    Return a normalized duplicate name or ``None`` when no change is required.

    Normalization is only attempted for names that look like Blender-generated
    duplicates (e.g. ``Cube.001``), and only when their base name still exists in
    the collection. This avoids rewriting user-authored dotted names.
    """
    parsed = parse_duplicate_suffix(current_name)
    if not parsed:
        return None

    base, _separator, number = parsed
    name_set = set(existing_names)
    if base not in name_set:
        return None

    resolved_base, root_starting_number, root_width = _resolve_sequence_base(base, name_set, options)
    effective_padding = options.padding
    if root_width is not None:
        effective_padding = max(int(options.padding), int(root_width))
    effective_options = NamingOptions(
        separator=options.separator,
        padding=effective_padding,
        case_mode=options.case_mode,
    )
    candidate = format_duplicate_name(resolved_base, number, effective_options)
    if candidate == current_name and current_name not in (name_set - {current_name}):
        return None

    taken = name_set - {current_name}
    if resolved_base != base:
        # Duplicating a suffixed item should continue the existing sequence.
        return _next_available_name(
            base=resolved_base,
            starting_number=root_starting_number or 1,
            taken=taken,
            options=effective_options,
        )

    return _next_available_name(
        base=resolved_base,
        starting_number=number,
        taken=taken,
        options=effective_options,
    )


def validate_name_against_convention(
    name: str,
    collection_name: str,
    preset: NamingPreset,
) -> str | None:
    """
    Return a violation message if the name does not match the convention, else None.
    """
    prefix = preset.prefix_map.get(collection_name, "")
    if prefix and not name.startswith(prefix):
        return f"Missing prefix '{prefix}'"
    base = name[len(prefix):] if prefix else name
    if not base:
        return "Empty name after prefix"
    if preset.case_mode == "UPPER" and base != base.upper():
        return "Base name should be UPPERCASE"
    if preset.case_mode == "LOWER" and base != base.lower():
        return "Base name should be lowercase"
    if preset.case_mode == "TITLE":
        expected = base.title()
        if base != expected:
            return "Base name should be Title Case"
    return None


def apply_regex_rename(name: str, find_pattern: str, replace_pattern: str) -> str | None:
    """Apply regex find/replace. Returns new name or None if no match."""
    try:
        new_name = re.sub(find_pattern, replace_pattern, name)
        return new_name if new_name != name else None
    except re.error:
        return None


def expand_rename_template(
    template: str,
    *,
    type_token: str,
    basename: str,
    index: int,
    separator: str = "_",
    padding: int = 3,
) -> str:
    """Expand {type}, {basename}, {index} tokens in a template."""
    return (
        template.replace("{type}", type_token)
        .replace("{basename}", basename)
        .replace("{index}", f"{index:0{max(1, padding)}d}")
        .replace("{sep}", separator)
    )
