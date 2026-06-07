"""Generate a PawsKnowHow blog draft for a breed and save it to content/drafts/.

Usage:
    python scripts/generate_blog.py "Border Collie"
    python scripts/generate_blog.py "Border Collie" --force   # overwrite draft

Flow:
    1. Fetch AKC source data (scripts/fetch_source.py).
    2. Call Claude (claude-opus-4-8) with the brand style guide as the system
       prompt and the source data as context, using structured outputs so we
       get a clean title / meta description / tags / body back.
    3. Write a markdown file with YAML frontmatter to content/drafts/.

Every draft is written with `approved: false`. A human must review the draft,
move it to content/approved/, and flip the flag before publish_blog.py will
touch it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date

import anthropic
from dotenv import load_dotenv

try:
    from _common import (
        BRAND_STYLE,
        DRAFTS,
        breed_image_path,
        dump_post,
        slugify,
    )
    from fetch_source import fetch_breed_source
except ImportError:  # pragma: no cover
    from scripts._common import (
        BRAND_STYLE,
        DRAFTS,
        breed_image_path,
        dump_post,
        slugify,
    )
    from scripts.fetch_source import fetch_breed_source

# Structured-output schema: forces Claude to return exactly these fields.
POST_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "meta_description": {"type": "string"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "body_markdown": {"type": "string"},
    },
    "required": ["title", "meta_description", "tags", "body_markdown"],
    "additionalProperties": False,
}


def _read_brand_style() -> str:
    return BRAND_STYLE.read_text(encoding="utf-8")


def _build_system_prompt() -> str:
    return (
        "You are the lead content writer for PawsKnowHow, a pet-education brand. "
        "Write a single, complete, publish-ready blog post about one dog breed, "
        "following this brand style guide exactly:\n\n"
        f"{_read_brand_style()}\n\n"
        "Output rules:\n"
        "- body_markdown is the full article in Markdown, ~900-1400 words, with "
        "  `##` section headings and short scannable paragraphs.\n"
        "- title is an engaging, SEO-aware post title (no markdown).\n"
        "- meta_description is <=155 characters, British English.\n"
        "- tags is 5-8 lowercase tags relevant to the breed and pet care.\n"
        "- British spelling throughout. Hedge all health claims. Positive framing only."
    )


def _build_user_prompt(breed: str, source: dict) -> str:
    return (
        f"Write the PawsKnowHow blog post for the **{breed}**.\n\n"
        "Here is source material scraped from the AKC (use it for facts; do not "
        "copy phrasing, and gently hedge anything health-related):\n\n"
        f"```json\n{json.dumps(source, indent=2, ensure_ascii=False)}\n```\n\n"
        "If a fact is missing from the source, rely on well-established general "
        "knowledge about the breed rather than inventing specifics."
    )


def generate_post(breed: str, *, force: bool = False) -> dict:
    """Generate one draft. Returns metadata dict; writes the markdown file."""
    load_dotenv()

    out_path = DRAFTS / f"{slugify(breed)}.md"
    if out_path.exists() and not force:
        raise FileExistsError(
            f"Draft already exists: {out_path} (use --force to overwrite)."
        )

    model = os.getenv("PAWS_MODEL", "claude-opus-4-8")
    effort = os.getenv("PAWS_EFFORT", "high")
    image_dir = os.getenv(
        "BREED_IMAGE_DIR",
        "/Volumes/SDextra4Mac/MyClaude/PawsKnowhow/dog_breed_images/instagram_4x5",
    )

    print(f"→ Fetching AKC source for {breed} …")
    source = fetch_breed_source(breed)
    if "error" in source:
        print(f"  warning: {source['error']}", file=sys.stderr)
        print("  continuing with breed name only.", file=sys.stderr)
    elif "warning" in source:
        print(f"  note: {source['warning']}", file=sys.stderr)

    print(f"→ Generating post with {model} (effort={effort}) …")
    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

    # Stream so large adaptive-thinking + output never hits an HTTP timeout.
    with client.messages.stream(
        model=model,
        max_tokens=16000,
        thinking={"type": "adaptive"},
        output_config={
            "effort": effort,
            "format": {"type": "json_schema", "schema": POST_SCHEMA},
        },
        system=_build_system_prompt(),
        messages=[{"role": "user", "content": _build_user_prompt(breed, source)}],
    ) as stream:
        message = stream.get_final_message()

    if message.stop_reason == "refusal":
        raise RuntimeError(f"Claude refused to generate content for {breed}.")

    raw = next((b.text for b in message.content if b.type == "text"), "")
    try:
        post = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Could not parse model output as JSON: {exc}\n{raw[:500]}")

    img = breed_image_path(breed, image_dir)
    metadata = {
        "breed": breed,
        "title": post["title"],
        "slug": slugify(breed),
        "meta_description": post["meta_description"],
        "tags": post["tags"],
        "source_url": source.get("source_url", ""),
        "image_path": str(img),
        "image_exists": img.exists(),
        "model": message.model,
        "generated_on": date.today().isoformat(),
        "human_approved": False,  # nothing publishes until a human flips this
        "approved": False,
    }

    dump_post(out_path, metadata, post["body_markdown"])
    print(f"✓ Draft written: {out_path}")
    if not img.exists():
        print(f"  warning: breed image not found at {img}", file=sys.stderr)
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a PawsKnowHow blog draft.")
    parser.add_argument("breed", help='Breed name, e.g. "Border Collie"')
    parser.add_argument(
        "--force", action="store_true", help="Overwrite an existing draft."
    )
    args = parser.parse_args()

    try:
        generate_post(args.breed, force=args.force)
    except (FileExistsError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    except anthropic.APIError as exc:
        print(f"Anthropic API error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
