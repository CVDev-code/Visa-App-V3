import io
import math
import re
from typing import Dict, List, Tuple, Optional
from datetime import datetime

import fitz  # PyMuPDF

RED = (1, 0, 0)
WHITE = (1, 1, 1)

# ---- style knobs ----
BOX_WIDTH = 1.7
LINE_WIDTH = 1.6
FONTNAME = "Times-Bold"
FONT_SIZES = [12, 11, 10, 9, 8]

# ---- footer no-go zone (page coordinates; PyMuPDF = top-left origin) ----
NO_GO_RECT = fitz.Rect(
    21.00,   # left
    816.00,  # top
    411.26,  # right
    830.00   # bottom
)

# ---- spacing knobs ----
EDGE_PAD = 18.0  # Increased from 12.0 to give more margin space
GAP_FROM_TEXT_BLOCKS = 12.0  # Increased from 8.0 for better annotation spacing
GAP_FROM_HIGHLIGHTS = 10.0
GAP_BETWEEN_CALLOUTS = 8.0
ENDPOINT_PULLBACK = 1.5

# ---- NEW: Annotation improvement constants ----
MIN_ANNOTATION_SPACING = 25.0   # Minimum vertical gap between annotations
MAX_ANNOTATION_DRIFT = 50.0     # Max distance from ideal Y position
OVERLAP_TOLERANCE = 2.0         # Extra padding to detect overlaps

# Arrowhead (DISABLED by setting to 0)
ARROW_LEN = 0.0  # Changed from 9.0 to 0.0 to disable arrowheads
ARROW_HALF_WIDTH = 0.0  # Changed from 4.5 to 0.0

# For quote search robustness
_MAX_TERM = 600
_CHUNK = 60
_CHUNK_OVERLAP = 18


# ============================================================
# Date parsing and comparison utilities
# ============================================================

def parse_date(date_str: str) -> Optional[datetime]:
    """
    Parse a date string in various common formats.
    Returns a datetime object or None if parsing fails.
    """
    if not date_str or not isinstance(date_str, str):
        return None
    
    date_str = date_str.strip()
    
    # Common date formats to try
    formats = [
        "%B %d, %Y",      # January 25, 2026
        "%b %d, %Y",      # Jan 25, 2026
        "%Y-%m-%d",       # 2026-01-25
        "%d/%m/%Y",       # 25/01/2026
        "%m/%d/%Y",       # 01/25/2026
        "%d.%m.%Y",       # 25.01.2026
        "%d-%m-%Y",       # 25-01-2026
        "%Y/%m/%d",       # 2026/01/25
    ]
    
    for fmt in formats:
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    
    return None


def get_date_label(performance_date_str: str, current_date: Optional[datetime] = None) -> str:
    """
    Determine if a performance date is in the past or future.
    Returns appropriate label text.
    
    Args:
        performance_date_str: The performance date string from metadata
        current_date: The current date (defaults to today if None)
    
    Returns:
        Either "Past performance date." or "Future performance date."
        or "Performance date." if date cannot be parsed
    """
    if current_date is None:
        current_date = datetime.now()
    
    performance_date = parse_date(performance_date_str)
    
    if performance_date is None:
        # Cannot parse date, use generic label
        return "Performance date."
    
    # Compare dates (ignoring time component)
    perf_date_only = performance_date.date()
    current_date_only = current_date.date()
    
    if perf_date_only < current_date_only:
        return "Past performance date."
    elif perf_date_only > current_date_only:
        return "Future performance date."
    else:
        # Same day - treat as current
        return "Performance date."


# ============================================================
# Geometry helpers
# ============================================================

def inflate_rect(r: fitz.Rect, pad: float) -> fitz.Rect:
    rr = fitz.Rect(r)
    rr.x0 -= pad
    rr.y0 -= pad
    rr.x1 += pad
    rr.y1 += pad
    return rr


def _union_rect(rects: List[fitz.Rect]) -> fitz.Rect:
    if not rects:
        return fitz.Rect(0, 0, 0, 0)
    r = fitz.Rect(rects[0])
    for x in rects[1:]:
        r |= x
    return r


def _center(rect: fitz.Rect) -> fitz.Point:
    return fitz.Point((rect.x0 + rect.x1) / 2, (rect.y0 + rect.y1) / 2)


def _pull_back_point(from_pt: fitz.Point, to_pt: fitz.Point, dist: float) -> fitz.Point:
    vx = from_pt.x - to_pt.x
    vy = from_pt.y - to_pt.y
    d = math.hypot(vx, vy)
    if d == 0:
        return to_pt
    ux, uy = vx / d, vy / d
    return fitz.Point(to_pt.x + ux * dist, to_pt.y + uy * dist)


def _segment_hits_rect(p1: fitz.Point, p2: fitz.Point, r: fitz.Rect, steps: int = 60) -> bool:
    for i in range(steps + 1):
        t = i / steps
        x = p1.x + (p2.x - p1.x) * t
        y = p1.y + (p2.y - p1.y) * t
        if r.contains(fitz.Point(x, y)):
            return True
    return False


