# Empirical OSINT: viral carousels (IG / TikTok Photo Mode / LinkedIn PDF)

**Date:** 2026-09-10  
**Method:** GitHub code inspection (not README marketing), Hugging Face / Kaggle schema checks, arXiv / JM primary papers. Agency blogs and SEO tips ignored.  
**Skeptic verdict (headline):** There is **no public, transparent dataset** that jointly contains `slide_count` + per-slide `word_count` / text-area ratio + Instagram **saves** for N≥500 viral carousels. What exists are (a) **engineering scrapers** that *can* build such a sample, (b) **synthetic “analytics” CSVs** that look complete but fail authenticity checks, and (c) **adjacent science** (text overlays on *single* images; video virality).

---

## 1. Source table (primary only)

| Link | Sample size | What was actually studied / built | Engineering takeaway | Verdict |
|------|-------------|-------------------------------------|----------------------|---------|
| [Q-Bukold/TikTok-Content-Scraper](https://github.com/Q-Bukold/TikTok-Content-Scraper) | Tool (used in research at “millions of profiles/videos” scale per CITATION; no bundled CSV) | Parses `__UNIVERSAL_DATA_FOR_REHYDRATION__` → `itemStruct`; downloads **slides as JPEG+MP3** vs MP4; SQLite progress DB | Real fields: `diggcount`, `sharecount`, `commentcount`, `playcount`, **`collectcount` (saves)**, `repostcount`; flag `file_metadata.is_slide`; binaries from `imagePost.images[].imageURL.urlList` | **ACCEPT** — production research scraper for Photo Mode |
| [AlbertoQuian/instagram-tiktok-scraper](https://github.com/AlbertoQuian/instagram-tiktok-scraper) | Tool (JOSS-style `paper.md`; no fixed public N) | Playwright IG (intercept `web_profile_info` / GraphQL) + yt-dlp TikTok; unified CSV; **ffmpeg** rebuilds photo carousels → MP4 slideshow | CSV columns include `likes`, `comments`, `views`, `shares`, **`format`** (`image`/`video`/`carousel`); notes like `carousel_reconstructed (N slides)`; IG pad **1080×1080**, TT pad **1080×1920** | **ACCEPT** — best open academic pipeline for carousel-aware collection |
| [mikf/gallery-dl](https://github.com/mikf/gallery-dl) `gallery_dl/extractor/tiktok.py` | Tool | Stable Photo Mode extractor: `post_type = "image" if "imagePost" in post`; per-slide `width`/`height`/`num` | Schema ground truth for TT photo posts; filter `-o photos` | **ACCEPT** — reference parser |
| [instaloader/instaloader](https://github.com/instaloader/instaloader) `structures.py` | Tool | `GraphSidecar` / `PostSidecarNode`; `mediacount`; likes/comments on post | Public IG sidecar → **slide_count = mediacount**; **no public saves** | **ACCEPT** — IG carousel structure |
| [Slashgear/linkedin-carousel-gen](https://github.com/Slashgear/linkedin-carousel-gen) | Generator (no engagement data) | React → **Satori** SVG → **@resvg/resvg-js** PNG → **pdf-lib** PDF | Hardcoded `SLIDE_WIDTH = SLIDE_HEIGHT = 1080` | **ACCEPT** — LinkedIn PDF factory stack |
| [ludusrusso/mkcr](https://github.com/ludusrusso/mkcr) | Generator | Go CLI: HTML+Tailwind slides → PNG/PDF; agent-oriented | Presets `square` 1080×1080, `vertical` 1080×1350; slides as `1.html`…`N.html` | **ACCEPT** — agent-friendly carousel render |
| [roslove44/brand-artisan](https://github.com/roslove44/brand-artisan) | Generator | Satori + resvg + pdf-lib (same family as Slashgear) | Confirms industry default stack for OG/social/carousels | **ACCEPT** — architecture reference |
| [Farace et al., JM 2026](https://doi.org/10.1177/00222429251322773) (text overlays) | Twitter field: TO subsample N≈615; Instagram Study 5: **8,467** single-image posts (from 11,268 scraped) | **Text overlay size × centrality × image dynamism → engagement** (likes+comments on IG; retweets on X). **Not carousels.** | Empirically: for **dynamic** images, TO size inverted-U; engagement weakens when TO **> ~24%** of image area; below baseline of no-TO when **> ~46%**. Static images: size effect weak/ns in Study 1. Practitioners’ ≤**20%** (Facebook/HubSpot) cited as prior. | **ACCEPT** — only peer-reviewed text-area constants found |
| [karansikka1/documentIntent_emnlp19](https://github.com/karansikka1/documentIntent_emnlp19) (MDID) | Multimodal intent labels + likes; images withheld (ResNet-18 feats) | Document intent / semiotic / contextual labels on IG posts | Multimodal taxonomy useful for caption–image intent; **not** slide/save analysis | **ACCEPT (adjacent)** |
| [Harvard Dataverse: Big Four Fashion Weeks](https://doi.org/10.7910/DVN/8BNXES) | **905,726** posts + 171k profiles | Event hashtags, likes, comments, caption length, brand dummies | Large **real** scrape; **no** media_type/carousel/saves | **ACCEPT (adjacent)** — scale reference only |
| [vargr/main_instagram](https://huggingface.co/datasets/vargr/main_instagram) | **605,868** rows | Real-looking `shortcode`, likes, comments, `post_type` (int), caption, followers | Likely scraped; **no saves / no slide_count / opaque post_type mapping** | **ACCEPT with caveats** — use for likes/comments baselines only |
| [juanls1/TikTok-Virality-Predictor](https://github.com/juanls1/TikTok-Virality-Predictor) | Kaggle trending Dec 2020 videos + notebooks | Multimodal **video** virality (views/likes/comments/shares weighted formula) | Useful ML pattern; **not Photo Mode** | **REJECT for carousel factory** (keep as video baseline) |
| [harbarex/tiktok-virality-prediction](https://github.com/harbarex/tiktok-virality-prediction) | `label.csv` **N=1000** trending labels + ViViT | Video viral classification | N≥500 but video-only | **REJECT for carousel** |
| [maayan890/instagram-engagement-eda](https://huggingface.co/datasets/maayan890/instagram-engagement-eda) / Kaggle twin (~30k) | Claims 29,999 with saves/shares/reach + `media_type=carousel` | Student EDA notebook + CSV | IDs `IG0000001…`; caption_length massed at 117–122; looks **synthetic** | **REJECT** — fails authenticity |
| [Dhela456/Instagram-Analytics-EDA-ML](https://github.com/Dhela456/Instagram-Analytics-EDA-ML) | Same family CSV + XGBoost Streamlit | Claims Reels > Carousel > Photo engagement | Same synthetic schema as above | **REJECT** |
| [jason1966/…viral-content…](https://huggingface.co/datasets/jason1966/aliiihussain_social-media-viral-content-and-engagement-metrics) | Large; `content_type=carousel` | Synthetic `SM_*` IDs, no methodology | Marketing-grade fake panel | **REJECT** |
| [luminati-io/Instagram-Posts-dataset-samples](https://github.com/luminati-io/Instagram-Posts-dataset-samples) | 7,730 sample | Real Bright Data extract; has `content_type` incl. carousel | README is lead-gen for paid full dump; sample OK for schema peek only | **WEAK** — schema only, not open full science |

---

## 2. What parsers actually extract (field inventory)

### 2.1 TikTok Photo Mode (from Q-Bukold + gallery-dl)

| Domain | Fields in code |
|--------|----------------|
| Identity | `id`, `author_id`, `username` (`uniqueId`), `time_created` |
| Text | `description` / `desc`, hashtags, mentions, `text_language` |
| Engagement | `diggcount`, `commentcount`, `sharecount`, `playcount`, **`collectcount`**, `repostcount` (prefer `statsV2`) |
| Media type | Presence of `imagePost` → slide; else `video`; Q-Bukold sets `is_slide` when JPEGs downloaded |
| Slides | `imagePost.images[]` → `imageURL.urlList`, `imageWidth`, `imageHeight`; count = `len(images)` |
| Audio | `music.playUrl`, title, author |
| Flags | `isAd`, `IsAigc` / `AIGCDescription`, stickers, duet/stitch |

**Critical for the factory:** TikTok **exposes saves publicly** as `collectCount`. Instagram does **not** on public surfaces.

### 2.2 Instagram carousel (from AlbertoQuian + instaloader)

| Domain | Fields |
|--------|--------|
| Identity | `post_id`, `post_url`, shortcode |
| Text | `caption`, hashtags, `language` (lingua-py in AlbertoQuian) |
| Engagement | `likes`, `comments`, `views` (when present), `shares` (platform-dependent), `likes_hidden` |
| Format | `format ∈ {image, video, carousel}` via `carousel_media` or `edge_sidecar_to_children` |
| Slides | Child edges / `carousel_media` list; reconstruct notes store **slide count**; instaloader `mediacount` |
| Not available publicly | **saves**, reach, impressions, Insights traffic source |

Unified export schema (AlbertoQuian `utils/export.py`):

```text
category, account_name, account_id, platform, post_id, post_url, date,
caption, hashtags, likes, likes_hidden, comments, views, shares, fb_likes,
format, duration, music_title, music_author, media_files, thumbnail,
metadata_file, language, notes
```

### 2.3 LinkedIn PDF carousel (generators, not scrapers)

Render constants from open code:

- Slashgear: **1080×1080**, Satori → Resvg → pdf-lib  
- mkcr: **1080×1080** square / **1080×1350** vertical  

No open engagement datasets for LinkedIn document carousels found under the skeptic filter.

---

## 3. Mathematical / design constants from *primary* evidence

| Constant | Value | Source type | Notes |
|----------|-------|-------------|-------|
| Text overlay area (dynamic image) — soft ceiling | **~24%** of image | Farace et al. JM (field, X; TO×dynamism) | Beyond this, marginal engagement declines vs smaller TO |
| Text overlay area — hard failure vs no-TO | **~46%** of image | Same | Engagement drops below dynamic image **without** TO |
| Practitioner prior (Facebook) | **≤20%** text | Cited in Farace intro (HubSpot/FB guidance) | Not an IG carousel RCT; use as conservative band |
| LinkedIn slide canvas | **1080×1080** (or 1080×1350) | Slashgear / mkcr source | Engineering default, not engagement optimum |
| IG slideshow rebuild pad | **1080×1080** | AlbertoQuian ffmpeg `-vf scale=…pad=1080:1080` | Matches feed square |
| TT Photo Mode rebuild pad | **1080×1920** | AlbertoQuian TikTok ffmpeg | Vertical phone frame |
| Scrape pacing (TikTok) | **wait_time ≈ 0.35 s** default | Q-Bukold | Rate-limit hygiene, not virality |
| Optimal **slide count** | **Not established in open data** | — | No accepted N≥500 study with transparent methodology linking slide_count → saves/completion. Do **not** treat marketing “7–10 slides” as empirical. |
| Optimal **words per slide** | **Not established in open data** | — | Public scrapes store caption length only; per-slide OCR word counts are almost never released. |
| Instagram public saves | **Unavailable** | API/scraper reality | Any CSV with `saves` + public `post_id` without Insights auth is suspect |

**Implication for `formulas.json`:** keep Farace-aligned text/image band (~11–24% soft, collapse ~44–46%) as the only peer-reviewed constant; treat slide/word bands as **hypotheses to validate on your own Insights / collectCount scrapes**, not as literature facts.

---

## 4. Statistical patterns from accepted corpora (limited)

| Corpus | What you can honestly report |
|--------|------------------------------|
| Farace Study 5 (IG, N=8,467 **single** images) | Engagement = likes + comments; TO size/centrality + dynamism matter; human presence often negative IRR in models; **carousel slides not in sample** |
| vargr HF (~606k) | Large likes/comments distribution possible after cleaning; `post_type` needs reverse-mapping before carousel analysis |
| Fashion Weeks Dataverse (905k) | Event-driven volume; caption_length / hashtags_count available; no format split |
| Synthetic IG analytics (~30k) | **Do not use** for medians/quartiles — caption length and IDs are generated |

**No trustworthy open quartile table** for “top engagement carousels by slide_count” was found.

---

## 5. Architecture patterns to copy into the Carousel Factory

### 5.1 Collection (Photo Mode + IG sidecar)

```text
TikTok:
  GET page HTML → BeautifulSoup #__UNIVERSAL_DATA_FOR_REHYDRATION__
  → itemStruct → _filter statsV2 + imagePost
  → download JPEGs + music.playUrl MP3
  → derive slide_count = len(imagePost.images)
  → target metric = collectcount / playcount

Instagram:
  Playwright intercept web_profile_info / GraphQL
  → if carousel_media or edge_sidecar_to_children → format=carousel
  → slide_count = len(children)
  → public targets = likes, comments (, shares if present)
  → saves only via authenticated Insights / Meta Content Library
```

### 5.2 Rebuild slideshow (analysis / training on motion proxies)

From AlbertoQuian (IG):

```python
# Pseudocode aligned with scrapers/instagram_playwright.py
image_files = [f for f in media_files if f.lower().endswith((".jpg", ".jpeg", ".png", ".webp"))]
# ffmpeg: concat demuxer + scale/pad 1080x1080 → {post_id}_slideshow.mp4
# notes = f"carousel_reconstructed ({len(image_files)} slides)"
```

TikTok variant: Playwright reads `imagePost.images`, yt-dlp pulls audio, ffmpeg pads **1080×1920**.

### 5.3 LinkedIn PDF generation

```text
Slide React/HTML (1080²)
  → Satori (SVG)
  → @resvg/resvg-js (PNG)
  → pdf-lib (one page per slide)
# Alternative: mkcr HTML+Tailwind → headless PNG/PDF
```

### 5.4 Recommended factory schema (implement this; don’t invent saves)

```python
from pydantic import BaseModel, Field
from typing import Literal, Optional

class CarouselSlideRecord(BaseModel):
    slide_index: int = Field(ge=1)
    width: Optional[int] = None
    height: Optional[int] = None
    word_count_ocr: Optional[int] = None   # fill via OCR/Vision; scrapers rarely have it
    text_area_pct: Optional[float] = None  # Farace-style: % of frame covered by text
    has_face: Optional[bool] = None

class CarouselPostRecord(BaseModel):
    platform: Literal["instagram", "tiktok", "linkedin"]
    post_id: str
    post_url: str
    format: Literal["carousel", "image", "video", "photo_mode"]
    slide_count: int
    caption: str = ""
    caption_word_count: int = 0
    likes: Optional[int] = None
    comments: Optional[int] = None
    shares: Optional[int] = None
    views_or_plays: Optional[int] = None
    saves_or_collects: Optional[int] = None  # TT: collectCount; IG: Insights-only
    save_rate: Optional[float] = None        # saves / impressions_or_plays
    slides: list[CarouselSlideRecord] = []
    source: str = ""  # scraper id + commit hash
    methodology_note: str = ""
```

### 5.5 Minimal EDA targets once you own N≥500

```python
# After scraping with Q-Bukold / AlbertoQuian + your OCR:
# 1) filter format in {carousel, photo_mode}, slide_count >= 2
# 2) engagement = saves_or_collects / max(views_or_plays, 1)   # TT
#    or Insights save_rate                                        # IG owned accounts
# 3) report median/IQR of slide_count, caption_word_count, text_area_pct
#    for top decile vs bottom decile — do not import synthetic CSVs
```

---

## 6. How open-source authors automate assembly (stack map)

| Layer | Tools observed in accepted repos |
|-------|----------------------------------|
| Browser / HTML | Playwright, requests + BeautifulSoup, browser_cookie3 |
| Media download | yt-dlp (TT), direct CDN GETs for JPEG/MP3/MP4 |
| Progress / storage | SQLite object tracker (Q-Bukold), JSON metadata + CSV (Pandas) |
| Slideshow rebuild | **ffmpeg** (+ ffprobe for duration) |
| LinkedIn PDF | **Satori**, **@resvg/resvg-js**, **pdf-lib**; or HTML+Tailwind (mkcr) |
| Optional vision | Google Cloud Vision (Farace Study 5 TO detection / faces) — methodology only; data not openly mirrored |

---

## 7. Explicit gaps (so the factory does not lie to itself)

1. **No open “viral carousel” gold set** with slide_count × text metrics × saves.  
2. **Instagram saves** require account Insights or restricted Meta research access — public scrapers cannot honestly fill that column.  
3. **Virality GitHub projects** with notebooks are overwhelmingly **TikTok video**, not Photo Mode.  
4. **HF/Kaggle “Instagram Analytics” with saves** repeatedly fail synthetic-data checks (sequential fake IDs, unnatural caption_length histograms).  
5. Farace constants apply to **single-image text overlays**, not multi-slide listicles — transfer carefully.

---

## 8. Actionable next steps for this repo (`farm`)

1. Wire collectors: Q-Bukold (TT photo + `collectcount`) and/or AlbertoQuian (IG `format=carousel` + slide_count).  
2. Add OCR / text-mask step → `text_area_pct`, `word_count_ocr` per slide (Farace-compatible).  
3. Validate `formulas.json` bands only against **your** scrape + owned Insights — mark marketing-derived slide/word ranges as `hypothesis`.  
4. LinkedIn path: adopt Slashgear/mkcr render dimensions (1080² / 1080×1350) without pretending engagement optima exist in open data.

---

*Temp search helpers used during this pass (`_gh_search.py`, `_gh_inspect.py`, `_gh_deep.py`, `_gh_schema.py`) may be deleted; this file is the durable artifact.*
