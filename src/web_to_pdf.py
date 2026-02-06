"""
Web scraping and PDF conversion for O-1 Research Assistant.

This module fetches webpages and converts them to clean PDFs.

Updates (Opera Today-style):
- Two profiles: "opera_today" (tight margins/print look) and "annotate" (wide margins for annotation).
- Grey divider line after title.
- Tight spacing between title/divider/url and larger gap before body.
- Slightly lighter gray body text vs black title.
- Author credit rendered at the END (bold + italic).
- "www" icon used instead of "URL:" (embedded as base64 if local png is available).
- Key images extracted from article container only (filtered to avoid ads/related/logo/etc).
- Optional star rating (only if detected in the article header scope).
"""

import io
import re
import base64
from dataclasses import dataclass
from datetime import datetime
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse, urljoin

# ---- Optional dependencies (handled gracefully) ----
# requests, bs4, newspaper3k, pillow, weasyprint
# reportlab fallback remains for environments without weasyprint.


# -----------------------------
# Data container
# -----------------------------
@dataclass
class WebpageData:
    title: str = "Untitled"
    author: str = ""
    date: str = ""
    content: str = ""
    url: str = ""
    raw_html: str = ""
    images: List[str] = None  # list of absolute image URLs (filtered)
    rating: Optional[int] = None  # 1-5 stars (only if clearly related)


# -----------------------------
# Public API
# -----------------------------
def fetch_webpage_content(url: str) -> Dict[str, str]:
    """
    Backward-compatible wrapper returning dict.
    Uses robust extraction and returns:
      title, author, date, content, url, raw_html, images, rating
    """
    data = _fetch_webpage_content_structured(url)
    return {
        "title": data.title,
        "author": data.author,
        "date": data.date,
        "content": data.content,
        "url": data.url,
        "raw_html": data.raw_html,
        "images": data.images or [],
        "rating": data.rating,
    }


