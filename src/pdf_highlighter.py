import io
import math
import re
import os
from typing import Dict, List, Tuple, Optional, Any

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
EDGE_PAD = 12.0
GAP_FROM_TEXT_BLOCKS = 8.0
GAP_FROM_HIGHLIGHTS = 10.0
GAP_BETWEEN_CALLOUTS = 10.0  # consistent legibility gap
ENDPOINT_PULLBACK = 1.5

# Arrowhead
ARROW_LEN = 9.0
ARROW_HALF_WIDTH = 4.5

# For quote search robustness
_MAX_TERM = 600
_CHUNK = 60
_CHUNK_OVERLAP = 18

# ---- deterministic side assignment ----
SIDE_LEFT_LABELS = {
    "Original source of publication.",
    "Venue is distinguished organization.",
    "Ensemble is distinguished organization.",
}
SIDE_RIGHT_LABELS = {
    "Performance date.",
    "Beneficiary lead role evidence.",
    "Highly acclaimed review of the distinguished performance.",
}

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


def _segment_hits_rect(p1: fitz.Point, p2: fitz.Point, r: fitz.Rect, steps: int = 80) -> bool:
    for i in range(steps + 1):
        t = i / steps
        x = p1.x + (p2.x - p1.x) * t
        y = p1.y + (p2.y - p1.y) * t
        if r.contains(fitz.Point(x, y)):
            return True
    return False


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
    min_w: float = 50.0,
    min_h: float = 14.0,
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
    """
    Coarse bounding box of main body text region.
    Used as a hard exclusion zone for callout boxes.
    """
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
# Text wrapping
# ============================================================

def _optimize_layout_for_margin(text: str, box_width: float) -> Tuple[int, str, float, float]:
    text = (text or "").strip()
    if not text:
        return 12, "", box_width, 24.0
    words = text.split()
    max_h = 200.0

    for fs in FONT_SIZES:
        usable_w = max(30.0, box_width - 10.0)
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

    return FONT_SIZES[-1], text, box_width, 50.0


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
    r = _ensure_min_size(fitz.Rect(rect), pr)
    fs = int(fontsize)

    def attempt(rr: fitz.Rect, fsize: int) -> float:
        rr = _ensure_min_size(rr, pr)
        if not _rect_is_valid(rr):
            return -1.0
        return page.insert_textbox(
            rr,
            text,
            fontname=fontname,
            fontsize=fsize,
            color=color,
            align=align,
            overlay=overlay,
        )

    ret = attempt(r, fs)
    it = 0
    while ret < 0 and it < max_expand_iters:
        need = (-ret) + extra_pad_each_iter
        r.y0 -= need / 2.0
        r.y1 += need / 2.0
        r.y0 = max(2.0, r.y0)
        r.y1 = min(pr.height - 2.0, r.y1)
        ret = attempt(r, fs)
        it += 1

    shrink_tries = 0
    while ret < 0 and fs > FONT_SIZES[-1] and shrink_tries < 4:
        fs -= 1
        r = _ensure_min_size(fitz.Rect(rect), pr)
        ret = attempt(r, fs)
        it = 0
        while ret < 0 and it < max_expand_iters:
            need = (-ret) + extra_pad_each_iter
            r.y0 -= need / 2.0
            r.y1 += need / 2.0
            r.y0 = max(2.0, r.y0)
            r.y1 = min(pr.height - 2.0, r.y1)
            ret = attempt(r, fs)
            it += 1
        shrink_tries += 1

    return r, ret, fs


# ============================================================
# De-duplication
# ============================================================

def _rect_area(r: fitz.Rect) -> float:
    return max(0.0, (r.x1 - r.x0) * (r.y1 - r.y0))


def _dedupe_rects(rects: List[fitz.Rect], pad: float = 1.0) -> List[fitz.Rect]:
    if not rects:
        return []
    rr = [fitz.Rect(r) for r in rects]
    rr.sort(key=lambda r: _rect_area(r), reverse=True)
    kept: List[fitz.Rect] = []
    for r in rr:
        rbuf = inflate_rect(r, pad)
        contained = False
        for k in kept:
            if inflate_rect(k, pad).contains(rbuf):
                contained = True
                break
        if not contained:
            kept.append(r)
    kept.sort(key=lambda r: (r.y0, r.x0))
    return kept


