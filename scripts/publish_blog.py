"""Publish approved PawsKnowHow drafts to Blogger — always as a draft post.

Usage:
    python scripts/publish_blog.py                 # publish all approved posts
    python scripts/publish_blog.py border-collie   # publish one by slug/filename
    python scripts/publish_blog.py --list          # show what's approved

Safety contract:
    - Reads ONLY from content/approved/. Drafts in content/drafts/ are ignored.
    - A post is published only if BOTH `approved: true` AND `human_approved: true`
      are present in its frontmatter.
    - Posts are created on Blogger with isDraft=True — they are NEVER auto-published
      live. A human still has to hit "Publish" in the Blogger dashboard.
    - After a successful upload, the file is moved to content/published/ with the
      Blogger post id + url recorded in its frontmatter.

Auth: OAuth 2.0 desktop flow. On first run a browser opens for consent; the token
is cached to GOOGLE_TOKEN_FILE for subsequent runs.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from html import escape
from pathlib import Path

from dotenv import load_dotenv

try:
    from _common import APPROVED, PUBLISHED, dump_post, load_post
except ImportError:  # pragma: no cover
    from scripts._common import APPROVED, PUBLISHED, dump_post, load_post

BLOGGER_SCOPE = "https://www.googleapis.com/auth/blogger"

# Style applied to the whole post body (wraps hero + content).
CONTENT_FONT = "Verdana, Geneva, Tahoma, sans-serif"
CONTENT_STYLE = f"font-family: {CONTENT_FONT}; font-size: 14px; line-height: 1.6;"


# --- Minimal Markdown -> HTML (no extra dependency) --------------------------

def markdown_to_html(md: str) -> str:
    """Convert the subset of Markdown our posts use into Blogger-ready HTML.

    Handles: ##/### headings, **bold**, *italic*, [text](url) links, `- ` bullet
    lists, and blank-line-separated paragraphs. Good enough for clean drafts;
    for richer formatting, `pip install markdown` and swap this out.
    """
    def inline(text: str) -> str:
        text = escape(text, quote=False)
        text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
        text = re.sub(r"(?<!\*)\*(?!\s)(.+?)(?<!\s)\*(?!\*)", r"<em>\1</em>", text)
        text = re.sub(r"\[(.+?)\]\((.+?)\)", r'<a href="\2">\1</a>', text)
        return text

    html: list[str] = []
    list_open = False
    for block in re.split(r"\n\s*\n", md.strip()):
        lines = block.splitlines()
        if all(line.lstrip().startswith(("- ", "* ")) for line in lines if line.strip()):
            html.append("<ul>")
            for line in lines:
                item = line.lstrip()[2:]
                html.append(f"  <li>{inline(item)}</li>")
            html.append("</ul>")
            continue
        m = re.match(r"^(#{1,6})\s+(.*)$", lines[0])
        if m:
            level = len(m.group(1))
            html.append(f"<h{level}>{inline(m.group(2))}</h{level}>")
            continue
        paragraph = " ".join(line.strip() for line in lines)
        html.append(f"<p>{inline(paragraph)}</p>")
    return "\n".join(html)


# --- Hero image --------------------------------------------------------------

def export_hero_image(breed: str, slug: str) -> Path | None:
    """Save a web-optimized JPEG of the breed image into IMAGE_OUTPUT_DIR.

    Resolves {BREED_IMAGE_DIR}/{breed}.png, downscales it and writes
    {IMAGE_OUTPUT_DIR}/{slug}.jpg. Returns the saved path, or None if the source
    image or Pillow is unavailable. This is the file you host publicly.
    """
    image_dir = os.getenv(
        "BREED_IMAGE_DIR",
        "/Volumes/SDextra4Mac/MyClaude/PawsKnowhow/dog_breed_images/instagram_4x5",
    )
    src = Path(image_dir) / f"{breed}.png"
    if not src.exists():
        print(f"  [WARN] hero image not found: {src}")
        return None

    try:
        from PIL import Image
    except ImportError:
        print("  [WARN] Pillow not installed — skipping hero image")
        return None

    out_dir = Path(os.getenv("IMAGE_OUTPUT_DIR", "content/images"))
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / f"{slug}.jpg"
    with Image.open(src) as im:
        im = im.convert("RGB")
        im.thumbnail((1200, 1200))  # cap longest edge; preserves aspect ratio
        im.save(dest, format="JPEG", quality=85, optimize=True)
    print(f"  [IMG] exported hero -> {dest}")
    return dest


def _hero_image_html(breed: str, slug: str) -> str:
    """Export the breed image locally and return an <img> for its PUBLIC URL.

    Blogger strips inline `data:` URIs and has no image-upload API, so the image
    must be served from a real URL. The file is written to IMAGE_OUTPUT_DIR and
    referenced as PUBLIC_IMAGE_BASE_URL/<slug>.jpg. Returns "" (and warns) if the
    image can't be exported or PUBLIC_IMAGE_BASE_URL is unset, so a missing host
    never blocks publishing.
    """
    dest = export_hero_image(breed, slug)
    if dest is None:
        return ""

    base = os.getenv("PUBLIC_IMAGE_BASE_URL", "").rstrip("/")
    if not base:
        print(
            f"  [WARN] PUBLIC_IMAGE_BASE_URL not set — saved {dest} but omitting the "
            f"<img>. Set it to the public URL serving {dest.parent}/ and re-run."
        )
        return ""

    url = f"{base}/{dest.name}"
    alt = escape(f"{breed} — PawsKnowHow breed guide", quote=True)
    return (
        '<figure style="margin:0 0 1.5em;text-align:center;">'
        f'<img src="{url}" alt="{alt}" '
        'style="max-width:100%;height:auto;border-radius:8px;" />'
        "</figure>\n"
    )


# --- Blogger client ----------------------------------------------------------

def _get_blogger_service():
    """Build an authenticated Blogger v3 service, running OAuth if needed."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from google_auth_oauthlib.flow import InstalledAppFlow
    from googleapiclient.discovery import build

    token_file = Path(os.getenv("GOOGLE_TOKEN_FILE", "token.json"))
    secrets_file = os.getenv("GOOGLE_CLIENT_SECRETS", "client_secret.json")

    creds = None
    if token_file.exists():
        creds = Credentials.from_authorized_user_file(str(token_file), [BLOGGER_SCOPE])

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not Path(secrets_file).exists():
                raise FileNotFoundError(
                    f"OAuth client secrets not found at '{secrets_file}'. Download "
                    "them from Google Cloud Console and set GOOGLE_CLIENT_SECRETS."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                secrets_file, [BLOGGER_SCOPE]
            )
            creds = flow.run_local_server(port=0)
        token_file.write_text(creds.to_json(), encoding="utf-8")

    return build("blogger", "v3", credentials=creds)


