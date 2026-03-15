"""Operator/property/UIList classes."""

import json
import re

import bpy
from bpy.props import BoolProperty, EnumProperty, StringProperty
from bpy.types import Operator, PropertyGroup, UIList

from .core import NamingOptions, NamingPreset, apply_case, expand_rename_template
from .editor_preset import apply_preset_to_editor, build_editor_preset
from .profile_io import export_profile_file, import_profile_file
from .presets import BUILTIN_PRESETS, preset_to_dict
from . import (
    _apply_affixes_to_name,
    _batch_regex_rename_name,
    _build_options,
    _is_ignored_name,
    _split_suffix,
    _strip_known_prefix,
    _collect_violations,
    _ensure_scene_properties,
    _expected_name_for_preset,
    _get_active_preset,
    _get_preferences,
    _load_custom_presets,
    _next_name_from_seed,
    _normalize_all_ids,
    _normalize_all_ids_with_options,
    _preset_enum_value_for_name,
    _preset_name_from_enum_value,
    _reset_pointer_cache,
    _save_custom_preset,
    _sync_object_and_data_names,
    _iter_tracked_collections,
    _selected_validator_collections,
)


class NCT_OT_normalize_existing(Operator):
    bl_idname = "nct.normalize_existing"
    bl_label = "Normalize Existing Names"
    bl_description = "Convert existing duplicate suffixes to this add-on's convention"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        renamed = _normalize_all_ids()
        self.report({"INFO"}, f"Renamed {renamed} datablock(s)")
        return {"FINISHED"}


class NCT_OT_duplicate_replace(Operator):
    bl_idname = "nct.duplicate_replace"
    bl_label = "Duplicate + Replace Text"
    bl_description = "Duplicate selected objects and rename by replacing text while preserving numeric sequence"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected = list(context.selected_objects)
        if not selected:
            self.report({"WARNING"}, "Select at least one object")
            return {"CANCELLED"}

        preferences = _get_preferences()
        options = _build_options(preferences) if preferences else NamingOptions()
        scene = context.scene
        find_text = scene.nct_find_text
        replace_text = scene.nct_replace_text
        linked_data = scene.nct_linked_data_duplicate

        existing_names = {obj.name for obj in bpy.data.objects}
        new_objects = []
        for source in selected:
            duplicate = source.copy()
            if source.data is not None and not linked_data:
                duplicate.data = source.data.copy()

            if source.users_collection:
                for collection in source.users_collection:
                    collection.objects.link(duplicate)
            else:
                context.scene.collection.objects.link(duplicate)

            seed_name = source.name.replace(find_text, replace_text) if find_text else source.name
            final_name = _next_name_from_seed(seed_name, existing_names, options)
            duplicate.name = final_name
            existing_names.add(final_name)
            new_objects.append(duplicate)

        for obj in context.selected_objects:
            obj.select_set(False)
        for obj in new_objects:
            obj.select_set(True)
        if new_objects:
            context.view_layer.objects.active = new_objects[0]

        _reset_pointer_cache()
        self.report({"INFO"}, f"Created {len(new_objects)} duplicate(s)")
        return {"FINISHED"}


