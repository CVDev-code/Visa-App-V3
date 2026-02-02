import io
import math
import re
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional, Any

import fitz  # PyMuPDF

# ============================================================
# Style knobs
# ============================================================

RED = (1, 0, 0)
WHITE = (1, 1, 1)

BOX_WIDTH = 1.7
FONTNAME = "Times-Bold"
FONT_SIZES = [11, 10, 9, 8]

EDGE_PAD = 12.0
GAP_FROM_HIGHLIGHTS = 10.0
GAP_BETWEEN_CALLOUTS = 10.0

# Footer no-go zone (page coords; top-left origin)
NO_GO_RECT = fitz.Rect(21.00, 816.00, 411.26, 830.00)

# Quote search robustness
_MAX_TERM = 600
_CHUNK = 60
_CHUNK_OVERLAP = 18

# Routing / scoring weights
W_DIST = 1.0
W_CROSS = 18.0          # crossings are expensive (to avoid clutter)
W_SHIFT = 2.5           # keep callout aligned to anchor y
W_OVERLAP = 15.0        # avoid colliding callouts
W_FOOTER = 50.0         # avoid footer region on page 1

ARROW_LEN = 7.0
ARROW_ANGLE_DEG = 28.0
LEADER_WIDTH = 1.5

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

def _rect_is_valid(r: fitz.Rect) -> bool:
    vals = [r.x0, r.y0, r.x1, r.y1]
    return all(math.isfinite(v) for v in vals) and (r.x1 > r.x0) and (r.y1 > r.y0)

def _ensure_min_size(
    r: fitz.Rect,
    pr: fitz.Rect,
    min_w: float = 55.0,
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

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

def _dist(a: fitz.Point, b: fitz.Point) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)

# ============================================================
# ZONES + BEST-OCCURRENCE SCORING (NEW)
# ============================================================

def _zones(page: fitz.Page) -> Tuple[fitz.Rect, fitz.Rect]:
    pr = page.rect
    header = fitz.Rect(0, 0, pr.width, pr.height * 0.18)
    footer = fitz.Rect(0, pr.height * 0.86, pr.width, pr.height)
    return header, footer

def _score_hit(page: fitz.Page, r: fitz.Rect, kind: str) -> float:
    """
    Higher = better.
    kind: "url" | "entity" | "date" | "generic"
    """
    header, footer = _zones(page)
    footer_no_go = (fitz.Rect(NO_GO_RECT) & page.rect)
    c = _center(r)

    score = 0.0

    # Strong preference for header occurrences (matches your manual behavior)
    if header.intersects(r):
        score += 120.0
        # extra boost if nearer the very top
        score += 30.0 * (1.0 - (c.y / max(1.0, header.y1)))

    # Strong penalty for footer / print URL area
    if footer.intersects(r) or (footer_no_go.width > 0 and footer_no_go.height > 0 and footer_no_go.intersects(r)):
        score -= 250.0

    # Mild preference for earlier occurrence
    score += max(0.0, 25.0 - (c.y / page.rect.height) * 25.0)

    # Kind-specific tuning
    if kind == "url":
        score += 20.0
    elif kind in ("entity", "date"):
        score += 10.0

    return score

def _pick_best_rect(page: fitz.Page, rects: List[fitz.Rect], kind: str) -> Optional[fitz.Rect]:
    rects = _dedupe_rects(rects)
    if not rects:
        return None
    return max(rects, key=lambda r: _score_hit(page, r, kind))

# ============================================================
# Text area detection (dynamic margins)
# ============================================================

def _get_fallback_text_area(page: fitz.Page) -> fitz.Rect:
    pr = page.rect
    return fitz.Rect(pr.width * 0.12, pr.height * 0.12, pr.width * 0.88, pr.height * 0.88)

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
# Text wrapping + textbox insertion
# ============================================================