def _shift_rect_up(rect: fitz.Rect, shift: float, min_y: float = 2.0) -> fitz.Rect:
    if shift <= 0:
        return fitz.Rect(rect)
    h = rect.y1 - rect.y0
    new_y1 = max(min_y + h, rect.y1 - shift)
    return fitz.Rect(rect.x0, new_y1 - h, rect.x1, new_y1)


# ============================================================
# HARD SAFETY: never pass invalid rects into insert_textbox
# ============================================================

def _rect_is_valid(r: fitz.Rect) -> bool:
    vals = [r.x0, r.y0, r.x1, r.y1]
    return (
        all(math.isfinite(v) for v in vals)
        and (r.x1 > r.x0)
        and (r.y1 > r.y0)
    )


def _ensure_min_size(
    r: fitz.Rect,
    pr: fitz.Rect,
    min_w: float = 20.0,
    min_h: float = 12.0,
    pad: float = 2.0,
) -> fitz.Rect:
    rr = fitz.Rect(r)

    cx = (rr.x0 + rr.x1) / 2.0
    cy = (rr.y0 + rr.y1) / 2.0
    w = max(min_w, abs(rr.x1 - rr.x0))
    h = max(min_h, abs(rr.y1 - rr.y0))

    rr = fitz.Rect(cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0)

    rr.x0 = max(pad, rr.x0)
    rr.y0 = max(pad, rr.y0)
    rr.x1 = min(pr.width - pad, rr.x1)
    rr.y1 = min(pr.height - pad, rr.y1)

    if rr.x1 <= rr.x0 or rr.y1 <= rr.y0:
        rr = fitz.Rect(pad, pad, pad + min_w, pad + min_h)

    return rr


# ============================================================
# Text area detection (dynamic margins)
# ============================================================

def _get_fallback_text_area(page: fitz.Page) -> fitz.Rect:
    pr = page.rect
    return fitz.Rect(
        pr.width * 0.12,
        pr.height * 0.12,
        pr.width * 0.88,
        pr.height * 0.88,
    )


def _detect_actual_text_area(page: fitz.Page) -> fitz.Rect:
    try:
        words = page.get_text("words") or []
        if not words:
            return _get_fallback_text_area(page)

        pr = page.rect
        header_limit = pr.height * 0.12
        footer_limit = pr.height * 0.88

        x0s, x1s = [], []
        for w in words:
            x0, y0, x1, y1, text = w[:5]
            if y0 > header_limit and y1 < footer_limit and len((text or "").strip()) > 1:
                x0s.append(float(x0))
                x1s.append(float(x1))

        if not x0s:
            return _get_fallback_text_area(page)

        x0s.sort()
        x1s.sort()

        li = int(len(x0s) * 0.05)
        ri = int(len(x1s) * 0.95)

        text_left = x0s[max(0, li)]
        text_right = x1s[min(len(x1s) - 1, ri)]

        text_left = max(pr.width * 0.08, text_left)
        text_right = min(pr.width * 0.92, text_right)

        if text_right <= text_left + 50:
            return _get_fallback_text_area(page)

        return fitz.Rect(text_left, header_limit, text_right, footer_limit)
    except Exception:
        return _get_fallback_text_area(page)


# ============================================================
# Text wrapping (simple + reliable)
# ============================================================

def _optimize_layout_for_margin(text: str, box_width: float) -> Tuple[int, str, float, float]:
    text = (text or "").strip()
    if not text:
        return 12, "", box_width, 24.0

    words = text.split()
    max_h = 180.0

    for fs in FONT_SIZES:
        usable_w = max(20.0, box_width - 10.0)
        lines: List[str] = []
        cur = ""

        for w in words:
            trial = (cur + " " + w).strip() if cur else w
            if fitz.get_text_length(trial, fontname=FONTNAME, fontsize=fs) <= usable_w:
                cur = trial
            else:
                if cur:
                    lines.append(cur)
                cur = w

        if cur:
            lines.append(cur)

        wrapped = "\n".join(lines)
        h = (len(lines) * fs * 1.25) + 10.0

        if h <= max_h or fs == FONT_SIZES[-1]:
            return fs, wrapped, box_width, h

    return FONT_SIZES[-1], text, box_width, 44.0


# ============================================================
# Fit-guaranteed textbox insertion
# ============================================================