class NCT_OT_apply_affixes(Operator):
    bl_idname = "nct.apply_affixes"
    bl_label = "Apply Affix"
    bl_description = "Add prefix/suffix to object names (suffix is inserted before numeric suffix)"
    bl_options = {"REGISTER", "UNDO"}

    mode: EnumProperty(
        name="Mode",
        items=(
            ("PREFIX", "Prefix", "Apply only prefix"),
            ("SUFFIX", "Suffix", "Apply only suffix"),
            ("BOTH", "Both", "Apply both prefix and suffix"),
        ),
        default="BOTH",
    )

    def execute(self, context):
        _ensure_scene_properties()
        scene = context.scene
        raw_prefix = (getattr(scene, "nct_affix_prefix", "") or "").strip()
        raw_suffix = (getattr(scene, "nct_affix_suffix", "") or "").strip()
        prefix = raw_prefix if self.mode in {"PREFIX", "BOTH"} else ""
        suffix = raw_suffix if self.mode in {"SUFFIX", "BOTH"} else ""
        scope = getattr(scene, "nct_affix_scope", "SELECTED")

        if not prefix and not suffix:
            self.report({"WARNING"}, "Enter a prefix first" if self.mode == "PREFIX" else "Enter a suffix first")
            return {"CANCELLED"}

        preferences = _get_preferences()
        options = _build_options(preferences) if preferences else NamingOptions()
        active_preset = _get_active_preset(preferences) if preferences else NamingPreset()
        preset_prefix = active_preset.prefix_map.get("objects", "") or active_preset.prefix_map.get("meshes", "")
        prefix_position = getattr(scene, "nct_affix_prefix_position", "BEFORE_PRESET")
        suffix_position = getattr(scene, "nct_affix_suffix_position", "BEFORE_NUMBER")
        targets = list(context.selected_objects) if scope == "SELECTED" else list(bpy.data.objects)
        if not targets:
            self.report({"WARNING"}, "No target objects found")
            return {"CANCELLED"}

        existing = {obj.name for obj in bpy.data.objects}
        renamed = 0
        for obj in targets:
            candidate = _apply_affixes_to_name(
                current_name=obj.name,
                prefix=prefix,
                suffix=suffix,
                options=options,
                preset_prefix=preset_prefix,
                prefix_position=prefix_position,
                suffix_position=suffix_position,
            )
            if not candidate or candidate == obj.name:
                continue
            final = _next_name_from_seed(candidate, existing - {obj.name}, options)
            if final != obj.name:
                existing.discard(obj.name)
                obj.name = final
                existing.add(final)
                renamed += 1

        _reset_pointer_cache()
        self.report({"INFO"}, f"Updated {renamed} object name(s)")
        return {"FINISHED"}


class NCT_OT_fix_all_violations(Operator):
    bl_idname = "nct.fix_all_violations"
    bl_label = "Fix All Violations"
    bl_description = "Rename all datablocks that violate the active naming convention"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        preferences = _get_preferences()
        if not preferences:
            return {"CANCELLED"}
        preset = _get_active_preset(preferences)
        options = NamingOptions(separator=preset.separator, padding=preset.padding, case_mode=preset.case_mode)
        fixed = 0
        selected = _selected_validator_collections(context.scene)
        violations = _collect_violations(preferences, selected)
        needs_object_data_sync = any("Object/data mismatch" in message for *_rest, message in violations)
        grouped: dict[str, list[tuple[str, str, str]]] = {}
        for coll_name, current_name, expected_name, message in violations:
            grouped.setdefault(coll_name, []).append((current_name, expected_name, message))

        for coll_name, rows in grouped.items():
            collection = getattr(bpy.data, coll_name, None)
            if collection is None:
                continue
            existing = {item.name for item in collection}
            for current_name, expected_name, _message in rows:
                item = collection.get(current_name)
                if not item:
                    continue
                if expected_name == item.name:
                    continue
                final = _next_name_from_seed(expected_name, existing, options)
                if final != item.name:
                    existing.discard(item.name)
                    item.name = final
                    existing.add(final)
                    fixed += 1
        if needs_object_data_sync:
            fixed += _sync_object_and_data_names(preset=preset, preferences=preferences, options=options)
        fixed += _normalize_all_ids_with_options(options)
        _reset_pointer_cache()
        _refresh_validator_report(context)
        self.report({"INFO"}, f"Fixed {fixed} violation(s)")
        return {"FINISHED"}