def _optimize_layout_for_margin(text: str, box_width: float) -> Tuple[int, str, float, float]:
    text = (text or "").strip()
    if not text:
        return 11, "", box_width, 24.0

    words = text.split()
    max_h = 240.0

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
            rr, text, fontname=fontname, fontsize=fsize, color=color, align=align, overlay=overlay
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
# URL helpers
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

def _url_variants_from_meta(meta: Dict[str, Any]) -> List[str]:
    """
    Build a robust set of URL needles that can match header (scheme-less)
    and footer (https://...) representations.
    """
    cands: List[str] = []
    for k in ("source_url_display", "source_url_canonical", "source_url"):
        v = (meta.get(k) or "").strip()
        if v:
            cands.append(v)

    out: List[str] = []
    seen = set()

    def add(x: str):
        x = (x or "").strip()
        if not x:
            return
        if x not in seen:
            seen.add(x)
            out.append(x)

    for u in cands:
        add(u)
        nu = _normalize_urlish(u)  # domain/path
        add(nu)
        add("https://" + nu)
        add("http://" + nu)
        add("www." + nu)
        add("https://www." + nu)
        add("http://www." + nu)

    return out

# ============================================================
# Keep-out detection (content blocks)
# ============================================================

def _get_keepouts(page: fitz.Page) -> List[fitz.Rect]:
    keepouts: List[fitz.Rect] = []

    try:
        for b in (page.get_text("blocks") or []):
            x0, y0, x1, y1 = b[:4]
            r = fitz.Rect(x0, y0, x1, y1)
            if _rect_is_valid(r) and _rect_area(r) > 50:
                keepouts.append(r)
    except Exception:
        pass

    try:
        for img in page.get_images(full=True) or []:
            xref = img[0]
            try:
                r = page.get_image_bbox(xref)
                if r and _rect_is_valid(r) and _rect_area(r) > 50:
                    keepouts.append(fitz.Rect(r))
            except Exception:
                continue
    except Exception:
        pass

    keepouts = _dedupe_rects(keepouts, pad=0.5)
    keepouts = [inflate_rect(r, 1.5) for r in keepouts]
    return keepouts

# ============================================================
# Margin lanes
# ============================================================

def _compute_equal_margins(page: fitz.Page) -> Tuple[fitz.Rect, fitz.Rect, fitz.Rect]:
    pr = page.rect
    text_area = _detect_actual_text_area(page)

    left_available = max(0.0, text_area.x0 - EDGE_PAD)
    right_available = max(0.0, (pr.width - EDGE_PAD) - text_area.x1)
    lane_w = max(0.0, min(left_available, right_available))
    lane_w = max(lane_w, 60.0)

    left_lane = fitz.Rect(EDGE_PAD, EDGE_PAD, EDGE_PAD + lane_w, pr.height - EDGE_PAD)
    right_lane = fitz.Rect(pr.width - EDGE_PAD - lane_w, EDGE_PAD, pr.width - EDGE_PAD, pr.height - EDGE_PAD)
    return text_area, left_lane, right_lane

def _rect_conflicts(r: fitz.Rect, occupied: List[fitz.Rect], pad: float = 0.0) -> bool:
    rr = inflate_rect(r, pad) if pad else r
    return any(rr.intersects(o) for o in occupied)

# ============================================================
# Leader routing + intersection scoring
# ============================================================

def _segment_intersects_rect(p0: fitz.Point, p1: fitz.Point, r: fitz.Rect) -> bool:
    seg_bb = fitz.Rect(min(p0.x, p1.x), min(p0.y, p1.y), max(p0.x, p1.x), max(p0.y, p1.y))
    if not seg_bb.intersects(r):
        return False

    steps = 12
    for i in range(steps + 1):
        t = i / steps
        x = p0.x + (p1.x - p0.x) * t
        y = p0.y + (p1.y - p0.y) * t
        if r.contains(fitz.Point(x, y)):
            return True
    return False