def _insert_textbox_fit(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    *,
    fontname: str,
    fontsize: int,
    color,
    align=fitz.TEXT_ALIGN_LEFT,
    overlay: bool = True,
    max_expand_iters: int = 8,
    extra_pad_each_iter: float = 6.0,
) -> Tuple[fitz.Rect, float, int]:
    pr = page.rect
    r = fitz.Rect(rect)
    fs = int(fontsize)

    r = _ensure_min_size(r, pr)
    if not _rect_is_valid(r):
        return r, 0.0, fs

    attempt = 0
    while attempt < max_expand_iters:
        ret_val = page.insert_textbox(
            r,
            text,
            fontname=fontname,
            fontsize=fs,
            color=color,
            align=align,
            overlay=overlay,
        )

        if ret_val >= 0:
            return r, ret_val, fs

        attempt += 1
        r.y1 = min(r.y1 + extra_pad_each_iter, pr.height - 2.0)
        r.x1 = min(r.x1 + extra_pad_each_iter, pr.width - 2.0)

        if not _rect_is_valid(r):
            break

    # fallback
    final_ret = page.insert_textbox(
        r, text, fontname=fontname, fontsize=fs, color=color, align=align, overlay=overlay
    )
    return r, final_ret, fs


# ============================================================
# Search helpers (chunked, robust)
# ============================================================

def _search_term(page: fitz.Page, term: str) -> List[fitz.Rect]:
    term = (term or "").strip()
    if not term:
        return []

    if len(term) <= _MAX_TERM:
        try:
            return page.search_for(term)
        except Exception:
            return []

    found_rects: List[fitz.Rect] = []
    length = len(term)
    start = 0

    while start < length:
        end = min(start + _CHUNK, length)
        chunk = term[start:end]

        try:
            rects = page.search_for(chunk)
            found_rects.extend(rects)
        except Exception:
            pass

        start += (_CHUNK - _CHUNK_OVERLAP)

    return found_rects


def _dedupe_rects(rects: List[fitz.Rect], pad: float = 1.0) -> List[fitz.Rect]:
    if not rects:
        return []

    rects = sorted(rects, key=lambda r: (r.y0, r.x0))
    out: List[fitz.Rect] = [rects[0]]

    for r in rects[1:]:
        merged = False
        for i, existing in enumerate(out):
            if inflate_rect(existing, pad).intersects(r):
                out[i] = existing | r
                merged = True
                break
        if not merged:
            out.append(r)

    return out


# ============================================================
# Annotation placement (improved spacing)
# ============================================================

def _place_annotation_in_margin(
    page: fitz.Page,
    targets: List[fitz.Rect],
    occupied: List[fitz.Rect],
    label_text: str,
    left_count: int,
    right_count: int,
) -> Tuple[fitz.Rect, str, int, bool]:
    """
    Places annotation in margin with improved vertical spacing.
    Returns: (callout_rect, wrapped_text, fontsize, is_safe_placement)
    """
    if not targets:
        pr = page.rect
        return fitz.Rect(EDGE_PAD, EDGE_PAD, EDGE_PAD + 100, EDGE_PAD + 40), label_text, 10, False

    target_union = _union_rect(targets)
    text_area = _detect_actual_text_area(page)
    pr = page.rect

    # Determine side based on balance
    if left_count <= right_count:
        # Place on left
        side = "left"
        margin_x0 = EDGE_PAD
        margin_x1 = text_area.x0 - GAP_FROM_TEXT_BLOCKS
    else:
        # Place on right
        side = "right"
        margin_x0 = text_area.x1 + GAP_FROM_TEXT_BLOCKS
        margin_x1 = pr.width - EDGE_PAD

    box_width = max(20.0, margin_x1 - margin_x0)
    fs, wrapped, _w, box_h = _optimize_layout_for_margin(label_text, box_width)

    # Ideal Y position (aligned with target)
    ideal_y = target_union.y0

    # Find safe Y position avoiding overlaps
    test_rect = fitz.Rect(margin_x0, ideal_y, margin_x1, ideal_y + box_h)
    
    # Check for overlaps with existing annotations
    def has_overlap(rect: fitz.Rect) -> bool:
        for occ in occupied:
            if inflate_rect(occ, MIN_ANNOTATION_SPACING).intersects(rect):
                return True
        return False
    
    # Try ideal position first
    if not has_overlap(test_rect):
        return test_rect, wrapped, fs, True
    
    # Try moving down in small increments
    max_drift = MAX_ANNOTATION_DRIFT
    step = 5.0
    for offset in range(0, int(max_drift), int(step)):
        test_rect = fitz.Rect(margin_x0, ideal_y + offset, margin_x1, ideal_y + offset + box_h)
        if test_rect.y1 > pr.height - EDGE_PAD:
            break
        if not has_overlap(test_rect):
            return test_rect, wrapped, fs, True
    
    # Try moving up
    for offset in range(int(step), int(max_drift), int(step)):
        test_rect = fitz.Rect(margin_x0, ideal_y - offset, margin_x1, ideal_y - offset + box_h)
        if test_rect.y0 < EDGE_PAD:
            break
        if not has_overlap(test_rect):
            return test_rect, wrapped, fs, True
    
    # Fallback: place at bottom of occupied stack
    if occupied:
        last_occ = max(occupied, key=lambda r: r.y1)
        fallback_y = last_occ.y1 + MIN_ANNOTATION_SPACING
        if fallback_y + box_h < pr.height - EDGE_PAD:
            test_rect = fitz.Rect(margin_x0, fallback_y, margin_x1, fallback_y + box_h)
            return test_rect, wrapped, fs, False
    
    # Ultimate fallback
    return fitz.Rect(margin_x0, ideal_y, margin_x1, ideal_y + box_h), wrapped, fs, False