# ============================================================
# Robust search helpers
# ============================================================

def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()


def _search_term(page: fitz.Page, term: str) -> List[fitz.Rect]:
    t = (term or "").strip()
    if not t:
        return []
    if len(t) > _MAX_TERM:
        t = t[:_MAX_TERM]

    flags = 0
    try:
        flags |= fitz.TEXT_DEHYPHENATE
    except Exception:
        pass
    try:
        flags |= fitz.TEXT_PRESERVE_WHITESPACE
    except Exception:
        pass

    try:
        rects = page.search_for(t, flags=flags)
        if rects:
            return rects
    except Exception:
        pass

    t2 = _normalize_spaces(t)
    if t2 and t2 != t:
        try:
            rects = page.search_for(t2, flags=flags)
            if rects:
                return rects
        except Exception:
            pass

    if len(t2) >= _CHUNK:
        hits: List[fitz.Rect] = []
        step = max(10, _CHUNK - _CHUNK_OVERLAP)
        for i in range(0, len(t2), step):
            chunk = t2[i:i + _CHUNK].strip()
            if len(chunk) < 18:
                continue
            try:
                hits.extend(page.search_for(chunk, flags=flags))
            except Exception:
                continue

        if hits:
            hits_sorted = sorted(hits, key=lambda r: (r.y0, r.x0))
            merged: List[fitz.Rect] = []
            for r in hits_sorted:
                if not merged:
                    merged.append(fitz.Rect(r))
                else:
                    last = merged[-1]
                    if last.intersects(r) or abs(last.y0 - r.y0) < 3.0:
                        merged[-1] = last | r
                    else:
                        merged.append(fitz.Rect(r))
            return merged

    return []


# ============================================================
# URL helpers (reverted – no header prioritisation)
# ============================================================

def _looks_like_url(s: str) -> bool:
    s = (s or "").strip().lower()
    return s.startswith("http://") or s.startswith("https://") or s.startswith("www.")


def _normalize_urlish(s: str) -> str:
    s = (s or "").strip().lower()
    s = s.strip(" \t\r\n'\"()[]{}<>.,;")
    s = re.sub(r"^https?://", "", s)
    s = re.sub(r"^www\.", "", s)
    s = s.rstrip("/")
    return s


def _is_same_urlish(a: str, b: str) -> bool:
    na = _normalize_urlish(a)
    nb = _normalize_urlish(b)
    if not na or not nb:
        return False
    return na == nb


# ============================================================
# Arrow drawing
# ============================================================

def _draw_arrowhead(page: fitz.Page, start: fitz.Point, end: fitz.Point):
    vx = end.x - start.x
    vy = end.y - start.y
    d = math.hypot(vx, vy)
    if d == 0:
        return
    ux, uy = vx / d, vy / d
    bx = end.x - ux * ARROW_LEN
    by = end.y - uy * ARROW_LEN
    px = -uy
    py = ux
    p1 = fitz.Point(bx + px * ARROW_HALF_WIDTH, by + py * ARROW_HALF_WIDTH)
    p2 = fitz.Point(bx - px * ARROW_HALF_WIDTH, by - py * ARROW_HALF_WIDTH)
    tip = fitz.Point(end.x, end.y)
    page.draw_polyline([p1, tip, p2, p1], color=RED, fill=RED, width=0.0)


def _draw_line(page: fitz.Page, a: fitz.Point, b: fitz.Point):
    page.draw_line(a, b, color=RED, width=LINE_WIDTH)


def _draw_poly_connector(page: fitz.Page, pts: List[fitz.Point]):
    if len(pts) < 2:
        return
    for a, b in zip(pts, pts[1:]):
        _draw_line(page, a, b)
    _draw_arrowhead(page, pts[-2], pts[-1])


# ============================================================
# Deterministic margin lanes (equal widths)
# ============================================================