def convert_webpage_to_pdf_with_margins(
    webpage_data: Dict[str, str],
    left_margin_mm: float = 30,
    right_margin_mm: float = 30,
    top_margin_mm: float = 30,
    bottom_margin_mm: float = 30,
    *,
    profile: str = "annotate",          # "annotate" or "opera_today"
    include_images: bool = True,
    include_rating: bool = True,
    www_icon_path: Optional[str] = "/mnt/data/37eb9cc1-ba05-45c8-b018-2ee11bb94813.png",
    max_images: int = 3,
) -> bytes:
    """
    Convert webpage content to PDF.

    Profiles:
      - "opera_today": tight margins, print-like look (matches Opera Today.pdf more closely)
      - "annotate": wider margins for annotation

    If profile is "opera_today", margins are overridden unless you pass your own margins and set profile="custom".
    """
    try:
        from weasyprint import HTML
        from weasyprint.text.fonts import FontConfiguration
    except ImportError:
        # Fallback: reportlab (no images/rating/footer fidelity)
        return _convert_with_reportlab(
            webpage_data,
            left_margin_mm,
            right_margin_mm,
            top_margin_mm,
            bottom_margin_mm
        )

    # Apply profile defaults (your earlier issue #5: header too low is mostly top margin)
    if profile == "opera_today":
        left_margin_mm = right_margin_mm = 10
        top_margin_mm = 10
        bottom_margin_mm = 10
    elif profile == "annotate":
        # Keep your existing wide margins as default
        # (you can still override via parameters)
        pass
    elif profile != "custom":
        raise ValueError("profile must be one of: 'opera_today', 'annotate', 'custom'")

    title = (webpage_data.get("title") or "Untitled").strip()
    author = (webpage_data.get("author") or "").strip()
    date = (webpage_data.get("date") or "").strip()
    url = (webpage_data.get("url") or "").strip()
    content = (webpage_data.get("content") or "").strip()
    images = webpage_data.get("images") or []
    rating = webpage_data.get("rating")

    # Timestamp like browser print footer
    timestamp = datetime.now().strftime("%m/%d/%Y, %H:%M")

    display_url = _shorten_url_for_display(url)

    # www icon: embed as base64 data URI if file exists; otherwise fallback to emoji globe
    www_icon_data_uri = _try_load_png_as_data_uri(www_icon_path)

    # Prepare lead images (download + filter by actual dimensions)
    embedded_images_html = ""
    if include_images and images:
        embedded_images_html = _build_lead_images_html(
            images=images,
            max_images=max_images
        )

    # Prepare rating HTML (only if clearly present for this article)
    rating_html = ""
    if include_rating and isinstance(rating, int) and 1 <= rating <= 5:
        rating_html = _render_star_rating_html(rating)

    # Author credit should appear at the bottom (bold + italic)
    author_credit_html = f'<div class="author-credit">{_escape_html(author)}</div>' if author else ""

    # Footer: two-line (timestamp + title) then (url + page x/y)
    # WeasyPrint supports counters in margin boxes.
    footer_left = (
        f"{timestamp}  {_truncate(title, 60)}"
        "\\A"
        f"{display_url}  "  # second line
    )

    # If you want the page X/Y on the second line at right, we can keep bottom-right.
    # Opera Today.pdf shows URL + page count together; so we do that.
    html_template = f"""
    <!DOCTYPE html>
    <html>
      <head>
        <meta charset="UTF-8">
        <style>
          @page {{
            size: letter;
            margin: {top_margin_mm}mm {right_margin_mm}mm {bottom_margin_mm}mm {left_margin_mm}mm;

            /* No top header (Opera Today look) */

            @bottom-left {{
              content: "{footer_left}";
              font-family: 'Times New Roman', Times, serif;
              font-size: 8pt;
              color: #000;
              white-space: pre; /* to respect \\A line break */
            }}
            @bottom-right {{
              content: counter(page) "/" counter(pages);
              font-family: 'Times New Roman', Times, serif;
              font-size: 8pt;
              color: #000;
            }}
          }}

          body {{
            font-family: Georgia, 'Times New Roman', Times, serif;
            font-size: 11pt;
            line-height: 1.35;         /* tighter (your item #3) */
            color: #2f2f2f;            /* slightly lighter than black (your item #4) */
            text-align: left;
            hyphens: none;
            margin: 0;
            padding: 0;
            font-weight: 400;
          }}

          h1 {{
            font-size: 18pt;
            font-weight: 700;
            margin: 0 0 3pt 0;         /* tight title spacing */
            padding: 0;
            color: #000;
            line-height: 1.2;
          }}

          /* Optional rating line near title */
          .rating {{
            margin: 0 0 2pt 0;
            font-size: 11pt;
            color: #000;
          }}

          /* Grey divider line after header (your item #1) */
          .divider {{
            border-bottom: 0.5pt solid #cfcfcf;
            margin: 2pt 0 3pt 0;       /* close like Opera Today */
          }}

          /* URL display with www icon (your item #6) */
          .url-display {{
            font-size: 9pt;
            color: #333;              /* Opera Today looks plain/dark, not link-blue */
            margin: 0 0 18pt 0;       /* bigger gap before body (your item #3) */
            text-decoration: none;
            word-wrap: break-word;
          }}

          .url-display::before {{
            content: "";
            display: inline-block;
            width: 11pt;
            height: 11pt;
            margin-right: 4pt;
            vertical-align: -1pt;
            {f'background: url("{www_icon_data_uri}") no-repeat center / contain;' if www_icon_data_uri else ''}
          }}

          /* If no icon could be loaded, fall back to emoji via an extra span */
          .url-emoji {{
            display: inline;
          }}

          /* Lead images */
          .lead-images {{
            margin: 0 0 10pt 0;
          }}
          .lead-images img {{
            max-width: 100%;
            height: auto;
            display: block;
            margin: 10pt auto;
          }}

          /* Paragraph spacing */
          p {{
            margin: 0 0 10pt 0;
            padding: 0;
            orphans: 2;
            widows: 2;
          }}

          /* Author at bottom (your item #2) */
          .author-credit {{
            margin-top: 14pt;
            font-size: 10pt;
            font-weight: 700;
            font-style: italic;
            color: #000;
          }}
        </style>
      </head>
      <body>
        <h1>{_escape_html(title)}</h1>
        {rating_html}

        <div class="divider"></div>

        <div class="url-display">
          {"<span class='url-emoji'>🌐 </span>" if not www_icon_data_uri else ""}
          {_escape_html(display_url)}
        </div>

        {f"<div class='lead-images'>{embedded_images_html}</div>" if embedded_images_html else ""}

        <div class="content">
          {_format_content_to_html(content)}
          {author_credit_html}
        </div>
      </body>
    </html>
    """

    font_config = FontConfiguration()
    html = HTML(string=html_template, base_url=url or None)
    pdf_bytes = html.write_pdf(font_config=font_config)
    return pdf_bytes