# ============================================================
# Connector line routing
# ============================================================

def _edge_to_edge_points(r1: fitz.Rect, r2: fitz.Rect) -> Tuple[fitz.Point, fitz.Point]:
    """
    Determine optimal connection points between two rectangles.
    Improved logic: prioritizes horizontal connections and cleaner angles.
    """
    c1 = _center(r1)
    c2 = _center(r2)

    dx = c2.x - c1.x
    dy = c2.y - c1.y

    # Prefer horizontal connections when annotations are in margins
    # This creates cleaner L-shaped lines
    
    # Check if r1 is in left margin and r2 is in content area
    page_center_x = 306  # Approximate center of typical page (612pt wide)
    r1_in_left_margin = r1.x1 < page_center_x * 0.4
    r1_in_right_margin = r1.x0 > page_center_x * 1.6
    r2_in_content = page_center_x * 0.3 < c2.x < page_center_x * 1.7
    
    if r1_in_left_margin and r2_in_content:
        # Annotation on left, target in content
        # Connect from right edge of annotation to left edge of target
        p1 = fitz.Point(r1.x1, c1.y)
        p2 = fitz.Point(r2.x0, c2.y)
    elif r1_in_right_margin and r2_in_content:
        # Annotation on right, target in content  
        # Connect from left edge of annotation to right edge of target
        p1 = fitz.Point(r1.x0, c1.y)
        p2 = fitz.Point(r2.x1, c2.y)
    else:
        # Default behavior: use dominant direction
        if abs(dx) > abs(dy):
            # Horizontal dominant
            if dx > 0:
                p1 = fitz.Point(r1.x1, c1.y)
                p2 = fitz.Point(r2.x0, c2.y)
            else:
                p1 = fitz.Point(r1.x0, c1.y)
                p2 = fitz.Point(r2.x1, c2.y)
        else:
            # Vertical dominant
            if dy > 0:
                p1 = fitz.Point(c1.x, r1.y1)
                p2 = fitz.Point(c2.x, r2.y0)
            else:
                p1 = fitz.Point(c1.x, r1.y0)
                p2 = fitz.Point(c2.x, r2.y1)

    return p1, p2


def _draw_arrowhead(page: fitz.Page, from_pt: fitz.Point, to_pt: fitz.Point):
    """
    Draw an arrowhead at to_pt pointing from from_pt.
    DISABLED: Returns immediately if ARROW_LEN is 0.
    """
    if ARROW_LEN == 0:
        return  # Arrowheads disabled
    
    vx = from_pt.x - to_pt.x
    vy = from_pt.y - to_pt.y
    d = math.hypot(vx, vy)
    if d == 0:
        return

    ux, uy = vx / d, vy / d
    base = fitz.Point(to_pt.x + ux * ARROW_LEN, to_pt.y + uy * ARROW_LEN)

    perp_x, perp_y = -uy, ux
    left = fitz.Point(base.x + perp_x * ARROW_HALF_WIDTH, base.y + perp_y * ARROW_HALF_WIDTH)
    right = fitz.Point(base.x - perp_x * ARROW_HALF_WIDTH, base.y - perp_y * ARROW_HALF_WIDTH)

    page.draw_polyline([left, to_pt, right], color=RED, fill=RED, width=0.5, closePath=True)


def _draw_routed_line(
    page: fitz.Page,
    start: fitz.Point,
    end: fitz.Point,
    obstacles: List[fitz.Rect],
):
    """
    Draw a line from start to end, routing around obstacles with right angles.
    Uses improved routing logic.
    """
    s = _pull_back_point(end, start, ENDPOINT_PULLBACK)
    e = _pull_back_point(start, end, ENDPOINT_PULLBACK)

    # Check if direct path is clear
    direct_blocked = any(_segment_hits_rect(s, e, inflate_rect(obs, 2.0)) for obs in obstacles)
    
    if not direct_blocked:
        # Direct path is clear
        page.draw_line(s, e, color=RED, width=LINE_WIDTH)
        if ARROW_LEN > 0:  # Only draw arrowhead if enabled
            _draw_arrowhead(page, s, e)
        return

    # Need to route around obstacles
    # Try two-segment route (horizontal then vertical, or vice versa)
    mid_h_first = fitz.Point(e.x, s.y)  # horizontal first
    mid_v_first = fitz.Point(s.x, e.y)  # vertical first
    
    # Check horizontal-first route
    h_first_blocked = (
        any(_segment_hits_rect(s, mid_h_first, inflate_rect(obs, 2.0)) for obs in obstacles) or
        any(_segment_hits_rect(mid_h_first, e, inflate_rect(obs, 2.0)) for obs in obstacles)
    )
    
    # Check vertical-first route
    v_first_blocked = (
        any(_segment_hits_rect(s, mid_v_first, inflate_rect(obs, 2.0)) for obs in obstacles) or
        any(_segment_hits_rect(mid_v_first, e, inflate_rect(obs, 2.0)) for obs in obstacles)
    )
    
    if not h_first_blocked:
        # Use horizontal-first route
        page.draw_line(s, mid_h_first, color=RED, width=LINE_WIDTH)
        page.draw_line(mid_h_first, e, color=RED, width=LINE_WIDTH)
        if ARROW_LEN > 0:
            _draw_arrowhead(page, mid_h_first, e)
    elif not v_first_blocked:
        # Use vertical-first route
        page.draw_line(s, mid_v_first, color=RED, width=LINE_WIDTH)
        page.draw_line(mid_v_first, e, color=RED, width=LINE_WIDTH)
        if ARROW_LEN > 0:
            _draw_arrowhead(page, mid_v_first, e)
    else:
        # Both routes blocked, use direct path anyway
        page.draw_line(s, e, color=RED, width=LINE_WIDTH)
        if ARROW_LEN > 0:
            _draw_arrowhead(page, s, e)


