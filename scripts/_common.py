"""Shared helpers for the PawsKnowHow automation scripts.

Handles paths, breed-name slugging, and markdown-with-YAML-frontmatter I/O.
Kept dependency-light so every script can import it.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import yaml

# --- Paths -------------------------------------------------------------------

# Project root is the parent of this scripts/ directory.
ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
DRAFTS = CONTENT / "drafts"
APPROVED = CONTENT / "approved"
PUBLISHED = CONTENT / "published"
TEMPLATES = ROOT / "templates"
BRAND_STYLE = TEMPLATES / "brand_style.md"


def slugify(breed: str) -> str:
    """'Border Collie' -> 'border-collie' (used for filenames + URLs)."""
    slug = breed.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "-", slug)
    return slug.strip("-")


def breed_image_path(breed: str, image_dir: str) -> Path:
    """Resolve the 4x5 Instagram image for a breed.

    Images are stored as '{Breed Name}.png' (original casing/spacing).
    """
    return Path(image_dir) / f"{breed}.png"


# --- Frontmatter markdown I/O ------------------------------------------------

_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def dump_post(path: Path, metadata: dict[str, Any], body: str) -> None:
    """Write a markdown file with a YAML frontmatter block."""
    path.parent.mkdir(parents=True, exist_ok=True)
    front = yaml.safe_dump(metadata, sort_keys=False, allow_unicode=True).strip()
    path.write_text(f"---\n{front}\n---\n\n{body.strip()}\n", encoding="utf-8")


def load_post(path: Path) -> tuple[dict[str, Any], str]:
    """Read a markdown file, returning (metadata, body).

    Raises ValueError if the file has no frontmatter block.
    """
    text = path.read_text(encoding="utf-8")
    match = _FRONTMATTER_RE.match(text)
    if not match:
        raise ValueError(f"{path.name} has no YAML frontmatter block.")
    metadata = yaml.safe_load(match.group(1)) or {}
    body = match.group(2).strip()
    return metadata, body