def batch_convert_urls_to_pdfs(
    urls_by_criterion: Dict[str, list],
    progress_callback=None,
    *,
    profile: str = "annotate",
    include_images: bool = True,
    include_rating: bool = True,
) -> Dict[str, Dict[str, bytes]]:
    """
    Convert multiple approved URLs to PDFs, organized by criterion.

    profile:
      - "annotate" (wide margins)
      - "opera_today" (tight print look)
    """
    result: Dict[str, Dict[str, bytes]] = {}
    total_urls = sum(len(urls) for urls in urls_by_criterion.values())
    processed = 0

    for criterion_id, urls in urls_by_criterion.items():
        result[criterion_id] = {}

        for url_data in urls:
            url = url_data.get("url")
            title = url_data.get("title", "Untitled")

            try:
                if progress_callback:
                    progress_callback(processed, total_urls, f"Fetching: {title}")

                webpage_data = fetch_webpage_content(url)

                if progress_callback:
                    progress_callback(processed, total_urls, f"Converting: {title}")

                pdf_bytes = convert_webpage_to_pdf_with_margins(
                    webpage_data,
                    # keep margins (overridden by profile unless profile="custom")
                    left_margin_mm=30,
                    right_margin_mm=30,
                    top_margin_mm=30,
                    bottom_margin_mm=30,
                    profile=profile,
                    include_images=include_images,
                    include_rating=include_rating,
                )

                safe_title = "".join(c for c in title if c.isalnum() or c in (" ", "-", "_"))[:50]
                filename = f"{safe_title}.pdf"

                result[criterion_id][filename] = pdf_bytes
                processed += 1

            except Exception as e:
                if progress_callback:
                    progress_callback(processed, total_urls, f"Error: {title} - {str(e)}")
                processed += 1
                continue

    return result


# -----------------------------
# Structured fetch implementation
# -----------------------------
def _fetch_webpage_content_structured(url: str) -> WebpageData:
    # Try newspaper3k first
    try:
        from newspaper import Article

        article = Article(url)
        article.download()
        article.parse()

        images = []
        if getattr(article, "top_image", None):
            images.append(article.top_image)
        # article.images is a set
        if getattr(article, "images", None):
            for img in list(article.images):
                if img and img not in images:
                    images.append(img)

        return WebpageData(
            title=article.title or "Untitled",
            author=", ".join(article.authors) if article.authors else "",
            date=article.publish_date.strftime("%B %d, %Y") if article.publish_date else "",
            content=article.text or "",
            url=url,
            raw_html=article.html or "",
            images=_dedupe_preserve_order([_safe_abs_url(url, i) for i in images if i]),
            rating=None,  # newspaper3k doesn’t reliably extract this
        )

    except Exception as e:
        print(f"[newspaper3k failed] {e}, trying BeautifulSoup...")

    # BeautifulSoup fallback with aggressive cleaning + targeted image/rating extraction
    try:
        import requests
        from bs4 import BeautifulSoup

        response = requests.get(
            url,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (compatible; O1VisaBot/1.0)"},
        )
        response.raise_for_status()
        soup = BeautifulSoup(response.content, "html.parser")

        # Title
        title_tag = soup.find("h1") or soup.find("title")
        title = title_tag.get_text(strip=True) if title_tag else "Untitled"

        # Remove obvious junk tags
        for tag in soup(["script", "style", "nav", "footer", "aside", "iframe"]):
            tag.decompose()

        # Remove common junk classes/ids
        junk_patterns = re.compile(r"(nav|menu|breadcrumb|share|social|comment|related|promo|advert|ad-|ads|banner|cookie)", re.I)
        for t in soup.find_all(True):
            cls = " ".join(t.get("class", []))
            tid = t.get("id", "")
            if junk_patterns.search(cls) or junk_patterns.search(tid):
                # don't delete the whole tree too aggressively; only remove big containers
                if t.name in ("div", "section", "aside", "header"):
                    t.decompose()

        # Main content heuristic
        main_content = (
            soup.find("article")
            or soup.find("main")
            or soup.find("div", class_=["content", "article", "post", "entry-content"])
            or soup.find("body")
        )

        author = _extract_author_from_soup(main_content) or _extract_author_from_soup(soup) or ""
        date = _extract_date_from_soup(main_content) or _extract_date_from_soup(soup) or ""

        # Extract paragraphs
        content = ""
        if main_content:
            paragraphs = main_content.find_all("p")
            if paragraphs:
                content = "\n\n".join([p.get_text(" ", strip=True) for p in paragraphs if p.get_text(strip=True)])
            else:
                content = main_content.get_text("\n\n", strip=True)

        content = re.sub(r"\n{3,}", "\n\n", content).strip()

        # Extract + filter candidate images (article-only)
        images = _extract_key_images_from_article(main_content, base_url=url)

        # Extract star rating only within header scope of the article (not related thumbnails)
        rating = _extract_rating_scoped(main_content, title=title)

        return WebpageData(
            title=title,
            author=author,
            date=date,
            content=content,
            url=url,
            raw_html=str(soup),
            images=images,
            rating=rating,
        )

    except Exception as e2:
        raise RuntimeError(f"Failed to fetch {url}: {e2}") from e2


