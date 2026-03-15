"""UI classes for NoDot Names."""

import bpy

from bpy.types import AddonPreferences, Panel
from bpy.props import BoolProperty, EnumProperty, IntProperty, StringProperty

from .constants import TRACKED_BLEND_DATA_COLLECTIONS
from .editor_preset import apply_preset_to_editor
from . import (
    _ensure_scene_properties,
    _get_active_preset,
    _get_preferences,
    _on_live_renaming_toggled,
    _preset_enum_items,
)
from .ops import (
    NCT_OT_apply_affixes,
    NCT_OT_batch_rename_apply,
    NCT_OT_batch_rename_preview,
    NCT_OT_duplicate_replace,
    NCT_OT_editor_export_profile,
    NCT_OT_editor_import_profile,
    NCT_OT_editor_load_active_preset,
    NCT_OT_editor_save_profile,
    NCT_OT_fix_all_violations,
    NCT_OT_fix_selected_violation,
    NCT_OT_hierarchy_rename,
    NCT_OT_preset_delete,
    NCT_OT_preset_import,
    NCT_OT_switch_scene_to_preset,
    NCT_OT_validator_deselect_all,
    NCT_OT_validator_export_report,
    NCT_OT_validator_run,
    NCT_OT_validator_select_all,
)


_DATA_TYPE_ICONS = {
    "objects": "OBJECT_DATA",
    "meshes": "MESH_DATA",
    "collections": "OUTLINER_COLLECTION",
    "materials": "MATERIAL",
    "lights": "LIGHT",
    "cameras": "CAMERA_DATA",
    "armatures": "ARMATURE_DATA",
    "actions": "ACTION",
    "node_groups": "NODETREE",
    "images": "IMAGE_DATA",
    "textures": "TEXTURE",
    "curves": "CURVE_DATA",
    "fonts": "FONT_DATA",
    "scenes": "SCENE_DATA",
    "shape_keys": "SHAPEKEY_DATA",
    "sounds": "SOUND",
    "speakers": "SPEAKER",
    "texts": "TEXT",
    "volumes": "VOLUME_DATA",
    "worlds": "WORLD_DATA",
}


def _icon_for_data_type(collection_name: str) -> str:
    return _DATA_TYPE_ICONS.get(collection_name, "DOT")


def _on_active_preset_changed(self, context):
    """Keep editor fields in sync when preset dropdown changes."""
    try:
        scene = context.scene if context is not None else getattr(bpy.context, "scene", None)
        if scene is None:
            return
        apply_preset_to_editor(scene, _get_active_preset(self))
    except Exception:
        pass