def _draw_multipage_connector(
    doc: fitz.Document,
    callout_page_idx: int,
    callout_rect: fitz.Rect,
    target_page_idx: int,
    target_rect: fitz.Rect,
):
    """
    Draw a connector from a callout on one page to a target on another page.
    Routes through page margins.
    """
    if callout_page_idx == target_page_idx:
        return

    callout_page = doc.load_page(callout_page_idx)
    target_page = doc.load_page(target_page_idx)

    # Start from callout
    callout_center = _center(callout_rect)
    start_x = callout_rect.x1 if callout_rect.x1 < callout_page.rect.width / 2 else callout_rect.x0
    start = fitz.Point(start_x, callout_center.y)

    # End at target
    target_center = _center(target_rect)
    end_x = target_rect.x0 if target_rect.x0 > target_page.rect.width / 2 else target_rect.x1
    end = fitz.Point(end_x, target_center.y)

    # Draw vertical line to bottom of callout page
    margin_x = callout_page.rect.width - EDGE_PAD if start_x > callout_page.rect.width / 2 else EDGE_PAD
    bottom_point = fitz.Point(margin_x, callout_page.rect.height - EDGE_PAD)

    callout_page.draw_line(start, fitz.Point(margin_x, start.y), color=RED, width=LINE_WIDTH)
    callout_page.draw_line(fitz.Point(margin_x, start.y), bottom_point, color=RED, width=LINE_WIDTH)

    # Draw on intermediate pages if any
    for pi in range(callout_page_idx + 1, target_page_idx):
        p = doc.load_page(pi)
        top_point = fitz.Point(margin_x, EDGE_PAD)
        bottom_point = fitz.Point(margin_x, p.rect.height - EDGE_PAD)
        p.draw_line(top_point, bottom_point, color=RED, width=LINE_WIDTH)

    # Draw on target page
    top_point = fitz.Point(margin_x, EDGE_PAD)
    target_page.draw_line(top_point, fitz.Point(margin_x, end.y), color=RED, width=LINE_WIDTH)
    target_page.draw_line(fitz.Point(margin_x, end.y), end, color=RED, width=LINE_WIDTH)
    
    # Draw arrowhead only if enabled
    if ARROW_LEN > 0:
        _draw_arrowhead(target_page, fitz.Point(margin_x, end.y), end)


# ============================================================
# Main annotation function
# ============================================================