# -----------------------------
# Rating extraction (scoped)
# -----------------------------
def _extract_rating_scoped(main_content, title: str) -> Optional[int]:
    """
    Attempt to find a 1-5 star rating ONLY if it appears in the article header scope.
    This avoids picking up ratings in related articles/sidebars.

    Strategy:
    - Look near the top of main_content: first ~3000 chars of text
    - Also look for star glyph patterns (★★★★☆) near the title node if present
    - Accept only clear matches: 1..5
    """
    if not main_content:
        return None

    # Find an h1 inside main_content if possible
    h1 = main_content.find("h1")
    header_region_text = ""

    # Build a small header scope: h1 parent or first few siblings
    if h1 and h1.parent:
        # Use parent text but cap size
        header_region_text = h1.parent.get_text(" ", strip=True)
    else:
        header_region_text = main_content.get_text(" ", strip=True)

    header_region_text = header_region_text[:3000]

    # 1) Unicode stars like ★★★★☆
    # Count filled stars
    m = re.search(r"(★{1,5})(☆{0,5})", header_region_text)
    if m:
        stars = len(m.group(1))
        if 1 <= stars <= 5:
            return stars

    # 2) Text patterns: "4/5", "4 out of 5", "Rated 4"
    m = re.search(r"\b([1-5])\s*/\s*5\b", header_region_text)
    if m:
        return int(m.group(1))

    m = re.search(r"\b([1-5])\s*(?:out of|of)\s*5\b", header_region_text, re.I)
    if m:
        return int(m.group(1))

    # 3) Schema/meta patterns in header (rare but safe)
    # Look for ratingValue in the top of article
    rating_meta = main_content.find(attrs={"itemprop": "ratingValue"})
    if rating_meta and rating_meta.get("content"):
        try:
            v = float(rating_meta["content"])
            v_int = int(round(v))
            if 1 <= v_int <= 5:
                return v_int
        except Exception:
            pass

    return None


def _render_star_rating_html(rating: int) -> str:
    filled = "★" * rating
    empty = "☆" * (5 - rating)
    return f'<div class="rating">{filled}{empty}</div>'


# -----------------------------
# Image extraction + filtering
# -----------------------------
def _extract_key_images_from_article(main_content, base_url: str) -> List[str]:
    """
    Extract images within the main article container only, then filter out
    obvious non-article images (ads/logos/thumbnails/trackers/related blocks).
    """
    if not main_content:
        return []

    candidates: List[str] = []
    for img in main_content.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src")
        if not src:
            continue
        src = src.strip()
        abs_src = _safe_abs_url(base_url, src)
        if not abs_src:
            continue

        # Filter by attribute hints
        alt = (img.get("alt") or "").strip().lower()
        cls = " ".join(img.get("class", [])).lower()
        parent_cls = " ".join((img.parent.get("class", []) if img.parent else [])).lower()
        blob = " ".join([abs_src.lower(), alt, cls, parent_cls])

        # Junk patterns
        if re.search(r"(logo|sprite|icon|avatar|badge|tracking|pixel|doubleclick|ads|adserver|promo|banner|thumb|thumbnail|related)", blob):
            continue

        # Filter 1x1 etc if attributes exist
        try:
            w = int(img.get("width")) if img.get("width") else None
            h = int(img.get("height")) if img.get("height") else None
            if w is not None and h is not None and (w <= 5 or h <= 5):
                continue
        except Exception:
            pass

        candidates.append(abs_src)

    candidates = _dedupe_preserve_order(candidates)

    # Now verify actual pixel dimensions by downloading a few candidates
    # Keep those that look like real images (>=300px wide)
    filtered: List[str] = []
    for u in candidates:
        if _looks_like_real_article_image(u):
            filtered.append(u)
        if len(filtered) >= 6:  # cap before rendering stage
            break

    return filtered