def _count_path_crossings(points: List[fitz.Point], keepouts: List[fitz.Rect]) -> int:
    if len(points) < 2:
        return 0
    crosses = 0
    for i in range(len(points) - 1):
        a, b = points[i], points[i + 1]
        for r in keepouts:
            if _segment_intersects_rect(a, b, r):
                crosses += 1
    return crosses

def _nearest_point_on_rect_edge(from_pt: fitz.Point, r: fitz.Rect) -> fitz.Point:
    x = _clamp(from_pt.x, r.x0, r.x1)
    y = _clamp(from_pt.y, r.y0, r.y1)
    d_left = abs(x - r.x0)
    d_right = abs(r.x1 - x)
    d_top = abs(y - r.y0)
    d_bot = abs(r.y1 - y)
    m = min(d_left, d_right, d_top, d_bot)
    if m == d_left:
        return fitz.Point(r.x0, y)
    if m == d_right:
        return fitz.Point(r.x1, y)
    if m == d_top:
        return fitz.Point(x, r.y0)
    return fitz.Point(x, r.y1)

def _route_margin_first(
    note_rect: fitz.Rect,
    anchor_rect: fitz.Rect,
    side: str,
    page_rect: fitz.Rect,
) -> List[fitz.Point]:
    note_c = _center(note_rect)
    anchor_c = _center(anchor_rect)

    start = _nearest_point_on_rect_edge(anchor_c, note_rect)
    end = _nearest_point_on_rect_edge(note_c, anchor_rect)

    if side == "left":
        gutter_x = min(note_rect.x1 + 6.0, page_rect.width * 0.22)
        gutter_x = max(gutter_x, note_rect.x1 + 4.0)
    else:
        gutter_x = max(note_rect.x0 - 6.0, page_rect.width * 0.78)
        gutter_x = min(gutter_x, note_rect.x0 - 4.0)

    waypoint = fitz.Point(gutter_x, end.y)
    return [start, waypoint, end]

def _draw_arrowhead(page: fitz.Page, tail: fitz.Point, tip: fitz.Point, color=RED):
    dx = tip.x - tail.x
    dy = tip.y - tail.y
    ang = math.atan2(dy, dx)
    a = math.radians(ARROW_ANGLE_DEG)

    p1 = fitz.Point(
        tip.x - ARROW_LEN * math.cos(ang - a),
        tip.y - ARROW_LEN * math.sin(ang - a),
    )
    p2 = fitz.Point(
        tip.x - ARROW_LEN * math.cos(ang + a),
        tip.y - ARROW_LEN * math.sin(ang + a),
    )

    page.draw_line(p1, tip, color=color, width=LEADER_WIDTH)
    page.draw_line(p2, tip, color=color, width=LEADER_WIDTH)

# ============================================================
# Callout placement (cost-based)
# ============================================================

@dataclass
class CalloutPlan:
    label: str
    wrapped_text: str
    fontsize: int
    note_rect: fitz.Rect
    anchor_rect: fitz.Rect
    side: str
    leader_points: List[fitz.Point]

def _build_note_rect_in_lane(
    lane: fitz.Rect,
    page_rect: fitz.Rect,
    label: str,
    anchor_y: float,
) -> Tuple[fitz.Rect, str, int]:
    lane_w = lane.x1 - lane.x0
    max_w = min(180.0, lane_w - 8.0)
    max_w = max(max_w, 70.0)

    fs, wrapped, w_used, h_needed = _optimize_layout_for_margin(label, max_w)
    w_used = min(w_used, max_w)

    x0 = lane.x0 + 4.0
    x1 = min(lane.x1 - 4.0, x0 + w_used)

    y0 = anchor_y - h_needed / 2.0
    y1 = anchor_y + h_needed / 2.0
    y0 = _clamp(y0, lane.y0, lane.y1 - h_needed)
    y1 = y0 + h_needed

    rect = fitz.Rect(x0, y0, x1, y1)
    rect = _ensure_min_size(rect, page_rect, min_w=55.0, min_h=14.0)
    return rect, wrapped, fs

