# PawsKnowHow — Blog & Instagram Content Automation

Generates publish-ready blog drafts for the **PawsKnowHow** pet-education brand,
one dog breed at a time, and pushes approved posts to **Blogger as drafts**.

The pipeline is deliberately split into three reviewable stages so that
**nothing ever goes live without a human in the loop**:

```
fetch_source.py   →   generate_blog.py   →   (human review)   →   publish_blog.py
  (AKC scrape)         drafts/*.md             approved/*.md         Blogger draft
```

Content generation uses the **Anthropic Python SDK** (`claude-opus-4-8`).
Publishing uses the **Blogger API v3** via `google-api-python-client`.

---

## Project layout

```
pawsknowhow-automation/
├── .env                      # secrets + config (do NOT commit when filled in)
├── requirements.txt
├── scripts/
│   ├── _common.py            # shared paths + frontmatter I/O
│   ├── fetch_source.py       # fetch breed facts from akc.org
│   ├── generate_blog.py      # breed → Claude → content/drafts/<slug>.md
│   └── publish_blog.py       # content/approved/ → Blogger (as draft)
├── content/
│   ├── drafts/               # machine-generated, approved:false
│   ├── approved/             # human-reviewed, ready to publish
│   └── published/            # uploaded to Blogger (draft on their side)
└── templates/
    └── brand_style.md        # voice/spelling/safety rules → system prompt
```

---

## Setup

### 1. Install dependencies

```bash
cd pawsknowhow-automation
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure secrets

Edit `.env` (keys are pre-stubbed):

| Variable | What it is |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key (used by the SDK automatically). |
| `PAWS_MODEL` | Model id — defaults to `claude-opus-4-8`. |
| `PAWS_EFFORT` | Thinking/effort level: `low`/`medium`/`high`/`max` (default `high`). |
| `BLOGGER_BLOG_ID` | Numeric Blogger blog id. |
| `GOOGLE_CLIENT_SECRETS` | Path to your OAuth client-secrets JSON. |
| `GOOGLE_TOKEN_FILE` | Where the cached OAuth token is written (default `token.json`). |
| `BREED_IMAGE_DIR` | Folder of `{Breed Name}.png` 4×5 images. |

### 3. Set up Blogger API access (one-time)

1. In [Google Cloud Console](https://console.cloud.google.com/): create a project,
   enable the **Blogger API v3**.
2. **APIs & Services → Credentials → Create Credentials → OAuth client ID →
   Desktop app**. Download the JSON and point `GOOGLE_CLIENT_SECRETS` at it.
3. First run of `publish_blog.py` opens a browser for consent and caches the
   token to `GOOGLE_TOKEN_FILE`.

---

## Usage

### Fetch source data (optional — generate does this for you)

```bash
python scripts/fetch_source.py "Border Collie"
python scripts/fetch_source.py "Border Collie" --json
```

### Generate a draft

```bash
python scripts/generate_blog.py "Border Collie"
python scripts/generate_blog.py "Border Collie" --force   # overwrite existing draft
```

Writes `content/drafts/border-collie.md` with YAML frontmatter and
`approved: false` / `human_approved: false`.

### Review & approve (human step)

1. Read the draft in `content/drafts/`.
2. Edit as needed, then **move it** to `content/approved/`.
3. Set **both** flags in the frontmatter:

   ```yaml
   approved: true
   human_approved: true
   ```

`publish_blog.py` refuses to touch anything missing either flag.

### Publish to Blogger (as a draft)

```bash
python scripts/publish_blog.py --list          # show what's ready/blocked
python scripts/publish_blog.py border-collie   # publish one
python scripts/publish_blog.py                 # publish everything approved
```

Each post is created on Blogger with **`isDraft=True`** — it appears in your
Blogger dashboard as a draft. You still click **Publish** there yourself.
On success the file moves to `content/published/` with the Blogger post id/url
recorded.

---

## Draft frontmatter reference

```yaml
breed: Border Collie
title: "..."
slug: border-collie
meta_description: "..."          # <=155 chars, British English
tags: [border collie, herding, ...]
source_url: https://www.akc.org/dog-breeds/border-collie/
image_path: /…/instagram_4x5/Border Collie.png
image_exists: true
model: claude-opus-4-8
generated_on: 2026-06-07
human_approved: false           # ← flip to true after review
approved: false                 # ← flip to true after review
```

---

## Safety guarantees

- **No surprise publishing.** `publish_blog.py` reads only `content/approved/`,
  requires `approved: true` **and** `human_approved: true`, and creates Blogger
  posts as drafts only.
- **Brand voice enforced.** `templates/brand_style.md` is injected into every
  generation: British spelling, hedged health claims, positive framing,
  "pet parent"/"owner" (never "master").
- **Graceful scraping.** If the AKC page can't be fetched or parsed, generation
  continues on the breed name + general knowledge and warns you.

---

## Notes

- Markdown → HTML in `publish_blog.py` covers headings, bold/italic, links, and
  bullet lists. For richer formatting, `pip install markdown` and swap the
  `markdown_to_html` helper.
- AKC markup changes periodically; if `traits` come back empty, the parser
  selectors in `fetch_source.py` may need a refresh.