def _compute_equal_margins(page: fitz.Page) -> Tuple[fitz.Rect, fitz.Rect, fitz.Rect]:
    """
    Returns (text_area, left_lane_rect, right_lane_rect) with equal lane widths.
    Lanes are outside the detected text_area and symmetric by width.
    """
    pr = page.rect
    text_area = _detect_actual_text_area(page)

    left_available = max(0.0, text_area.x0 - EDGE_PAD)
    right_available = max(0.0, (pr.width - EDGE_PAD) - text_area.x1)
    lane_w = max(0.0, min(left_available, right_available))

    # Ensure lanes are real rectangles; if lane_w is too small, you still get something minimal
    lane_w = max(lane_w, 60.0)

    left_lane = fitz.Rect(EDGE_PAD, EDGE_PAD, EDGE_PAD + lane_w, pr.height - EDGE_PAD)
    right_lane = fitz.Rect(pr.width - EDGE_PAD - lane_w, EDGE_PAD, pr.width - EDGE_PAD, pr.height - EDGE_PAD)

    return text_area, left_lane, right_lane


def _choose_side_for_label(label: str) -> str:
    if label in SIDE_LEFT_LABELS:
        return "left"
    if label in SIDE_RIGHT_LABELS:
        return "right"
    # default (if you add more later)
    return "left"


def _rect_conflicts(r: fitz.Rect, occupied: List[fitz.Rect], pad: float = 0.0) -> bool:
    rr = inflate_rect(r, pad) if pad else r
    for o in occupied:
        if rr.intersects(o):
            return True
    return False


def _place_callout_in_lane(
    page: fitz.Page,
    lane: fitz.Rect,
    text_area: fitz.Rect,
    target_union: fitz.Rect,
    occupied_same_side: List[fitz.Rect],
    label: str,
) -> Tuple[fitz.Rect, str, int]:
    """
    Place a callout box in the given lane near target y, maintaining a minimum gap.
    Hard rules:
      - must be inside lane
      - must not intersect text_area
      - must not intersect target_no_go (inflated target)
      - must not intersect footer no-go
      - must not overlap other callouts on the same side
    """
    pr = page.rect
    footer_no_go = fitz.Rect(NO_GO_RECT) & pr
    target_no_go = inflate_rect(target_union, GAP_FROM_HIGHLIGHTS)

    lane_w = lane.x1 - lane.x0
    max_w = min(180.0, lane_w - 8.0)
    max_w = max(max_w, 70.0)

    fs, wrapped, w_used, h_needed = _optimize_layout_for_margin(label, max_w)
    w_used = min(w_used, max_w)

    # Create a candidate rect for a given center y
    def build_at_y(cy: float) -> fitz.Rect:
        y0 = cy - h_needed / 2.0
        y1 = cy + h_needed / 2.0
        y0 = max(lane.y0, y0)
        y1 = min(lane.y1, y1)
        if (y1 - y0) < (h_needed * 0.85):
            # enforce minimum height region
            y1 = min(lane.y1, y0 + h_needed)
            y0 = max(lane.y0, y1 - h_needed)

        x0 = lane.x0 + 4.0
        x1 = min(lane.x1 - 4.0, x0 + w_used)
        cand = fitz.Rect(x0, y0, x1, y1)
        cand = _ensure_min_size(cand, pr, min_w=55.0, min_h=14.0)
        return cand

    def allowed(cand: fitz.Rect) -> bool:
        if not lane.contains(cand):
            return False
        if cand.intersects(text_area):
            return False
        if cand.intersects(target_no_go):
            return False
        if footer_no_go.width > 0 and footer_no_go.height > 0 and cand.intersects(footer_no_go):
            return False
        if _rect_conflicts(cand, occupied_same_side, pad=GAP_BETWEEN_CALLOUTS):
            return False
        return True

    # Scan around target y to find closest available slot
    target_y = _center(target_union).y
    scan_steps = [0, 20, -20, 40, -40, 60, -60, 80, -80, 100, -100, 120, -120, 150, -150, 180, -180]

    for dy in scan_steps:
        cand = build_at_y(target_y + dy)
        if allowed(cand):
            return cand, wrapped, fs

    # If still not found, try stacking below/above existing callouts within lane
    # (Pick the first open "slot" in reading order)
    y_cursor = lane.y0 + 10.0
    while y_cursor + h_needed < lane.y1 - 10.0:
        cand = build_at_y(y_cursor + h_needed / 2.0)
        if allowed(cand):
            return cand, wrapped, fs
        y_cursor += (h_needed + GAP_BETWEEN_CALLOUTS)

    # Absolute last resort: return something in lane (may overlap callouts if impossible)
    return build_at_y(min(max(target_y, lane.y0 + 20), lane.y1 - 20)), wrapped, fs


