"""One-time Google OAuth login for Blogger publishing.

Runs the OAuth 2.0 desktop consent flow and caches the result to GOOGLE_TOKEN_FILE
(default token.json) so publish_blog.py can run unattended afterwards. A browser
opens for consent on first run; nothing is published.

Usage (from the pawsknowhow-automation/ directory):
    python scripts/login.py
"""
from __future__ import annotations

import sys
from pathlib import Path

from dotenv import load_dotenv

# Make sibling modules importable whether run as `python scripts/login.py`
# or `python -m scripts.login`.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from publish_blog import _get_blogger_service, BLOGGER_SCOPE  # noqa: E402


def main() -> int:
    # Loads GOOGLE_CLIENT_SECRETS / GOOGLE_TOKEN_FILE (relative to CWD) from .env.
    load_dotenv()
    import os

    token_file = os.getenv("GOOGLE_TOKEN_FILE", "token.json")
    print(f"Scope: {BLOGGER_SCOPE}")
    print("Opening browser for Google consent… (nothing will be published)")
    _get_blogger_service()  # runs the flow and writes the token on success
    print(f"✅ OAuth complete — token cached to {token_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