def annotate_pdf_bytes(
    pdf_bytes: bytes,
    quote_terms: List[str],
    criterion_id: str,
    meta: Dict,
    current_date: Optional[datetime] = None,
) -> Tuple[bytes, Dict]:
    """
    Annotate a PDF with highlights and metadata callouts.
    
    Args:
        pdf_bytes: Input PDF as bytes
        quote_terms: List of text snippets to highlight (these get RED BOXES AND criterion-specific annotation)
        criterion_id: Identifier for the criterion (e.g., "criterion-1", "criterion-2", etc.)
        meta: Metadata dictionary containing:
            - source_url: URL of the publication
            - venue_name: Name of the venue/organization
            - ensemble_name: Name of the performing ensemble
            - performance_date: Date of the performance
            - beneficiary_name: Name of the beneficiary
            - beneficiary_variants: Alternative names for beneficiary
        current_date: Current date for date comparison (defaults to today)
    
    Returns:
        Tuple of (annotated_pdf_bytes, statistics_dict)
    
    ANNOTATION LABEL MAPPING:
    ========================
    
    STANDARD METADATA ANNOTATIONS (all criteria):
    --------------------------------------------
    1. "Original source of publication." 
       - Maps to: meta["source_url"]
       - Appears for any URL/publication source
    
    2. "Distinguished organization."
       - Maps to: meta["venue_name"]
       - Appears for performance venues
    
    3. "Distinguished organization."
       - Maps to: meta["ensemble_name"]
       - Appears for performing groups
    
    4. "Performance date." / "Past performance date." / "Future performance date."
       - Maps to: meta["performance_date"]
       - Label text changes based on date comparison with current_date
       - "Past performance date." if date is before current_date
       - "Future performance date." if date is after current_date
       - "Performance date." if date cannot be parsed or is today
    
    5. "Beneficiary in lead role."
       - Maps to: meta["beneficiary_name"] + meta["beneficiary_variants"]
       - Appears for the person being evaluated
    
    CRITERION-SPECIFIC ANNOTATIONS (for quote_terms):
    ------------------------------------------------
    Criterion 1: "Beneficiary awarded significant industry award."
    Criterion 2: "Beneficiary named in lead role." (past or future based on performance_date)
    Criterion 3: "Beneficiary received significant international acclaim."
    Criterion 4: "Beneficiary named in lead role at distinguished organisation." (past or future)
    Criterion 5: "Achievement received major critical acclaim."
    Criterion 6: "Recognition from leading organization / expert."
    Criterion 7: No criterion-specific annotation (only standard metadata)
    
    NOTE: quote_terms now get BOTH red boxes AND a criterion-specific annotation.
    The first quote_term gets the criterion-specific annotation label.
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if len(doc) == 0:
        return pdf_bytes, {}

    page1 = doc.load_page(0)

    total_quote_hits = 0
    total_meta_hits = 0
    occupied_callouts: List[fitz.Rect] = []
    left_annotation_count = 0
    right_annotation_count = 0

    # Track quote hits with page index for multi-page connectors
    quote_hits_by_page: Dict[int, List[fitz.Rect]] = {}

    # A) Quote highlights (all pages) + dedupe per page
    # Track first quote term occurrence for criterion-specific annotation
    first_quote_term = quote_terms[0] if quote_terms else None
    first_quote_targets_by_page: Dict[int, List[fitz.Rect]] = {}
    
    for page_index in range(doc.page_count):
        page = doc.load_page(page_index)
        page_hits: List[fitz.Rect] = []

        for term in (quote_terms or []):
            rects = _search_term(page, term)
            page_hits.extend(rects)
            
            # Track first quote term separately for annotation
            if term == first_quote_term and rects:
                first_quote_targets_by_page.setdefault(page_index, []).extend(rects)

        page_hits = _dedupe_rects(page_hits, pad=1.0)
        if page_hits:
            quote_hits_by_page[page_index] = page_hits

        for r in page_hits:
            page.draw_rect(r, color=RED, width=BOX_WIDTH)
            total_quote_hits += 1
    
    # Deduplicate first quote term targets per page
    for pi in list(first_quote_targets_by_page.keys()):
        first_quote_targets_by_page[pi] = _dedupe_rects(first_quote_targets_by_page[pi], pad=1.0)

    # B) Metadata callouts (page 1) — targets can exist on any page now
    connectors_to_draw = []  # list of dicts

    def _find_targets_across_doc(needle: str) -> List[Tuple[int, fitz.Rect]]:
        out: List[Tuple[int, fitz.Rect]] = []
        if not needle.strip():
            return out

        for pi in range(doc.page_count):
            p = doc.load_page(pi)
            try:
                rects = p.search_for(needle)
            except Exception:
                rects = []
            for r in rects:
                out.append((pi, r))
        return out

    def _do_job(
        label: str,
        value: Optional[str],
        *,
        connect_policy: str = "union",  # "single" | "union" | "all"
        also_try_variants: Optional[List[str]] = None,
    ):
        nonlocal total_meta_hits
        nonlocal left_annotation_count
        nonlocal right_annotation_count

        needles: List[str] = []
        if value and str(value).strip():
            needles.append(str(value).strip())
        if also_try_variants:
            for v in also_try_variants:
                vv = (v or "").strip()
                if vv:
                    needles.append(vv)

        needles = list(dict.fromkeys(needles))
        if not needles:
            return

        # Find targets across ALL pages (then dedupe per page)
        targets_by_page: Dict[int, List[fitz.Rect]] = {}
        for needle in needles:
            hits = _find_targets_across_doc(needle)
            for pi, r in hits:
                targets_by_page.setdefault(pi, []).append(r)

        # Deduplicate per page
        cleaned_targets_by_page: Dict[int, List[fitz.Rect]] = {}
        for pi, rects in targets_by_page.items():
            deduped = _dedupe_rects(rects, pad=1.0)
            if deduped:
                cleaned_targets_by_page[pi] = deduped

        if not cleaned_targets_by_page:
            return

        # Box only FIRST occurrence, avoid double-boxing with quotes
        boxed_any = False
        
        # Try all occurrences in order until we box one
        for pi in sorted(cleaned_targets_by_page.keys()):
            if boxed_any:
                break
            
            p = doc.load_page(pi)
            page_quote_boxes = quote_hits_by_page.get(pi, [])
            
            for r in cleaned_targets_by_page[pi]:
                # Check if overlaps any quote box (quotes take priority)
                overlaps_quote = any(
                    r.intersects(inflate_rect(qr, OVERLAP_TOLERANCE)) 
                    for qr in page_quote_boxes
                )
                
                if not overlaps_quote:
                    # This is the first non-overlapping occurrence - box it
                    p.draw_rect(r, color=RED, width=BOX_WIDTH)
                    total_meta_hits += 1
                    
                    # Keep ONLY this occurrence for connector (don't overwrite dict structure!)
                    # Clear all other pages/rects, keep only this one
                    cleaned_targets_by_page.clear()
                    cleaned_targets_by_page[pi] = [r]
                    boxed_any = True
                    break
        
        # If all occurrences overlap quotes, don't box any metadata for this field
        if not boxed_any:
            return

        # Place the annotation (callout) on page 1
        # For placement heuristics, we use the union of page-1 targets if any, else union of first found page.
        if 0 in cleaned_targets_by_page:
            placement_targets = cleaned_targets_by_page[0]
        else:
            first_pi = sorted(cleaned_targets_by_page.keys())[0]
            placement_targets = cleaned_targets_by_page[first_pi]

        callout_rect, wrapped_text, fs, _safe = _place_annotation_in_margin(
            page1, placement_targets, occupied_callouts, label,
            left_annotation_count, right_annotation_count
        )

        footer_no_go = fitz.Rect(NO_GO_RECT) & page1.rect
        if footer_no_go.width > 0 and footer_no_go.height > 0 and callout_rect.intersects(footer_no_go):
            shift = (callout_rect.y1 - footer_no_go.y0) + EDGE_PAD
            callout_rect = _shift_rect_up(callout_rect, shift, min_y=EDGE_PAD)

        callout_rect = _ensure_min_size(callout_rect, page1.rect)
        if not _rect_is_valid(callout_rect):
            return

        # White backing + text
        page1.draw_rect(callout_rect, color=WHITE, fill=WHITE, overlay=True)

        final_rect, _ret, _final_fs = _insert_textbox_fit(
            page1,
            callout_rect,
            wrapped_text,
            fontname=FONTNAME,
            fontsize=fs,
            color=RED,
            align=fitz.TEXT_ALIGN_LEFT,
            overlay=True,
        )

        occupied_callouts.append(final_rect)
        
        # Track which side this annotation is on
        if final_rect.x0 < page1.rect.width / 2:
            left_annotation_count += 1
        else:
            right_annotation_count += 1

        # Store connector instructions to draw after all callouts exist
        connectors_to_draw.append(
            {
                "final_rect": final_rect,
                "connect_policy": connect_policy,
                "targets_by_page": cleaned_targets_by_page,
            }
        )

    # --- Criterion-specific annotation (for first quote term) ---
    # Determine the criterion-specific label based on criterion_id
    criterion_label = None
    performance_date_str = meta.get("performance_date")
    
    # Normalize criterion_id (handle both "criterion-1", "criterion_1", "1", etc.)
    criterion_num = None
    if criterion_id:
        criterion_str = str(criterion_id).lower().replace("criterion-", "").replace("criterion_", "").replace("criterion", "").strip()
        try:
            criterion_num = int(criterion_str)
        except (ValueError, TypeError):
            pass
    
    if criterion_num == 1:
        criterion_label = "Beneficiary awarded significant industry award."
    elif criterion_num == 2:
        # Check if past or future based on performance date
        if performance_date_str:
            perf_date = parse_date(performance_date_str)
            if perf_date and perf_date.date() < datetime.now().date():
                criterion_label = "Beneficiary named in lead role."
            else:
                criterion_label = "Beneficiary named in lead role."
        else:
            criterion_label = "Beneficiary named in lead role."
    elif criterion_num == 3:
        criterion_label = "Beneficiary received significant international acclaim."
    elif criterion_num == 4:
        # Check if past or future based on performance date
        if performance_date_str:
            perf_date = parse_date(performance_date_str)
            if perf_date and perf_date.date() < datetime.now().date():
                criterion_label = "Beneficiary named in lead role at distinguished organisation."
            else:
                criterion_label = "Beneficiary named in lead role at distinguished organisation."
        else:
            criterion_label = "Beneficiary named in lead role at distinguished organisation."
    elif criterion_num == 5:
        criterion_label = "Achievement received major critical acclaim."
    elif criterion_num == 6:
        criterion_label = "Recognition from leading organization / expert."
    # Criterion 7 gets no criterion-specific annotation
    
    # Apply criterion-specific annotation to first quote term if we have one
    if criterion_label and first_quote_targets_by_page:
        # Find first occurrence (same logic as metadata)
        boxed_any = False
        annotated_targets_by_page: Dict[int, List[fitz.Rect]] = {}
        
        for pi in sorted(first_quote_targets_by_page.keys()):
            if boxed_any:
                break
            
            page_quote_boxes = quote_hits_by_page.get(pi, [])
            
            for r in first_quote_targets_by_page[pi]:
                # The quote is already boxed from the highlighting phase above
                # We just need to add an annotation for it
                # Keep ONLY this occurrence for annotation
                annotated_targets_by_page[pi] = [r]
                boxed_any = True
                break
        
        if annotated_targets_by_page:
            # Place the criterion annotation
            if 0 in annotated_targets_by_page:
                placement_targets = annotated_targets_by_page[0]
            else:
                first_pi = sorted(annotated_targets_by_page.keys())[0]
                placement_targets = annotated_targets_by_page[first_pi]
            
            callout_rect, wrapped_text, fs, _safe = _place_annotation_in_margin(
                page1, placement_targets, occupied_callouts, criterion_label,
                left_annotation_count, right_annotation_count
            )
            
            footer_no_go = fitz.Rect(NO_GO_RECT) & page1.rect
            if footer_no_go.width > 0 and footer_no_go.height > 0 and callout_rect.intersects(footer_no_go):
                shift = (callout_rect.y1 - footer_no_go.y0) + EDGE_PAD
                callout_rect = _shift_rect_up(callout_rect, shift, min_y=EDGE_PAD)
            
            callout_rect = _ensure_min_size(callout_rect, page1.rect)
            
            if _rect_is_valid(callout_rect):
                # White backing + text
                page1.draw_rect(callout_rect, color=WHITE, fill=WHITE, overlay=True)
                
                final_rect, _ret, _final_fs = _insert_textbox_fit(
                    page1,
                    callout_rect,
                    wrapped_text,
                    fontname=FONTNAME,
                    fontsize=fs,
                    color=RED,
                    align=fitz.TEXT_ALIGN_LEFT,
                    overlay=True,
                )
                
                occupied_callouts.append(final_rect)
                
                # Track which side this annotation is on
                if final_rect.x0 < page1.rect.width / 2:
                    left_annotation_count += 1
                else:
                    right_annotation_count += 1
                
                # Store connector instructions
                connectors_to_draw.append(
                    {
                        "final_rect": final_rect,
                        "connect_policy": "all",
                        "targets_by_page": annotated_targets_by_page,
                    }
                )

    # --- Meta labels (standard metadata annotations) ---
    # For source_url, try multiple variants (with/without protocol, with/without www)
    source_url = meta.get("source_url")
    source_url_variants = []
    if source_url:
        # Try without https://
        without_protocol = source_url.replace('https://', '').replace('http://', '')
        source_url_variants.append(without_protocol)
        
        # Try with just domain (theatermania.com)
        if without_protocol.startswith('www.'):
            without_www = without_protocol.replace('www.', '', 1)
            source_url_variants.append(without_www)
    
    _do_job("Original source of publication.", source_url, 
            connect_policy="all", also_try_variants=source_url_variants)
    _do_job("Distinguished organization.", meta.get("venue_name"), connect_policy="all")
    _do_job("Distinguished organization.", meta.get("ensemble_name"), connect_policy="all")
    
    # Performance date with smart past/future detection
    # IMPORTANT: Pass current_date parameter to enable past/future detection
    # Example: annotate_pdf_bytes(..., current_date=datetime.now())
    performance_date_str = meta.get("performance_date")
    if performance_date_str:
        # If current_date is None, use datetime.now() by default
        effective_current_date = current_date if current_date is not None else datetime.now()
        date_label = get_date_label(performance_date_str, effective_current_date)
        _do_job(date_label, performance_date_str, connect_policy="all")

    # Beneficiary targets (still value-driven)
    _do_job(
        "Beneficiary in lead role.",
        meta.get("beneficiary_name"),
        connect_policy="all",
        also_try_variants=meta.get("beneficiary_variants") or [],
    )

    # Second pass: draw connectors AFTER all callouts exist
    for item in connectors_to_draw:
        final_rect = item["final_rect"]
        targets_by_page = item["targets_by_page"]
        connect_policy = item["connect_policy"]

        # Draw connectors to ALL targets across pages, routed down margins if needed.
        # NOTE: callout is always on page 0.
        callout_page_index = 0

        for pi, rects in targets_by_page.items():
            if connect_policy == "single" and rects:
                rects = rects[:1]

            for r in rects:
                if pi == 0:
                    # Same-page: route around obstacles
                    s, e = _edge_to_edge_points(final_rect, r)
                    
                    # Collect obstacles (all red boxes + all OTHER annotations, not this one!)
                    other_annotations = [ann for ann in occupied_callouts if ann != final_rect]
                    obstacles = quote_hits_by_page.get(0, []) + other_annotations
                    
                    # Use smart routing
                    _draw_routed_line(page1, s, e, obstacles)
                else:
                    _draw_multipage_connector(doc, callout_page_index, final_rect, pi, r)

    out = io.BytesIO()
    doc.save(out)
    doc.close()
    out.seek(0)

    return out.getvalue(), {
        "total_quote_hits": total_quote_hits,
        "total_meta_hits": total_meta_hits,
        "criterion_id": criterion_id,
    }
