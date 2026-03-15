# NoDot Names

**Blender add-on for studio naming conventions: presets, validation, and batch renaming.**

Replace Blender's default `.001` duplicate naming with configurable conventions (e.g. `_001`), and keep naming consistent across Unreal, Unity, or custom pipelines.

---

## Metadata

| | |
|---|---|
| **Author** | Jordan Moss |
| **Version** | 2.0.0 |
| **Blender** | 4.5+ |
| **License** | GNU GPL v3 or later |

---

## Features

### Presets
- **Unreal** – `SM_`, `M_`, `T_`, etc.
- **Unity** – `Mesh_`, `Mat_`, `Tex_`, etc.
- **Studio Pipeline** – `Geo_`, `Prop_`, `Rig_`, etc.
- **Custom** – Define your own in the Naming Convention Editor.

### Live Rename
- Converts new duplicates from `Cube.001` → `Cube_001` automatically.
- Toggle on/off in Preferences or the N-panel.

### Project Validator
- Scans datablocks for naming violations (prefix, case, separator, object/data mismatch).
- **Fix All** – Fix all violations.
- **Fix Selected** – Fix only checked items (multi-select).
- **Export Report** – Export violations to a text file.
- **Data Types** – Choose which datablocks to validate (default: objects, meshes, armatures, cameras, lights, collections, curves, worlds).

### Apply to File
- Switch presets and apply to the whole file.
- Converts names instead of stacking prefixes (e.g. `SM_Magazine_001` → `Mesh_Magazine_001` when switching Unreal → Unity).

### Naming Convention Editor
- Define prefixes per datablock type, separator, padding, and case.
- **Load Preset** – Load selected preset into the editor.
- **Save As Preset** – Save editor rules as a custom preset.
- **Import / Export .ndot** – Share profiles as `.ndot` files.

### Rename Tools
- **Affix Tools** – Add prefix/suffix (before/after preset prefix, before/after number).
- **Duplicate + Replace** – Duplicate objects with find/replace in names (e.g. `_low` → `_high`).
- **Hierarchy Rename** – Chain or branch naming for rigs and hierarchies.
- **Batch Rename** – Regex or template-based renaming with preview.

### Ignore List
- Skips addon-generated datablocks (zenUV, ZenBBQ, DecalMachine, etc.).
- Add custom prefixes in Preferences → **Ignore Prefixes** (comma-separated).

---

## Installation

1. Download the `nodot_names` folder or zip.
2. **Edit → Preferences → Add-ons → Install...**
3. Select the zip (or add the folder to your addons path).
4. Enable **NoDot Names**.

---

## Usage

### Quick Start
1. Open **Edit → Preferences → Add-ons → NoDot Names**.
2. Choose a **Preset** (Unreal, Unity, etc.).
3. Enable **Live Rename** to auto-normalize new datablocks.
4. Open the **N** sidebar (View3D) and select the **Nodot** tab.

### N-Panel (View3D → Sidebar → Nodot)

| Section | Description |
|---------|-------------|
| **Live Rename** | Toggle auto-normalization of new datablocks. |
| **Preset** | Select preset, **Import .ndot**, **Apply to File**. |
| **Project Validator** | **Run** to scan, **Fix All** or **Fix Selected**, **Export** report. Use checkboxes to select violations. |
| **Affix Tools** | Add prefix/suffix to selected or all objects. |
| **Duplicate + Replace** | Duplicate with find/replace in names. |
| **Hierarchy Rename** | **Chain** (indexed) or **Branch** (path-based) naming. |
| **Batch Rename** | Regex `{pattern}` or template `{type}_{basename}_{index}`. |

### Hierarchy Rename Modes
- **Chain** – Sequential index: `Ctrl_Spine_01`, `Ctrl_Spine_02`.
- **Branch** – Path-based: `Arm_L`, `Arm_L_Upper`, `Arm_L_Hand`.

### Batch Rename Regex
- Use `{...}` for regex: `{\.\d{3}$}` to match `.001`-style suffixes.
- Without braces, the pattern is treated as literal text.

---

## Preferences

- **Preset** – Active convention; delete custom presets with the trash icon.
- **Live Rename** – Auto-normalize new datablocks.
- **Ignore Prefixes** – Comma-separated prefixes to skip (e.g. `zenuv, myaddon_`).
- **Naming Convention Editor** – Profile name, separator, padding, case, prefix rules per datablock type.

---

## .ndot Profile Files

Export and import naming profiles as `.ndot` files to share across teams. Use **Import .ndot** in the N-panel to load a profile as the active preset, or **Import .ndot** in the editor to load into the editor for editing.

---

## License

GNU General Public License v3 or later. See [LICENSE](LICENSE).