class NCT_PT_tools(Panel):
    bl_label = "Nodot"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Nodot"

    def draw(self, context):
        _ensure_scene_properties()
        layout = self.layout
        scene = context.scene
        prefs = _get_preferences()

        if prefs and hasattr(prefs, "enable_live_renaming"):
            toggle_row = layout.row(align=True)
            enabled = bool(getattr(prefs, "enable_live_renaming", False))
            toggle_row.prop(
                prefs,
                "enable_live_renaming",
                text="Live Rename: ON" if enabled else "Live Rename: OFF",
                toggle=True,
                icon="CHECKMARK" if enabled else "PAUSE",
            )
        layout.separator(factor=0.5)

        preset_box = layout.box()
        preset_box.label(text="Preset", icon="PRESET")
        col = preset_box.column(align=True)
        if prefs and hasattr(prefs, "active_preset"):
            col.prop(prefs, "active_preset", text="")
        row = col.row(align=True)
        row.operator(NCT_OT_preset_import.bl_idname, text="Import .ndot", icon="IMPORT")
        row.operator(NCT_OT_switch_scene_to_preset.bl_idname, text="Apply to File", icon="FILE_REFRESH")

        valid_box = layout.box()
        valid_box.label(text="Project Validator", icon="VIEWZOOM")
        vcol = valid_box.column(align=True)
        if hasattr(scene, "nct_validator_filter_foldout"):
            filter_header = vcol.row(align=True)
            filter_open = bool(getattr(scene, "nct_validator_filter_foldout", False))
            filter_header.prop(
                scene,
                "nct_validator_filter_foldout",
                text="Data Types",
                emboss=False,
                icon="TRIA_DOWN" if filter_open else "TRIA_RIGHT",
            )
            if filter_open:
                filter_items = []
                for collection_name in TRACKED_BLEND_DATA_COLLECTIONS:
                    prop_name = f"nct_validator_include_{collection_name}"
                    if hasattr(scene, prop_name):
                        filter_items.append((prop_name, collection_name.replace("_", " ")))
                if filter_items:
                    grid = vcol.row(align=True)
                    columns = [grid.column(align=True), grid.column(align=True), grid.column(align=True)]
                    for idx, (prop_name, label) in enumerate(filter_items):
                        collection_name = prop_name.removeprefix("nct_validator_include_")
                        columns[idx % 3].prop(
                            scene,
                            prop_name,
                            text=label,
                            icon=_icon_for_data_type(collection_name),
                        )
        row = vcol.row(align=True)
        row.operator(NCT_OT_validator_run.bl_idname, text="Run", icon="VIEWZOOM")
        row.operator(NCT_OT_fix_all_violations.bl_idname, text="Fix All", icon="CHECKMARK")
        row.operator(NCT_OT_validator_export_report.bl_idname, text="", icon="EXPORT")
        if hasattr(scene, "nct_validation_report") and scene.nct_validation_report:
            vcol.label(text=f"{len(scene.nct_validation_report)} violation(s)", icon="ERROR")
            if hasattr(scene, "nct_validator_search_filter"):
                vcol.prop(scene, "nct_validator_search_filter", text="", icon="VIEWZOOM")
            row = vcol.row(align=True)
            row.operator(NCT_OT_validator_select_all.bl_idname, text="All", icon="CHECKBOX_HLT")
            row.operator(NCT_OT_validator_deselect_all.bl_idname, text="None", icon="CHECKBOX_DEHLT")
            row.operator(NCT_OT_fix_selected_violation.bl_idname, text="Fix Selected", icon="CHECKMARK")
            vcol.template_list(
                "NCT_UL_validation_report",
                "",
                scene,
                "nct_validation_report",
                scene,
                "nct_validation_report_index",
                rows=6,
            )
            idx = min(max(0, scene.nct_validation_report_index), len(scene.nct_validation_report) - 1)
            item = scene.nct_validation_report[idx]
            vcol.label(text=item.message, icon="INFO")
        else:
            vcol.label(text="Run validator to scan for violations", icon="INFO")

        layout.separator()
        layout.label(text="Rename Tools", icon="SORTALPHA")
        affix_box = layout.box()
        affix_open = bool(getattr(scene, "nct_affix_foldout", False))
        header = affix_box.row(align=True)
        header.prop(
            scene,
            "nct_affix_foldout",
            text="Affix Tools",
            emboss=False,
            icon="TRIA_DOWN" if affix_open else "TRIA_RIGHT",
        )
        if affix_open:
            acol = affix_box.column(align=True)
            if hasattr(scene, "nct_affix_scope"):
                acol.prop(scene, "nct_affix_scope", text="Scope")
            if hasattr(scene, "nct_affix_prefix"):
                acol.prop(scene, "nct_affix_prefix")
            if hasattr(scene, "nct_affix_prefix_position"):
                acol.prop(scene, "nct_affix_prefix_position", text="Prefix Placement")
            if hasattr(scene, "nct_affix_suffix"):
                acol.prop(scene, "nct_affix_suffix")
            if hasattr(scene, "nct_affix_suffix_position"):
                acol.prop(scene, "nct_affix_suffix_position", text="Suffix Placement")
            row = acol.row(align=True)
            op = row.operator(NCT_OT_apply_affixes.bl_idname, text="Add Prefix", icon="PLUS")
            op.mode = "PREFIX"
            op = row.operator(NCT_OT_apply_affixes.bl_idname, text="Add Suffix", icon="PLUS")
            op.mode = "SUFFIX"

        duplicate_box = layout.box()
        duplicate_open = bool(getattr(scene, "nct_duplicate_foldout", False))
        header = duplicate_box.row(align=True)
        header.prop(
            scene,
            "nct_duplicate_foldout",
            text="Duplicate + Replace",
            emboss=False,
            icon="TRIA_DOWN" if duplicate_open else "TRIA_RIGHT",
        )
        if duplicate_open:
            col = duplicate_box.column(align=True)
            if hasattr(scene, "nct_find_text"):
                col.prop(scene, "nct_find_text", text="Find")
            if hasattr(scene, "nct_replace_text"):
                col.prop(scene, "nct_replace_text", text="Replace")
            if hasattr(scene, "nct_linked_data_duplicate"):
                col.prop(scene, "nct_linked_data_duplicate", text="Linked Data")
            col.operator(NCT_OT_duplicate_replace.bl_idname, icon="DUPLICATE")

        hier_box = layout.box()
        hier_open = bool(getattr(scene, "nct_hierarchy_foldout", False))
        header = hier_box.row(align=True)
        header.prop(
            scene,
            "nct_hierarchy_foldout",
            text="Hierarchy Rename",
            emboss=False,
            icon="TRIA_DOWN" if hier_open else "TRIA_RIGHT",
        )
        if hier_open:
            col = hier_box.column(align=True)
            if hasattr(scene, "nct_hierarchy_parent_name"):
                col.prop(scene, "nct_hierarchy_parent_name", text="Base Name")
            if hasattr(scene, "nct_hierarchy_mode"):
                col.prop(scene, "nct_hierarchy_mode", text="Mode")
            if hasattr(scene, "nct_hierarchy_prefix"):
                col.prop(scene, "nct_hierarchy_prefix", text="Prefix")
            col.operator(NCT_OT_hierarchy_rename.bl_idname, text="Rename Hierarchy", icon="OUTLINER")

        batch_box = layout.box()
        batch_open = bool(getattr(scene, "nct_batch_foldout", False))
        header = batch_box.row(align=True)
        header.prop(
            scene,
            "nct_batch_foldout",
            text="Batch Rename",
            emboss=False,
            icon="TRIA_DOWN" if batch_open else "TRIA_RIGHT",
        )
        if batch_open:
            col = batch_box.column(align=True)
            mode = getattr(scene, "nct_batch_mode", "TEMPLATE")
            if hasattr(scene, "nct_batch_mode"):
                col.prop(scene, "nct_batch_mode", text="Mode")
            if hasattr(scene, "nct_batch_scope"):
                col.prop(scene, "nct_batch_scope", text="Scope")
            if mode == "REGEX":
                if hasattr(scene, "nct_batch_find"):
                    col.prop(scene, "nct_batch_find", text="Find (regex)")
                if hasattr(scene, "nct_batch_replace"):
                    col.prop(scene, "nct_batch_replace", text="Replace")
            else:
                if hasattr(scene, "nct_batch_template"):
                    col.prop(scene, "nct_batch_template", text="Template")
            row = col.row(align=True)
            row.operator(NCT_OT_batch_rename_preview.bl_idname, icon="VIEWZOOM")
            row.operator(NCT_OT_batch_rename_apply.bl_idname, icon="EXPORT")
            if hasattr(scene, "nct_batch_preview") and scene.nct_batch_preview:
                col.template_list(
                    "NCT_UL_batch_preview",
                    "",
                    scene,
                    "nct_batch_preview",
                    scene,
                    "nct_batch_preview_index",
                    rows=4,
                )