class NCT_OT_hierarchy_rename(Operator):
    bl_idname = "nct.hierarchy_rename"
    bl_label = "Hierarchy Rename"
    bl_description = (
        "Rename parent and children using rigging conventions: "
        "Chain mode for control/bone chains, Branch mode for skeletal hierarchy"
    )
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        selected = list(context.selected_objects)
        if not selected:
            self.report({"WARNING"}, "Select at least one root object (no parent)")
            return {"CANCELLED"}
        scene = context.scene
        base_name = (getattr(scene, "nct_hierarchy_parent_name", "") or "Root").strip() or "Root"
        mode = getattr(scene, "nct_hierarchy_mode", "BRANCH")
        prefix_override = (getattr(scene, "nct_hierarchy_prefix", "") or "").strip()
        preferences = _get_preferences()
        preset = _get_active_preset(preferences) if preferences else NamingPreset()
        options = NamingOptions(
            separator=preset.separator,
            padding=max(1, int(preset.padding)),
            case_mode=preset.case_mode,
        )
        obj_prefix = prefix_override or preset.prefix_map.get("objects", "") or preset.prefix_map.get("meshes", "")
        sep = options.separator
        pad = options.padding
        renamed = 0

        def _stem(obj) -> str:
            """Extract meaningful part from object name for branch naming."""
            raw = obj.name.split(".")[0]
            stripped = _strip_known_prefix(raw, "objects", preferences)
            base, _num, _w = _split_suffix(stripped)
            part = (base or "Unnamed").strip() or "Unnamed"
            return apply_case(part, preset.case_mode)

        for obj in selected:
            if obj.parent:
                continue
            existing = {o.name for o in bpy.data.objects}
            root_base = f"{obj_prefix}{base_name}" if obj_prefix else base_name
            root_final = _next_name_from_seed(root_base, existing, options)
            if root_final != obj.name:
                existing.discard(obj.name)
                obj.name = root_final
                existing.add(root_final)
                renamed += 1

            if mode == "CHAIN":
                chain_base = root_final
                for i, child in enumerate(obj.children_recursive, start=1):
                    suffix = f"{sep}{i:0{pad}d}" if pad >= 3 else f"{sep}{i}"
                    candidate = f"{chain_base}{suffix}"
                    final = _next_name_from_seed(candidate, existing, options)
                    if final != child.name:
                        existing.discard(child.name)
                        child.name = final
                        existing.add(final)
                        renamed += 1
            else:
                # BRANCH: cascading path, siblings with same stem get index
                def _rename_branch(parent_path: str, parent_obj):
                    children = list(parent_obj.children)
                    if not children:
                        return
                    stems = [_stem(c) for c in children]
                    stem_counts = {}
                    for s in stems:
                        stem_counts[s] = stem_counts.get(s, 0) + 1
                    stem_next = {}
                    for child in children:
                        stem = _stem(child)
                        if stem_counts.get(stem, 0) > 1:
                            idx = stem_next.get(stem, 1)
                            stem_next[stem] = idx + 1
                            suffix = f"{sep}{stem}{sep}{idx:0{pad}d}" if pad >= 3 else f"{sep}{stem}{sep}{idx}"
                        else:
                            suffix = f"{sep}{stem}"
                        candidate = f"{parent_path}{suffix}"
                        final = _next_name_from_seed(candidate, existing, options)
                        if final != child.name:
                            existing.discard(child.name)
                            child.name = final
                            existing.add(final)
                            nonlocal renamed
                            renamed += 1
                        _rename_branch(final, child)

                _rename_branch(root_final, obj)

        _reset_pointer_cache()
        self.report({"INFO"}, f"Renamed {renamed} object(s)")
        return {"FINISHED"}