def _is_publishable(metadata: dict) -> tuple[bool, str]:
    if metadata.get("approved") is not True:
        return False, "approved is not true"
    if metadata.get("human_approved") is not True:
        return False, "human_approved is not true"
    return True, ""


def _ensure_draft(service, blog_id: str, post_id: str) -> str:
    """Guarantee a freshly-inserted post is a DRAFT; revert it if it went live.

    posts.insert(isDraft=True) should never publish live, but we verify rather
    than trust it. The source of truth is posts.list(status="LIVE") — a just-
    created post sorts newest-first, so it lands on page one if it is live.
    posts.get().status is deliberately NOT used: it reports "LIVE" for drafts.
    Returns the verified status to record in frontmatter.
    """
    live = (
        service.posts()
        .list(blogId=blog_id, status="LIVE", fetchBodies=False, maxResults=20)
        .execute()
    )
    live_ids = {p["id"] for p in live.get("items", [])}
    if post_id not in live_ids:
        return "DRAFT"

    # Should not happen with isDraft=True — force it back to draft.
    print(f"  [WARN] post {post_id} landed LIVE — reverting to draft")
    service.posts().revert(blogId=blog_id, postId=post_id).execute()
    return "DRAFT (reverted from live)"


def publish_file(path: Path, *, blog_id: str, service) -> dict:
    """Upload one approved markdown file to Blogger as a draft post."""
    metadata, body = load_post(path)

    ok, reason = _is_publishable(metadata)
    if not ok:
        raise PermissionError(f"{path.name} is not publishable: {reason}.")

    breed = metadata.get("breed", path.stem)
    inner = _hero_image_html(breed, path.stem) + markdown_to_html(body)
    html = f'<div style="{CONTENT_STYLE}">\n{inner}\n</div>'
    post_body = {
        "title": metadata.get("title", breed),
        "content": html,
        "labels": metadata.get("tags", []),
    }

    print(f"→ Uploading '{post_body['title']}' to Blogger as a draft …")
    created = (
        service.posts()
        .insert(blogId=blog_id, body=post_body, isDraft=True)
        .execute()
    )
    post_id = created.get("id", "")

    # Verify it is genuinely a draft (and revert if not) before recording.
    status = _ensure_draft(service, blog_id, post_id)

    # Record Blogger identifiers and move the file to content/published/.
    metadata["blogger_post_id"] = post_id
    metadata["blogger_url"] = created.get("url", "")
    metadata["blogger_status"] = status

    dest = PUBLISHED / path.name
    dump_post(dest, metadata, body)
    path.unlink()

    print(f"✓ Created Blogger draft (id={post_id}, status={status}).")
    print(f"  Moved {path.name} → content/published/")
    print("  NOTE: the post is a DRAFT on Blogger — publish it manually when ready.")
    return metadata


def _approved_files(selector: str | None) -> list[Path]:
    files = sorted(APPROVED.glob("*.md"))
    if selector:
        stem = selector.removesuffix(".md")
        files = [p for p in files if p.stem == stem]
    return files


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="Publish approved drafts to Blogger.")
    parser.add_argument(
        "selector",
        nargs="?",
        help="Slug/filename to publish (default: all approved).",
    )
    parser.add_argument(
        "--list", action="store_true", help="List approved posts and their status."
    )
    args = parser.parse_args()

    files = _approved_files(args.selector)

    if args.list:
        if not files:
            print("Nothing in content/approved/.")
            return 0
        for p in files:
            meta, _ = load_post(p)
            ok, reason = _is_publishable(meta)
            flag = "READY" if ok else f"BLOCKED ({reason})"
            print(f"  [{flag}] {p.stem} — {meta.get('title', '?')}")
        return 0

    if not files:
        print("No approved posts to publish.", file=sys.stderr)
        return 1

    blog_id = os.getenv("BLOGGER_BLOG_ID")
    if not blog_id:
        print("ERROR: set BLOGGER_BLOG_ID in your .env.", file=sys.stderr)
        return 1

    # Pre-filter so we don't run OAuth if nothing is actually publishable.
    publishable = [p for p in files if _is_publishable(load_post(p)[0])[0]]
    if not publishable:
        print("No files are both approved:true and human_approved:true.", file=sys.stderr)
        return 1

    service = _get_blogger_service()

    exit_code = 0
    for path in publishable:
        try:
            publish_file(path, blog_id=blog_id, service=service)
        except PermissionError as exc:
            print(f"SKIP: {exc}", file=sys.stderr)
        except Exception as exc:  # noqa: BLE001 — surface any API error per-file
            print(f"ERROR publishing {path.name}: {exc}", file=sys.stderr)
            exit_code = 1
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