class NamingConventionPreferences(AddonPreferences):
    bl_idname = __package__

    active_preset: EnumProperty(
        name="Preset",
        description="Active naming convention preset",
        items=_preset_enum_items,
        update=_on_active_preset_changed,
    )
    custom_presets_json: StringProperty(name="Custom Presets", default="{}", maxlen=65535)
    enable_live_renaming: BoolProperty(
        name="Live Rename New Data",
        description="Normalize names as soon as new datablocks are created",
        default=True,
        update=_on_live_renaming_toggled,
    )
    separator_style: EnumProperty(
        name="Suffix Separator",
        description="Separator between the base name and numeric suffix",
        items=(
            ("UNDERSCORE", "Underscore (_)", "Use '_' as separator"),
            ("DOT", "Dot (.)", "Use '.' as separator (Blender default)"),
            ("DASH", "Dash (-)", "Use '-' as separator"),
            ("SPACE", "Space ( )", "Use a space as separator"),
            ("CUSTOM", "Custom", "Use your own separator"),
        ),
        default="UNDERSCORE",
    )
    custom_separator: StringProperty(name="Custom Separator", default="_", maxlen=8)
    padding: IntProperty(name="Number Padding", default=3, min=1, max=8)
    case_mode: EnumProperty(
        name="Base Name Case",
        items=(
            ("PRESERVE", "Preserve", ""),
            ("UPPER", "UPPER", ""),
            ("LOWER", "lower", ""),
            ("TITLE", "Title", ""),
        ),
        default="PRESERVE",
    )
    custom_ignore_prefixes: StringProperty(
        name="Ignore Prefixes",
        description="Comma-separated prefixes to skip (e.g. zenuv, myaddon_). Built-in: zenuv, zenbbq, decalmachine, fluent, substance",
        default="",
        maxlen=512,
    )

    def draw(self, context):
        _ensure_scene_properties()
        layout = self.layout
        scene = context.scene
        col = layout.column(align=True)
        row = col.row(align=True)
        row.prop(self, "active_preset")
        row.operator(NCT_OT_preset_delete.bl_idname, text="", icon="TRASH")
        toggle_row = col.row(align=True)
        enabled = bool(getattr(self, "enable_live_renaming", False))
        toggle_row.prop(
            self,
            "enable_live_renaming",
            text="Live Rename: ON" if enabled else "Live Rename: OFF",
            toggle=True,
            icon="CHECKMARK" if enabled else "PAUSE",
        )
        if hasattr(self, "custom_ignore_prefixes"):
            col.prop(self, "custom_ignore_prefixes", text="Ignore Prefixes")

        layout.separator(factor=1.0)
        editor_box = layout.box()
        editor_box.label(text="Naming Convention Editor", icon="TEXT")
        ecol = editor_box.column(align=True)
        ecol.prop(scene, "nct_editor_preset_name", text="Profile")
        ecol.prop(scene, "nct_editor_separator_style", text="Separator")
        if getattr(scene, "nct_editor_separator_style", "UNDERSCORE") == "CUSTOM":
            ecol.prop(scene, "nct_editor_custom_separator", text="Custom")
        ecol.prop(scene, "nct_editor_padding", text="Padding")
        ecol.prop(scene, "nct_editor_case_mode", text="Case")

        pcol = ecol.column(align=True)
        pcol.label(text="Prefix Rules", icon="COPY_ID")
        prefix_items = []
        shown_objects_mesh = False
        for collection_name in TRACKED_BLEND_DATA_COLLECTIONS:
            if collection_name == "meshes":
                prefix_items.append(("nct_editor_prefix_objects", "objects + meshes"))
                shown_objects_mesh = True
                continue
            if collection_name == "objects":
                if not shown_objects_mesh:
                    prefix_items.append(("nct_editor_prefix_objects", "objects + meshes"))
                continue
            prop_name = f"nct_editor_prefix_{collection_name}"
            if hasattr(scene, prop_name):
                prefix_items.append((prop_name, collection_name.replace("_", " ")))
        if prefix_items:
            grid = pcol.row(align=True)
            columns = [grid.column(align=True), grid.column(align=True), grid.column(align=True)]
            for idx, (prop_name, label) in enumerate(prefix_items):
                collection_name = "objects" if prop_name == "nct_editor_prefix_objects" else prop_name.removeprefix("nct_editor_prefix_")
                columns[idx % 3].prop(
                    scene,
                    prop_name,
                    text=label,
                    icon=_icon_for_data_type(collection_name),
                )

        ecol.separator()
        row = ecol.row(align=True)
        row.operator(NCT_OT_editor_load_active_preset.bl_idname, text="Load Preset", icon="IMPORT")
        row.operator(NCT_OT_editor_save_profile.bl_idname, text="Save As Preset", icon="FILE_TICK")
        row = ecol.row(align=True)
        row.operator(NCT_OT_editor_import_profile.bl_idname, text="Import .ndot", icon="FILEBROWSER")
        row.operator(NCT_OT_editor_export_profile.bl_idname, text="Export .ndot", icon="EXPORT")