class NCT_OT_batch_rename_preview(Operator):
    bl_idname = "nct.batch_rename_preview"
    bl_label = "Preview"
    bl_description = "Preview renames without applying"
    bl_options = {"REGISTER"}

    def execute(self, context):
        _ensure_scene_properties()
        scene = context.scene
        scene.nct_batch_preview.clear()
        mode = getattr(scene, "nct_batch_mode", "TEMPLATE")
        find_pattern = getattr(scene, "nct_batch_find", "") or ""
        replace_pattern = getattr(scene, "nct_batch_replace", "") or ""
        template = getattr(scene, "nct_batch_template", "{type}_{basename}_{index}") or "{type}_{basename}_{index}"
        use_selected = getattr(scene, "nct_batch_scope", "ALL") == "SELECTED"
        preferences = _get_preferences()
        options = _build_options(preferences) if preferences else NamingOptions()
        type_tokens = {"meshes": "SM", "materials": "M", "textures": "T", "images": "T", "objects": "Obj", "armatures": "SK", "collections": "COL"}
        selected_objs = set(context.selected_objects) if use_selected else None
        for coll_name, collection in _iter_tracked_collections():
            targets = list(collection)
            if use_selected and coll_name == "objects":
                targets = [t for t in targets if t in selected_objs]
            for i, item in enumerate(targets):
                if mode == "REGEX" and find_pattern:
                    new_name = _batch_regex_rename_name(item.name, find_pattern, replace_pattern)
                    if new_name is None:
                        continue
                else:
                    base = re.sub(r"[._\- ]\d{3,}$", "", item.name)
                    tok = type_tokens.get(coll_name, coll_name[:3].upper())
                    new_name = expand_rename_template(
                        template, type_token=tok, basename=base or "Item", index=i + 1, separator=options.separator, padding=options.padding
                    )
                if new_name and new_name != item.name:
                    entry = scene.nct_batch_preview.add()
                    entry.old_name = item.name
                    entry.new_name = new_name
                    entry.collection_name = coll_name
        self.report({"INFO"}, f"Preview: {len(scene.nct_batch_preview)} rename(s)")
        return {"FINISHED"}


class NCT_OT_batch_rename_apply(Operator):
    bl_idname = "nct.batch_rename_apply"
    bl_label = "Apply Batch Rename"
    bl_description = "Apply the previewed renames"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _ensure_scene_properties()
        scene = context.scene
        preferences = _get_preferences()
        options = _build_options(preferences) if preferences else NamingOptions()
        applied = 0
        taken_by_coll: dict[str, set[str]] = {}
        for entry in scene.nct_batch_preview:
            coll = getattr(bpy.data, entry.collection_name, None)
            if not coll:
                continue
            item = coll.get(entry.old_name)
            if not item or not entry.new_name or entry.new_name == entry.old_name:
                continue
            taken = taken_by_coll.setdefault(entry.collection_name, {o.name for o in coll})
            final = _next_name_from_seed(entry.new_name, taken, options)
            if final != item.name:
                taken.discard(item.name)
                item.name = final
                taken.add(final)
                applied += 1
        scene.nct_batch_preview.clear()
        _reset_pointer_cache()
        self.report({"INFO"}, f"Applied {applied} rename(s)")
        return {"FINISHED"}


class NCT_UL_batch_preview(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            layout.label(text=f"{item.old_name} -> {item.new_name}", icon="SORTALPHA")
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.label(text=item.new_name, icon="SORTALPHA")


class NCT_OT_preset_save(Operator):
    bl_idname = "nct.preset_save"
    bl_label = "Save Preset"
    bl_description = "Save current convention as a named preset"
    bl_options = {"REGISTER"}

    preset_name: StringProperty(name="Preset Name", default="My Preset", maxlen=64)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=320)

    def draw(self, context):
        self.layout.prop(self, "preset_name")

    def execute(self, context):
        preferences = _get_preferences()
        if not preferences:
            return {"CANCELLED"}
        preset = NamingPreset(
            name=self.preset_name.strip() or "Custom",
            separator=preferences.custom_separator if preferences.separator_style == "CUSTOM" else {"UNDERSCORE": "_", "DOT": ".", "DASH": "-", "SPACE": " "}.get(preferences.separator_style, "_"),
            padding=max(1, int(getattr(preferences, "padding", 3))),
            case_mode=getattr(preferences, "case_mode", "PRESERVE"),
            prefix_map=_get_active_preset(preferences).prefix_map.copy(),
        )
        _save_custom_preset(preferences, preset)
        preferences.active_preset = _preset_enum_value_for_name(preset.name, preferences)
        self.report({"INFO"}, f"Saved preset '{preset.name}'")
        return {"FINISHED"}