# ============================================================
# Connectors that NEVER go through callout boxes
# ============================================================

def _callout_edge_point_toward_gutter(callout: fitz.Rect, gutter_x: float) -> fitz.Point:
    cy = (callout.y0 + callout.y1) / 2.0
    if gutter_x < callout.x0:
        return fitz.Point(callout.x0, min(max(cy, callout.y0 + 1), callout.y1 - 1))
    else:
        return fitz.Point(callout.x1, min(max(cy, callout.y0 + 1), callout.y1 - 1))


def _target_edge_point_toward_gutter(target: fitz.Rect, gutter_x: float, desired_y: float) -> fitz.Point:
    y = min(max(desired_y, target.y0 + 1), target.y1 - 1)
    if gutter_x < target.x0:
        end_raw = fitz.Point(target.x0, y)
    else:
        end_raw = fitz.Point(target.x1, y)
    return end_raw


def _route_connector_no_callout_crossing(
    page: fitz.Page,
    callout: fitz.Rect,
    target: fitz.Rect,
    callout_blocks: List[fitz.Rect],
) -> List[fitz.Point]:
    """
    Route: callout edge -> gutter (outside margins) -> vertical -> target edge.
    This makes it extremely unlikely to cross any callout box.
    If a segment would still cross a callout, it tries the other gutter.
    """
    pr = page.rect
    tc = _center(target)

    gutters = [
        EDGE_PAD,               # left gutter
        pr.width - EDGE_PAD,    # right gutter
    ]

    # Try preferred gutter based on which side callout is on
    callout_c = _center(callout)
    preferred = gutters[1] if callout_c.x > pr.width / 2 else gutters[0]
    ordered_gutters = [preferred] + [g for g in gutters if g != preferred]

    for gx in ordered_gutters:
        start = _callout_edge_point_toward_gutter(callout, gx)
        # pull outward just a touch so we don't graze callout boundary
        start_out = fitz.Point(gx, start.y)

        mid = fitz.Point(gx, min(max(tc.y, EDGE_PAD), pr.height - EDGE_PAD))
        end_raw = _target_edge_point_toward_gutter(target, gx, mid.y)
        end = _pull_back_point(mid, end_raw, ENDPOINT_PULLBACK)

        pts = [start, start_out, mid, end]

        # Validate: no segment goes through any callout block (inflated)
        ok = True
        for a, b in zip(pts, pts[1:]):
            for br in callout_blocks:
                if _segment_hits_rect(a, b, br):
                    ok = False
                    break
            if not ok:
                break

        if ok:
            return pts

    # Absolute last resort: direct line (still pulled back)
    start = fitz.Point(callout.x1, (callout.y0 + callout.y1) / 2.0)
    end_raw = fitz.Point(target.x0, (target.y0 + target.y1) / 2.0)
    end = _pull_back_point(start, end_raw, ENDPOINT_PULLBACK)
    return [start, end]


# ============================================================
# Multi-page routing (kept simple; stays in gutter)
# ============================================================

def _draw_multipage_connector(
    doc: fitz.Document,
    callout_page_index: int,
    callout_rect: fitz.Rect,
    target_page_index: int,
    target_rect: fitz.Rect,
):
    callout_page = doc.load_page(callout_page_index)
    pr = callout_page.rect
    callout_c = _center(callout_rect)

    gutter_side = "right" if callout_c.x >= pr.width / 2 else "left"
    gutter_x = pr.width - EDGE_PAD if gutter_side == "right" else EDGE_PAD

    start = _callout_edge_point_toward_gutter(callout_rect, gutter_x)
    p_gutter_start = fitz.Point(gutter_x, min(max(start.y, EDGE_PAD), pr.height - EDGE_PAD))
    p_gutter_bottom = fitz.Point(gutter_x, pr.height - EDGE_PAD)

    _draw_line(callout_page, start, p_gutter_start)
    _draw_line(callout_page, p_gutter_start, p_gutter_bottom)

    for pi in range(callout_page_index + 1, target_page_index):
        p = doc.load_page(pi)
        pr_i = p.rect
        gx = pr_i.width - EDGE_PAD if gutter_side == "right" else EDGE_PAD
        _draw_line(p, fitz.Point(gx, EDGE_PAD), fitz.Point(gx, pr_i.height - EDGE_PAD))

    tp = doc.load_page(target_page_index)
    pr_t = tp.rect
    gx_t = pr_t.width - EDGE_PAD if gutter_side == "right" else EDGE_PAD
    tc = _center(target_rect)
    y_target = min(max(tc.y, EDGE_PAD), pr_t.height - EDGE_PAD)

    p_top = fitz.Point(gx_t, EDGE_PAD)
    p_mid = fitz.Point(gx_t, y_target)

    end_raw = _target_edge_point_toward_gutter(target_rect, gx_t, y_target)
    end = _pull_back_point(p_mid, end_raw, ENDPOINT_PULLBACK)

    _draw_line(tp, p_top, p_mid)
    _draw_line(tp, p_mid, end)
    _draw_arrowhead(tp, p_mid, end)


