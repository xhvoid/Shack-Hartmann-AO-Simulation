# Tests verify the AO demonstrator documentation, data directories, and configuration provenance tags.

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]

CONFIG_FILES = [
    ROOT / "configs" / "ao_demo_2m_fast.yaml",
    ROOT / "configs" / "ao_demo_2m_portfolio.yaml",
    ROOT / "configs" / "ao_demo_2m_research.yaml",
    ROOT / "configs" / "ao_demo_10m_high_order_reference.yaml",
]

REQUIRED_DOCS = [
    ROOT / "docs" / "architecture.md",
    ROOT / "docs" / "validation.md",
    ROOT / "docs" / "ao_realistic_demo_parameter_source_inventory.md",
    ROOT / "docs" / "ao_realistic_demo_parameter_source_inventory.pdf",
]

REQUIRED_DEVELOPER_DATA_DIRS = [
    ROOT / "data" / "external",
    ROOT / "data" / "cache",
]

REQUIRED_RUNTIME_DATA_DIRS = [
    ROOT / "src" / "shwfs_ao" / "resources" / "public",
    ROOT / "src" / "shwfs_ao" / "resources" / "samples",
    ROOT / "src" / "shwfs_ao" / "resources" / "literature_profiles",
    ROOT / "src" / "shwfs_ao" / "resources" / "synthetic_presets",
    ROOT / "src" / "shwfs_ao" / "resources" / "reference_metrics",
]

REQUIRED_CONFIG_GROUPS = [
    "telescope:",
    "atmosphere:",
    "wfs:",
    "detector:",
    "dm:",
    "registration:",
    "control:",
    "science:",
    "source:",
    "static_aberration:",
    "archive_validation:",
    "caching:",
]

ALLOWED_SOURCE_CLASSES = {
    "direct_public_data",
    "literature_derived",
    "synthetic_literature_inspired",
    "synthetic_assumed",
    "package_reference",
}

LEGACY_SOURCE_CLASSES = {
    "public_api",
    "public_archive",
    "literature",
    "synthetic",
    "out_of_scope",
}


def test_public_documentation_is_checked_in():
    for path in REQUIRED_DOCS:
        assert path.is_file(), f"Missing public documentation: {path}"
        assert path.stat().st_size > 200, f"Public documentation looks empty: {path}"


def test_data_directory_skeleton_exists():
    for path in REQUIRED_DEVELOPER_DATA_DIRS:
        assert path.is_dir(), f"Missing data directory: {path}"
        assert (path / ".gitkeep").is_file(), f"Missing tracked .gitkeep in {path}"
    for path in REQUIRED_RUNTIME_DATA_DIRS:
        assert path.is_dir(), f"Missing runtime resource directory: {path}"
        assert any(child.is_file() for child in path.iterdir()), f"Empty runtime resource directory: {path}"


def test_config_files_have_required_groups():
    for path in CONFIG_FILES:
        text = path.read_text(encoding="utf-8")
        for group in REQUIRED_CONFIG_GROUPS:
            assert group in text, f"{path.name} missing config group {group}"


def test_config_source_classes_use_allowed_taxonomy():
    for path in CONFIG_FILES:
        text = path.read_text(encoding="utf-8")
        values = set(re.findall(r"source_class:\s*([A-Za-z0-9_]+)", text))
        assert values, f"No source_class tags found in {path.name}"
        assert values <= ALLOWED_SOURCE_CLASSES, f"{path.name} has invalid source_class values: {values - ALLOWED_SOURCE_CLASSES}"
        assert not (values & LEGACY_SOURCE_CLASSES), f"{path.name} uses legacy source_class values: {values & LEGACY_SOURCE_CLASSES}"