class NCT_PG_batch_preview_item(PropertyGroup):
    old_name: StringProperty()
    new_name: StringProperty()
    collection_name: StringProperty()


class NCT_PG_violation_item(PropertyGroup):
    collection_name: StringProperty()
    item_name: StringProperty()
    expected_name: StringProperty()
    message: StringProperty()
    selected: BoolProperty(name="Selected", default=False)


class NCT_UL_validation_report(UIList):
    def draw_item(self, context, layout, data, item, icon, active_data, active_propname):
        if self.layout_type in {"DEFAULT", "COMPACT"}:
            row = layout.row(align=True)
            row.prop(item, "selected", text="", emboss=False, icon="CHECKMARK" if item.selected else "CHECKBOX_DEHLT")
            row.label(text=f"[{item.collection_name}] {item.item_name}", icon="ERROR")
            row.label(text=f"-> {item.expected_name}")
        elif self.layout_type == "GRID":
            layout.alignment = "CENTER"
            layout.prop(item, "selected", text="", emboss=False)
            layout.label(text=item.item_name, icon="ERROR")

    def filter_items(self, context, data, property):
        items = getattr(data, property)
        search = (getattr(data, "nct_validator_search_filter", "") or "").strip().lower()
        if not search:
            return [], []  # Default: show all
        filtered = [
            (i, item)
            for i, item in enumerate(items)
            if search in (item.item_name or "").lower()
            or search in (item.collection_name or "").lower()
            or search in (item.expected_name or "").lower()
        ]
        return [f[0] for f in filtered], [f[1] for f in filtered]


def _refresh_validator_report(context) -> int:
    _ensure_scene_properties()
    scene = context.scene
    scene.nct_validation_report.clear()
    preferences = _get_preferences()
    selected = _selected_validator_collections(scene)
    violations = _collect_violations(preferences, selected) if preferences else []
    for coll_name, item_name, expected_name, message in violations:
        row = scene.nct_validation_report.add()
        row.collection_name = coll_name
        row.item_name = item_name
        row.expected_name = expected_name
        row.message = message
        row.selected = False
    scene.nct_validation_report_index = 0
    return len(scene.nct_validation_report)


class NCT_OT_validator_run(Operator):
    bl_idname = "nct.validator_run"
    bl_label = "Run Project Validator"
    bl_description = "Scan all datablocks and generate a detailed naming violation report"
    bl_options = {"REGISTER"}

    def execute(self, context):
        total = _refresh_validator_report(context)
        self.report({"INFO"}, f"Validator found {total} violation(s)")
        return {"FINISHED"}


class NCT_OT_fix_selected_violation(Operator):
    bl_idname = "nct.fix_selected_violation"
    bl_label = "Fix Selected"
    bl_description = "Fix all selected violations in the report"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        _ensure_scene_properties()
        scene = context.scene
        report = scene.nct_validation_report
        selected_items = [r for r in report if getattr(r, "selected", False)]
        if not selected_items:
            self.report({"WARNING"}, "Select one or more violations (use checkboxes)")
            return {"CANCELLED"}
        preferences = _get_preferences()
        preset = _get_active_preset(preferences) if preferences else NamingPreset()
        options = NamingOptions(separator=preset.separator, padding=preset.padding, case_mode=preset.case_mode)
        fixed = 0
        needs_object_data_sync = False
        for item in selected_items:
            coll_name = item.collection_name
            current_name = item.item_name
            expected_name = item.expected_name
            collection = getattr(bpy.data, coll_name, None)
            if not collection:
                continue
            datablock = collection.get(current_name)
            if not datablock:
                continue
            existing = {i.name for i in collection}
            final = _next_name_from_seed(expected_name, existing - {current_name}, options)
            if final != current_name:
                existing.discard(current_name)
                datablock.name = final
                existing.add(final)
                fixed += 1
            if "Object/data mismatch" in item.message:
                needs_object_data_sync = True
        if needs_object_data_sync:
            fixed += _sync_object_and_data_names(preset=preset, preferences=preferences, options=options)
        _reset_pointer_cache()
        _refresh_validator_report(context)
        self.report({"INFO"}, f"Fixed {fixed} violation(s)")
        return {"FINISHED"}