def _looks_like_real_article_image(img_url: str) -> bool:
    """
    Download image headers/bytes and ensure it's likely not a tiny asset.
    Returns True if width >= 300 or height >= 180 (heuristic).
    """
    try:
        import requests
        from PIL import Image

        # Avoid huge downloads; stream and cap
        r = requests.get(img_url, timeout=12, stream=True, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        content_type = (r.headers.get("Content-Type") or "").lower()
        if not any(t in content_type for t in ("image/jpeg", "image/png", "image/webp", "image/gif")):
            return False

        # Read up to ~2.5MB
        max_bytes = 2_500_000
        data = b""
        for chunk in r.iter_content(chunk_size=65536):
            if not chunk:
                break
            data += chunk
            if len(data) > max_bytes:
                break

        im = Image.open(io.BytesIO(data))
        w, h = im.size
        return (w >= 300 and h >= 180) or (w >= 500)  # allow banner-like lead images
    except Exception:
        return False


def _build_lead_images_html(images: List[str], max_images: int = 3) -> str:
    """
    Convert top N image URLs to embedded <img> tags using data URIs (self-contained PDFs).
    """
    html_parts: List[str] = []
    count = 0
    for u in images:
        data_uri = _img_url_to_data_uri(u)
        if not data_uri:
            continue
        html_parts.append(f'<img src="{data_uri}" alt="Article image"/>')
        count += 1
        if count >= max_images:
            break
    return "\n".join(html_parts)


def _img_url_to_data_uri(img_url: str) -> Optional[str]:
    """
    Download image and return data URI.
    """
    try:
        import requests

        r = requests.get(img_url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        ct = (r.headers.get("Content-Type") or "").lower()

        if "image/jpeg" in ct or img_url.lower().endswith((".jpg", ".jpeg")):
            mime = "image/jpeg"
        elif "image/png" in ct or img_url.lower().endswith(".png"):
            mime = "image/png"
        elif "image/webp" in ct or img_url.lower().endswith(".webp"):
            mime = "image/webp"
        elif "image/gif" in ct or img_url.lower().endswith(".gif"):
            mime = "image/gif"
        else:
            return None

        b64 = base64.b64encode(r.content).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception:
        return None


# -----------------------------
# Author/date helpers
# -----------------------------
def _extract_author_from_soup(node) -> str:
    if not node:
        return ""

    # Common patterns: meta name=author, itemprop=author, rel=author, class=byline/author
    meta = node.find("meta", attrs={"name": "author"}) or node.find("meta", attrs={"property": "author"})
    if meta and meta.get("content"):
        return meta["content"].strip()

    author_el = (
        node.find(attrs={"itemprop": "author"})
        or node.find(rel="author")
        or node.find(class_=re.compile(r"(byline|author)", re.I))
    )
    if author_el:
        txt = author_el.get_text(" ", strip=True)
        # Strip "By "
        txt = re.sub(r"^\s*by\s+", "", txt, flags=re.I).strip()
        # keep it short
        return txt[:120]
    return ""


def _extract_date_from_soup(node) -> str:
    if not node:
        return ""

    # Common patterns: <time datetime="...">
    t = node.find("time")
    if t:
        dt = t.get("datetime") or t.get_text(strip=True)
        if dt:
            return dt.strip()[:50]

    meta = node.find("meta", attrs={"property": "article:published_time"}) or node.find("meta", attrs={"name": "date"})
    if meta and meta.get("content"):
        return meta["content"].strip()[:50]

    return ""


# -----------------------------
# Formatting helpers
# -----------------------------
def _format_content_to_html(text: str) -> str:
    paragraphs = text.split("\n\n")
    html_paragraphs = []
    for p in paragraphs:
        p = p.strip()
        if not p:
            continue
        html_paragraphs.append(f"<p>{_escape_html(p)}</p>")
    return "\n".join(html_paragraphs)


def _escape_html(s: str) -> str:
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
    )


def _truncate(s: str, n: int) -> str:
    s = s.strip()
    if len(s) <= n:
        return s
    return s[: max(0, n - 3)].rstrip() + "..."


def _shorten_url_for_display(url: str) -> str:
    if not url:
        return ""
    u = url.strip()
    u = u.replace("https://", "").replace("http://", "")
    return u.rstrip("/")


def _safe_abs_url(base_url: str, maybe_url: str) -> Optional[str]:
    if not maybe_url:
        return None
    try:
        return urljoin(base_url, maybe_url)
    except Exception:
        return None


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    seen = set()
    out = []
    for x in items:
        if x in seen:
            continue
        seen.add(x)
        out.append(x)
    return out


def _try_load_png_as_data_uri(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    try:
        with open(path, "rb") as f:
            b = f.read()
        b64 = base64.b64encode(b).decode("ascii")
        return f"data:image/png;base64,{b64}"
    except Exception:
        return None


# -----------------------------
# ReportLab fallback
# -----------------------------
def _convert_with_reportlab(
    webpage_data: Dict[str, str],
    left_margin_mm: float,
    right_margin_mm: float,
    top_margin_mm: float,
    bottom_margin_mm: float,
) -> bytes:
    """
    Fallback PDF converter using ReportLab.
    Note: This won't match Opera Today styling as closely (no margin-box footer, no embedded images).
    """
    from reportlab.lib.pagesizes import letter
    from reportlab.lib.units import mm
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
    from reportlab.lib.enums import TA_LEFT
    from reportlab.lib import colors

    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        leftMargin=left_margin_mm * mm,
        rightMargin=right_margin_mm * mm,
        topMargin=top_margin_mm * mm,
        bottomMargin=bottom_margin_mm * mm,
    )

    styles = getSampleStyleSheet()

    title_style = ParagraphStyle(
        "CustomTitle",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=6,
        textColor=colors.black,
    )

    body_style = ParagraphStyle(
        "CustomBody",
        parent=styles["BodyText"],
        fontSize=11,
        leading=14,
        alignment=TA_LEFT,
        spaceAfter=10,
        textColor=colors.HexColor("#2f2f2f"),
    )

    url_style = ParagraphStyle(
        "UrlStyle",
        parent=styles["Normal"],
        fontSize=9,
        textColor=colors.HexColor("#333333"),
        spaceAfter=14,
    )

    author_style = ParagraphStyle(
        "AuthorStyle",
        parent=styles["Normal"],
        fontSize=10,
        textColor=colors.black,
        spaceBefore=14,
    )

    story = []
    title = webpage_data.get("title", "Untitled")
    url = webpage_data.get("url", "")
    content = webpage_data.get("content", "")
    author = webpage_data.get("author", "")

    story.append(Paragraph(_escape_html(title), title_style))
    story.append(Paragraph(_escape_html(_shorten_url_for_display(url)), url_style))
    story.append(Spacer(1, 6))

    for para in content.split("\n\n"):
        para = para.strip()
        if para:
            story.append(Paragraph(_escape_html(para), body_style))

    if author:
        story.append(Paragraph(f"<b><i>{_escape_html(author)}</i></b>", author_style))

    doc.build(story)
    buffer.seek(0)
    return buffer.getvalue()


# -----------------------------
# Placeholder evidence function (unchanged)
# -----------------------------
def fetch_organization_evidence(organization_name: str) -> Tuple[Dict, list]:
    return {
        "is_distinguished": True,
        "confidence": "high",
        "reasoning": "International opera house with 100+ year history",
    }, [
        {
            "url": f"https://en.wikipedia.org/wiki/{organization_name.replace(' ', '_')}",
            "title": f"{organization_name} - Wikipedia",
            "snippet": "Official encyclopedia entry",
        }
    ]