# ============================================================
# Stars helper
# ============================================================

_STAR_CRITERIA = {"3", "2_past", "4_past"}

def _find_high_star_tokens(page: fitz.Page) -> List[str]:
    text = page.get_text("text") or ""
    tokens: List[str] = []
    for m in re.finditer(r"(?<!\*)\*{4,5}(?!\*)", text):
        tokens.append(m.group(0))
    for m in re.finditer(r"[★☆]{5}", text):
        tok = m.group(0)
        if tok.count("★") >= 4:
            tokens.append(tok)
    out = []
    seen = set()
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


# ============================================================
# Main annotation entrypoint
# ============================================================

def annotate_pdf_bytes(
    pdf_bytes: bytes,
    quote_terms: List[str],
    criterion_id: str,
    meta: Dict,
) -> Tuple[bytes, Dict]:

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if len(doc) == 0:
        return pdf_bytes, {}

    page1 = doc.load_page(0)

    total_quote_hits = 0
    total_meta_hits = 0

    occupied_left: List[fitz.Rect] = []
    occupied_right: List[fitz.Rect] = []
    all_callouts: List[fitz.Rect] = []

    connectors_to_draw: List[Dict[str, Any]] = []

    text_area, left_lane, right_lane = _compute_equal_margins(page1)
    pr1 = page1.rect
    footer_no_go_p1 = fitz.Rect(NO_GO_RECT) & pr1

    # ------------------------------------------------------------
    # 1) Highlights for quotes (URLs restricted to page 1 as before)
    # ------------------------------------------------------------
    meta_url = (meta.get("source_url") or "").strip()
    for page in doc:
        for term in (quote_terms or []):
            t = (term or "").strip()
            if not t:
                continue
            is_url_term = _looks_like_url(t) or (meta_url and _is_same_urlish(t, meta_url))
            if is_url_term and page.number != 0:
                continue
            rects = _search_term(page, t)
            for r in _dedupe_rects(rects):
                page.draw_rect(r, color=RED, width=BOX_WIDTH)
                total_quote_hits += 1

    # ------------------------------------------------------------
    # 2) Metadata search + callouts (deterministic side)
    # ------------------------------------------------------------
    def _find_targets_across_doc(needle: str, *, page_indices: Optional[List[int]] = None) -> List[Tuple[int, fitz.Rect]]:
        out = []
        needle = (needle or "").strip()
        if not needle:
            return out
        indices = page_indices if page_indices is not None else list(range(doc.page_count))
        for pi in indices:
            p = doc.load_page(pi)
            try:
                rects = p.search_for(needle)
            except Exception:
                rects = []
            for r in rects:
                out.append((pi, r))
        return out

    def _place_and_register_callout(label: str, targets_by_page: Dict[int, List[fitz.Rect]]):
        nonlocal occupied_left, occupied_right, all_callouts

        if not targets_by_page:
            return

        # Choose targets to anchor placement (prefer page 1, else first page found)
        if 0 in targets_by_page:
            anchor_targets = targets_by_page[0]
        else:
            first_pi = sorted(targets_by_page.keys())[0]
            anchor_targets = targets_by_page[first_pi]

        anchor_targets = _dedupe_rects(anchor_targets)
        if not anchor_targets:
            return

        target_union = _union_rect(anchor_targets)

        side = _choose_side_for_label(label)
        lane = left_lane if side == "left" else right_lane
        occupied = occupied_left if side == "left" else occupied_right

        crect, wtext, fs = _place_callout_in_lane(
            page1,
            lane=lane,
            text_area=text_area,
            target_union=target_union,
            occupied_same_side=occupied,
            label=label,
        )

        # Hard footer adjustment (keep callouts out of footer no-go)
        if footer_no_go_p1.width > 0 and footer_no_go_p1.height > 0 and crect.intersects(footer_no_go_p1):
            shift = (crect.y1 - footer_no_go_p1.y0) + EDGE_PAD
            crect = fitz.Rect(crect.x0, crect.y0 - shift, crect.x1, crect.y1 - shift)
            crect = _ensure_min_size(crect, page1.rect)

        if not _rect_is_valid(crect):
            return

        # Draw white background and red text
        page1.draw_rect(crect, color=WHITE, fill=WHITE, overlay=True)
        final_r, _, _ = _insert_textbox_fit(page1, crect, wtext, fontname=FONTNAME, fontsize=fs, color=RED)

        # Register occupancy
        if side == "left":
            occupied_left.append(final_r)
        else:
            occupied_right.append(final_r)

        all_callouts.append(final_r)

        connectors_to_draw.append({
            "final_rect": final_r,
            "targets_by_page": targets_by_page
        })

    def _do_job(label: str, value: Optional[str], variants: List[str] = None):
        nonlocal total_meta_hits

        val_str = str(value or "").strip()
        if not val_str:
            return

        is_url = _looks_like_url(val_str) or (meta_url and _is_same_urlish(val_str, meta_url))
        indices = [0] if is_url else None  # URL only on page 1

        needles = list(dict.fromkeys([val_str] + (variants or [])))
        targets_by_page: Dict[int, List[fitz.Rect]] = {}

        for n in needles:
            for pi, r in _find_targets_across_doc(n, page_indices=indices):
                targets_by_page.setdefault(pi, []).append(r)

        if not targets_by_page:
            return

        # Draw red boxes for all matches found (URL is effectively only footer in your export)
        for pi, rects in targets_by_page.items():
            p = doc.load_page(pi)
            for r in _dedupe_rects(rects):
                p.draw_rect(r, color=RED, width=BOX_WIDTH)
                total_meta_hits += 1

        # Callout placement: URL only on page 1; others across doc
        if is_url:
            targets_by_page = {0: targets_by_page.get(0, [])}
            if not targets_by_page[0]:
                return

        _place_and_register_callout(label, targets_by_page)

    _do_job("Original source of publication.", meta.get("source_url"))
    _do_job("Venue is distinguished organization.", meta.get("venue_name"))
    _do_job("Ensemble is distinguished organization.", meta.get("ensemble_name"))
    _do_job("Performance date.", meta.get("performance_date"))
    _do_job("Beneficiary lead role evidence.", meta.get("beneficiary_name"), meta.get("beneficiary_variants"))

    # ------------------------------------------------------------
    # 3) Stars Logic (right side by rule)
    # ------------------------------------------------------------
    if criterion_id in _STAR_CRITERIA:
        stars_map: Dict[int, List[fitz.Rect]] = {}
        for p in doc:
            for tok in _find_high_star_tokens(p):
                found = p.search_for(tok)
                if found:
                    stars_map.setdefault(p.number, []).extend(found)
                    for r in _dedupe_rects(found):
                        p.draw_rect(r, color=RED, width=BOX_WIDTH)
                        total_quote_hits += 1

        if stars_map:
            _place_and_register_callout(
                "Highly acclaimed review of the distinguished performance.",
                stars_map
            )

    # ------------------------------------------------------------
    # 4) Draw Connectors (allowed across body text, forbidden through callouts)
    # ------------------------------------------------------------
    callout_blocks = [inflate_rect(c, GAP_BETWEEN_CALLOUTS / 2.0) for c in all_callouts]

    for item in connectors_to_draw:
        fr = item["final_rect"]
        for pi, rects in item["targets_by_page"].items():
            for r in _dedupe_rects(rects):
                if pi == 0:
                    pts = _route_connector_no_callout_crossing(page1, fr, r, callout_blocks)
                    _draw_poly_connector(page1, pts)
                else:
                    _draw_multipage_connector(doc, 0, fr, pi, r)

    out = io.BytesIO()
    doc.save(out)
    doc.close()
    out.seek(0)

    return out.getvalue(), {
        "total_quote_hits": total_quote_hits,
        "total_meta_hits": total_meta_hits,
        "criterion_id": criterion_id
    }