class NCT_OT_validator_select_all(Operator):
    bl_idname = "nct.validator_select_all"
    bl_label = "Select All"
    bl_description = "Select all violations in the report"
    bl_options = {"REGISTER"}

    def execute(self, context):
        _ensure_scene_properties()
        scene = context.scene
        for item in scene.nct_validation_report:
            item.selected = True
        return {"FINISHED"}


class NCT_OT_validator_deselect_all(Operator):
    bl_idname = "nct.validator_deselect_all"
    bl_label = "Deselect All"
    bl_description = "Deselect all violations in the report"
    bl_options = {"REGISTER"}

    def execute(self, context):
        _ensure_scene_properties()
        scene = context.scene
        for item in scene.nct_validation_report:
            item.selected = False
        return {"FINISHED"}


class NCT_OT_validator_export_report(Operator):
    bl_idname = "nct.validator_export_report"
    bl_label = "Export Report"
    bl_description = "Export violation report to a text file for sharing or tracking"
    bl_options = {"REGISTER"}

    filepath: StringProperty(subtype="FILE_PATH", default="naming_violations.txt")
    filter_glob: StringProperty(default="*.txt", options={"HIDDEN"})

    def invoke(self, context, event):
        if not self.filepath or not self.filepath.lower().endswith(".txt"):
            self.filepath = "naming_violations.txt"
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        scene = context.scene
        report = getattr(scene, "nct_validation_report", None)
        if not report:
            self.report({"WARNING"}, "Run validator first")
            return {"CANCELLED"}
        lines = [f"NoDot Names - Violation Report ({len(report)} items)", "=" * 50, ""]
        for r in report:
            lines.append(f"[{r.collection_name}] {r.item_name}")
            lines.append(f"  → Expected: {r.expected_name}")
            lines.append(f"  → {r.message}")
            lines.append("")
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
        except OSError as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        self.report({"INFO"}, f"Exported to {self.filepath}")
        return {"FINISHED"}


class NCT_OT_switch_scene_to_preset(Operator):
    bl_idname = "nct.switch_scene_to_preset"
    bl_label = "Switch File To Preset"
    bl_description = "Rename existing datablocks to match the currently selected preset"
    bl_options = {"REGISTER", "UNDO"}

    def execute(self, context):
        preferences = _get_preferences()
        if not preferences:
            return {"CANCELLED"}
        preset = _get_active_preset(preferences)
        options = NamingOptions(separator=preset.separator, padding=preset.padding, case_mode=preset.case_mode)
        changed = 0
        for coll_name, collection in _iter_tracked_collections():
            existing = {item.name for item in collection}
            for item in list(collection):
                if _is_ignored_name(item.name):
                    continue
                target = _expected_name_for_preset(item.name, coll_name, preset, preferences)
                if target == item.name:
                    continue
                final = _next_name_from_seed(target, existing, options)
                if final != item.name:
                    existing.discard(item.name)
                    item.name = final
                    existing.add(final)
                    changed += 1
        changed += _sync_object_and_data_names(preset=preset, preferences=preferences, options=options)
        changed += _normalize_all_ids_with_options(options)
        _reset_pointer_cache()
        _refresh_validator_report(context)
        self.report({"INFO"}, f"Converted {changed} datablock name(s) to '{preset.name}'")
        return {"FINISHED"}


class NCT_OT_editor_load_active_preset(Operator):
    bl_idname = "nct.editor_load_active_preset"
    bl_label = "Load Selected Preset"
    bl_description = "Copy selected preset rules into the naming convention editor"
    bl_options = {"REGISTER"}

    def execute(self, context):
        preferences = _get_preferences()
        if not preferences:
            return {"CANCELLED"}
        apply_preset_to_editor(context.scene, _get_active_preset(preferences))
        self.report({"INFO"}, "Loaded selected preset into editor")
        return {"FINISHED"}