def _push_to_avoid(rect: fitz.Rect, occupied: List[fitz.Rect], lane: fitz.Rect) -> fitz.Rect:
    if not occupied:
        return rect

    r = fitz.Rect(rect)

    def collides(rr: fitz.Rect) -> bool:
        return _rect_conflicts(rr, occupied, pad=GAP_BETWEEN_CALLOUTS)

    step = 8.0
    for _ in range(60):
        if not collides(r):
            return r
        r = fitz.Rect(r.x0, r.y0 + step, r.x1, r.y1 + step)
        if r.y1 > lane.y1:
            break

    r = fitz.Rect(rect)
    for _ in range(60):
        if not collides(r):
            return r
        r = fitz.Rect(r.x0, r.y0 - step, r.x1, r.y1 - step)
        if r.y0 < lane.y0:
            break

    return fitz.Rect(rect)

def _choose_anchor_rect(rects: List[fitz.Rect]) -> fitz.Rect:
    """
    Choose ONE anchor rect from a cluster.
    Default: rect closest to cluster centroid.
    """
    rects = _dedupe_rects(rects)
    if not rects:
        return fitz.Rect(0, 0, 0, 0)
    centroid = _center(_union_rect(rects))
    best = min(rects, key=lambda r: _dist(_center(r), centroid))
    return fitz.Rect(best)

def _placement_score(
    note_rect: fitz.Rect,
    anchor_rect: fitz.Rect,
    leader_points: List[fitz.Point],
    keepouts: List[fitz.Rect],
    occupied: List[fitz.Rect],
    footer_no_go: fitz.Rect,
) -> float:
    note_c = _center(note_rect)
    anch_c = _center(anchor_rect)

    dist_cost = _dist(note_c, anch_c)
    cross_cost = _count_path_crossings(leader_points, keepouts)
    shift_cost = abs(note_c.y - anch_c.y)
    overlap_cost = 1.0 if _rect_conflicts(note_rect, occupied, pad=GAP_BETWEEN_CALLOUTS) else 0.0
    footer_cost = 1.0 if (footer_no_go.width > 0 and footer_no_go.height > 0 and note_rect.intersects(footer_no_go)) else 0.0

    return (
        W_DIST * dist_cost
        + W_CROSS * cross_cost
        + W_SHIFT * shift_cost
        + W_OVERLAP * overlap_cost
        + W_FOOTER * footer_cost
    )

def _plan_callout_cost_based(
    page: fitz.Page,
    text_area: fitz.Rect,
    left_lane: fitz.Rect,
    right_lane: fitz.Rect,
    keepouts: List[fitz.Rect],
    occupied_left: List[fitz.Rect],
    occupied_right: List[fitz.Rect],
    label: str,
    target_rects_on_page1: List[fitz.Rect],
    preferred_side: Optional[str] = None,
) -> Optional[CalloutPlan]:
    pr = page.rect
    footer_no_go = fitz.Rect(NO_GO_RECT) & pr

    rects = _dedupe_rects(target_rects_on_page1)
    if not rects:
        return None

    target_union = _union_rect(rects)
    target_no_go = inflate_rect(target_union, GAP_FROM_HIGHLIGHTS)

    anchor_rect = _choose_anchor_rect(rects)
    anchor_y = _center(anchor_rect).y

    def candidate(side: str) -> Optional[CalloutPlan]:
        lane = left_lane if side == "left" else right_lane
        occ = occupied_left if side == "left" else occupied_right

        note_rect, wrapped, fs = _build_note_rect_in_lane(lane, pr, label, anchor_y)
        note_rect = _push_to_avoid(note_rect, occ, lane)

        if note_rect.intersects(text_area):
            return None
        if note_rect.intersects(target_no_go):
            return None
        if not lane.contains(note_rect):
            return None

        leader = _route_margin_first(note_rect, anchor_rect, side, pr)
        return CalloutPlan(
            label=label,
            wrapped_text=wrapped,
            fontsize=fs,
            note_rect=note_rect,
            anchor_rect=anchor_rect,
            side=side,
            leader_points=leader,
        )

    candidates: List[CalloutPlan] = []
    for side in ("left", "right"):
        c = candidate(side)
        if c:
            candidates.append(c)

    if not candidates:
        return None

    scored: List[Tuple[float, CalloutPlan]] = []
    for c in candidates:
        occ = occupied_left if c.side == "left" else occupied_right
        s = _placement_score(c.note_rect, c.anchor_rect, c.leader_points, keepouts, occ, footer_no_go)
        if preferred_side and c.side == preferred_side:
            s *= 0.92
        scored.append((s, c))

    scored.sort(key=lambda x: x[0])
    best = scored[0][1]

    if best.side == "left":
        occupied_left.append(best.note_rect)
    else:
        occupied_right.append(best.note_rect)

    return best

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
    out: List[str] = []
    seen = set()
    for t in tokens:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out

