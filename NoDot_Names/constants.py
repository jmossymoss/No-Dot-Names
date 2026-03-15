"""Shared addon constants/state."""

# Datablock name prefixes to ignore (case-insensitive). Addon-generated content
# that would conflict if renamed. Users can add more via Preferences > Ignore Prefixes.
# Data types enabled by default in Project Validator (others off to reduce noise).
VALIDATOR_DEFAULT_INCLUDE = frozenset({
    "armatures",
    "cameras",
    "collections",
    "curves",
    "lights",
    "meshes",
    "objects",
    "worlds",
})

IGNORE_NAME_PREFIXES = (
    "zenuv",
    "zen uv",
    "zenbbq",
    "zen bbq",
    "decalmachine",
    "fluent",
    "substance",
    "layer painter",
    "materialiq",
)

TRACKED_BLEND_DATA_COLLECTIONS = (
    "actions",
    "armatures",
    "brushes",
    "cache_files",
    "cameras",
    "collections",
    "curves",
    "fonts",
    "grease_pencils",
    "hair_curves",
    "images",
    "lattices",
    "libraries",
    "lightprobes",
    "lights",
    "linestyles",
    "masks",
    "materials",
    "meshes",
    "metaballs",
    "movieclips",
    "node_groups",
    "objects",
    "paint_curves",
    "palettes",
    "particles",
    "pointclouds",
    "scenes",
    "shape_keys",
    "sounds",
    "speakers",
    "texts",
    "textures",
    "volumes",
    "worlds",
)