class NCT_OT_editor_save_profile(Operator):
    bl_idname = "nct.editor_save_profile"
    bl_label = "Save Editor As Preset"
    bl_description = "Save editor rules as a custom preset and make it active"
    bl_options = {"REGISTER"}

    def execute(self, context):
        preferences = _get_preferences()
        if not preferences:
            return {"CANCELLED"}
        preset = build_editor_preset(context.scene)
        _save_custom_preset(preferences, preset)
        preferences.active_preset = _preset_enum_value_for_name(preset.name, preferences)
        self.report({"INFO"}, f"Saved editor preset '{preset.name}'")
        return {"FINISHED"}


class NCT_OT_editor_export_profile(Operator):
    bl_idname = "nct.editor_export_profile"
    bl_label = "Export .ndot Profile"
    bl_description = "Export the editor rules as a shareable .ndot profile"
    bl_options = {"REGISTER"}

    filepath: StringProperty(subtype="FILE_PATH", default="naming_profile.ndot")
    filter_glob: StringProperty(default="*.ndot", options={"HIDDEN"})

    def invoke(self, context, event):
        if not self.filepath:
            self.filepath = "naming_profile.ndot"
        elif not self.filepath.lower().endswith(".ndot"):
            self.filepath += ".ndot"
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        path = self.filepath
        if not path.lower().endswith(".ndot"):
            path += ".ndot"
        export_profile_file(build_editor_preset(context.scene), path)
        self.report({"INFO"}, f"Exported profile to {path}")
        return {"FINISHED"}


class NCT_OT_editor_import_profile(Operator):
    bl_idname = "nct.editor_import_profile"
    bl_label = "Import .ndot Profile"
    bl_description = "Load editor rules from a .ndot profile file"
    bl_options = {"REGISTER"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.ndot", options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        try:
            preset = import_profile_file(self.filepath)
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        apply_preset_to_editor(context.scene, preset)
        self.report({"INFO"}, f"Imported profile '{preset.name}' into editor")
        return {"FINISHED"}


class NCT_OT_preset_import(Operator):
    bl_idname = "nct.preset_import"
    bl_label = "Import Preset"
    bl_description = "Import preset from .ndot profile file"
    bl_options = {"REGISTER"}

    filepath: StringProperty(subtype="FILE_PATH")
    filter_glob: StringProperty(default="*.ndot", options={"HIDDEN"})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {"RUNNING_MODAL"}

    def execute(self, context):
        preferences = _get_preferences()
        if not preferences:
            return {"CANCELLED"}
        try:
            preset = import_profile_file(self.filepath)
            _save_custom_preset(preferences, preset)
            preferences.active_preset = _preset_enum_value_for_name(preset.name, preferences)
            self.report({"INFO"}, f"Imported preset '{preset.name}'")
        except Exception as exc:
            self.report({"ERROR"}, str(exc))
            return {"CANCELLED"}
        return {"FINISHED"}


class NCT_OT_preset_delete(Operator):
    bl_idname = "nct.preset_delete"
    bl_label = "Delete Preset"
    bl_description = "Delete the selected custom preset"
    bl_options = {"REGISTER"}

    def execute(self, context):
        preferences = _get_preferences()
        if not preferences:
            return {"CANCELLED"}

        active_value = getattr(preferences, "active_preset", "CUSTOM") or "CUSTOM"
        preset_name = _preset_name_from_enum_value(active_value, preferences)
        if not preset_name or preset_name == "Custom" or preset_name in BUILTIN_PRESETS:
            self.report({"WARNING"}, "Only custom presets can be deleted")
            return {"CANCELLED"}

        custom = _load_custom_presets(preferences)
        if preset_name not in custom:
            self.report({"WARNING"}, f"Preset '{preset_name}' not found")
            return {"CANCELLED"}

        del custom[preset_name]
        preferences.custom_presets_json = json.dumps({k: preset_to_dict(v) for k, v in custom.items()})
        preferences.active_preset = "CUSTOM"
        self.report({"INFO"}, f"Deleted preset '{preset_name}'")
        return {"FINISHED"}