# ============================================================
# Main entrypoint (connector-free)
# ============================================================

def annotate_pdf_bytes(
    pdf_bytes: bytes,
    quote_terms: List[str],
    criterion_id: str,
    meta: Dict[str, Any],
    *,
    preferred_side_by_label: Optional[Dict[str, str]] = None,
) -> Tuple[bytes, Dict[str, Any]]:
    """
    Pipeline:
      1) Draw red rectangles around hits (quotes/meta/stars).
      2) On page 1: place margin callouts in left/right lanes via cost scoring.
      3) Draw callouts (white box + red text) AND leader lines with arrowheads to an anchor highlight.

    Changes in this version:
      - URL: uses variants + BEST-OCCURRENCE scoring (header preferred, footer avoided).
      - Venue/Ensemble/Date: picks BEST occurrence on page 1 (boxes once).
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if len(doc) == 0:
        return pdf_bytes, {}

    page1 = doc.load_page(0)

    total_quote_hits = 0
    total_meta_hits = 0

    text_area, left_lane, right_lane = _compute_equal_margins(page1)
    keepouts_p1 = _get_keepouts(page1)

    occupied_left: List[fitz.Rect] = []
    occupied_right: List[fitz.Rect] = []
    plans: List[CalloutPlan] = []

    # ------------------------------------------------------------
    # 1) Quote highlights (UNCHANGED)
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
    # 2) Metadata highlighting + callouts
    # ------------------------------------------------------------

    def _do_job(
        label: str,
        value: Optional[str],
        variants: Optional[List[str]] = None,
        *,
        kind: str = "generic",
        single_best: bool = True,
        page1_only: bool = True,
    ):
        """
        single_best=True:
          - boxes only the best occurrence on page 1
          - callout anchored to that occurrence
        """
        nonlocal total_meta_hits, plans

        val_str = str(value or "").strip()
        if not val_str:
            return

        needles = list(dict.fromkeys([val_str] + (variants or [])))

        # Collect rects on page 1 only (matches your manual behavior)
        rects_p1: List[fitz.Rect] = []
        for n in needles:
            rects_p1.extend(_search_term(page1, n))

        rects_p1 = _dedupe_rects(rects_p1)
        if not rects_p1:
            return

        if single_best:
            best = _pick_best_rect(page1, rects_p1, kind=kind)  # header preferred, footer avoided
            if not best:
                return
            # Draw ONE box
            page1.draw_rect(best, color=RED, width=BOX_WIDTH)
            total_meta_hits += 1
            anchor_rects = [best]
        else:
            # Draw all (rarely desired for your workflow)
            for r in rects_p1:
                page1.draw_rect(r, color=RED, width=BOX_WIDTH)
                total_meta_hits += 1
            anchor_rects = rects_p1

        preferred = preferred_side_by_label.get(label) if preferred_side_by_label else None

        plan = _plan_callout_cost_based(
            page1,
            text_area=text_area,
            left_lane=left_lane,
            right_lane=right_lane,
            keepouts=keepouts_p1,
            occupied_left=occupied_left,
            occupied_right=occupied_right,
            label=label,
            target_rects_on_page1=anchor_rects,  # anchor(s)
            preferred_side=preferred,
        )
        if plan:
            plans.append(plan)

    # --- URL: use variants and best-occurrence scoring ---
    _do_job(
        "Original source of publication.",
        meta.get("source_url"),
        variants=_url_variants_from_meta(meta),
        kind="url",
        single_best=True,
        page1_only=True,
    )

    # --- Venue/Ensemble/Date: box once (best occurrence) ---
    _do_job(
        "Venue is distinguished organization.",
        meta.get("venue_name"),
        kind="entity",
        single_best=True,
        page1_only=True,
    )
    _do_job(
        "Ensemble is distinguished organization.",
        meta.get("ensemble_name"),
        kind="entity",
        single_best=True,
        page1_only=True,
    )
    _do_job(
        "Performance date.",
        meta.get("performance_date"),
        kind="date",
        single_best=True,
        page1_only=True,
    )

    # Beneficiary: often you *do* want multiple variants; still choose best occurrence for the callout anchor
    _do_job(
        "Beneficiary lead role evidence.",
        meta.get("beneficiary_name"),
        variants=meta.get("beneficiary_variants"),
        kind="entity",
        single_best=True,
        page1_only=True,
    )

    # ------------------------------------------------------------
    # 3) Stars (optional criterion) — choose best on page 1
    # ------------------------------------------------------------
    if criterion_id in _STAR_CRITERIA:
        stars_rects_p1: List[fitz.Rect] = []
        for tok in _find_high_star_tokens(page1):
            stars_rects_p1.extend(page1.search_for(tok) or [])

        stars_rects_p1 = _dedupe_rects(stars_rects_p1)
        if stars_rects_p1:
            best = _pick_best_rect(page1, stars_rects_p1, kind="generic")
            if best:
                page1.draw_rect(best, color=RED, width=BOX_WIDTH)
                total_quote_hits += 1

                label = "Highly acclaimed review of the distinguished performance."
                preferred = preferred_side_by_label.get(label) if preferred_side_by_label else None
                plan = _plan_callout_cost_based(
                    page1,
                    text_area=text_area,
                    left_lane=left_lane,
                    right_lane=right_lane,
                    keepouts=keepouts_p1,
                    occupied_left=occupied_left,
                    occupied_right=occupied_right,
                    label=label,
                    target_rects_on_page1=[best],
                    preferred_side=preferred,
                )
                if plan:
                    plans.append(plan)

    # ------------------------------------------------------------
    # 4) Draw callouts + leaders last (arrows are already drawn here)
    # ------------------------------------------------------------
    for plan in plans:
        page1.draw_rect(plan.note_rect, color=WHITE, fill=WHITE, overlay=True)

        _insert_textbox_fit(
            page1,
            plan.note_rect,
            plan.wrapped_text,
            fontname=FONTNAME,
            fontsize=plan.fontsize,
            color=RED,
            overlay=True,
        )

        pts = plan.leader_points
        for i in range(len(pts) - 1):
            page1.draw_line(pts[i], pts[i + 1], color=RED, width=LEADER_WIDTH)

        if len(pts) >= 2:
            _draw_arrowhead(page1, pts[-2], pts[-1], color=RED)

    out = io.BytesIO()
    doc.save(out)
    doc.close()
    out.seek(0)

    return out.getvalue(), {
        "total_quote_hits": total_quote_hits,
        "total_meta_hits": total_meta_hits,
        "criterion_id": criterion_id,
        "callouts_drawn": len(plans),
    }
