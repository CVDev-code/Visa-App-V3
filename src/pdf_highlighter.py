import io
import math
import re
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
GAP_BETWEEN_CALLOUTS = 8.0
ENDPOINT_PULLBACK = 1.5

# Arrowhead
ARROW_LEN = 9.0
ARROW_HALF_WIDTH = 4.5

# For quote search robustness
_MAX_TERM = 600
_CHUNK = 60
_CHUNK_OVERLAP = 18


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
        return r, -1.0, fs

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
        r = fitz.Rect(rect)
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
# De-duplication for overlapping/nested hits
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
# URL helpers (used to restrict URL boxing to page 1)
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
# Arrow drawing (tip ends at end-point)
# ============================================================

def _draw_arrowhead(page: fitz.Page, start: fitz.Point, end: fitz.Point):
    vx = end.x - start.x
    vy = end.y - start.y
    d = math.hypot(vx, vy)
    if d == 0:
        return

    ux, uy = vx / d, vy / d  # direction

    # base center is behind tip
    bx = end.x - ux * ARROW_LEN
    by = end.y - uy * ARROW_LEN

    # perpendicular
    px = -uy
    py = ux

    p1 = fitz.Point(bx + px * ARROW_HALF_WIDTH, by + py * ARROW_HALF_WIDTH)
    p2 = fitz.Point(bx - px * ARROW_HALF_WIDTH, by - py * ARROW_HALF_WIDTH)
    tip = fitz.Point(end.x, end.y)

    page.draw_polyline([p1, tip, p2, p1], color=RED, fill=RED, width=0.0)


def _draw_line(page: fitz.Page, a: fitz.Point, b: fitz.Point):
    page.draw_line(a, b, color=RED, width=LINE_WIDTH)


# ============================================================
# Connector endpoints (edge-to-edge with pullback)
# ============================================================

def _edge_to_edge_points(callout_rect: fitz.Rect, target_rect: fitz.Rect) -> Tuple[fitz.Point, fitz.Point]:
    """
    Calculates the shortest line between the callout box and the target box.
    FIX: Logic simplfied to avoid lines erroneously drawing to page corner (0,0).
    """
    # 1. Determine relative position
    # callout is to the RIGHT of target (target < callout)
    if callout_rect.x0 >= target_rect.x1:
        start_x = callout_rect.x0
        end_x = target_rect.x1
    # callout is to the LEFT of target (callout < target)
    elif callout_rect.x1 <= target_rect.x0:
        start_x = callout_rect.x1
        end_x = target_rect.x0
    else:
        # Overlapping horizontally? Pick centers or nearest edges
        cc = _center(callout_rect)
        tc = _center(target_rect)
        if cc.x > tc.x:
            start_x = callout_rect.x0
            end_x = target_rect.x1
        else:
            start_x = callout_rect.x1
            end_x = target_rect.x0

    # 2. Determine Y coordinates (clamp to the overlap of Y ranges)
    # Find the vertical overlap range
    overlap_y0 = max(callout_rect.y0, target_rect.y0)
    overlap_y1 = min(callout_rect.y1, target_rect.y1)

    if overlap_y1 > overlap_y0:
        # Boxes overlap vertically; draw straight horizontal line in the middle of overlap
        mid_y = (overlap_y0 + overlap_y1) / 2
        start_y = mid_y
        end_y = mid_y
    else:
        # No vertical overlap; draw from center-y to center-y (or clamp to edges)
        cc = _center(callout_rect)
        tc = _center(target_rect)
        
        # Clamp start_y to callout vertical range
        start_y = min(max(tc.y, callout_rect.y0 + 1), callout_rect.y1 - 1)
        # Clamp end_y to target vertical range
        end_y = min(max(start_y, target_rect.y0 + 1), target_rect.y1 - 1)

    start = fitz.Point(start_x, start_y)
    end_raw = fitz.Point(end_x, end_y)

    # 3. Apply Pullback from the target (so arrow doesn't bury in the box)
    end = _pull_back_point(start, end_raw, ENDPOINT_PULLBACK)

    return start, end


# ============================================================
# Multi-page routing: down the page margin(s) until target page
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

    # Page 1: from callout edge -> gutter at same y, then down to bottom
    s, _ = _edge_to_edge_points(callout_rect, target_rect)

    y_start = min(max(s.y, EDGE_PAD), pr.height - EDGE_PAD)
    p_gutter_start = fitz.Point(gutter_x, y_start)
    p_gutter_bottom = fitz.Point(gutter_x, pr.height - EDGE_PAD)

    _draw_line(callout_page, s, p_gutter_start)
    _draw_line(callout_page, p_gutter_start, p_gutter_bottom)

    # Intermediate pages: vertical gutter line top->bottom
    for pi in range(callout_page_index + 1, target_page_index):
        p = doc.load_page(pi)
        pr_i = p.rect
        gx = pr_i.width - EDGE_PAD if gutter_side == "right" else EDGE_PAD
        _draw_line(p, fitz.Point(gx, EDGE_PAD), fitz.Point(gx, pr_i.height - EDGE_PAD))

    # Target page: gutter top -> target_y, then across to target edge, arrowhead at end
    tp = doc.load_page(target_page_index)
    pr_t = tp.rect
    gx_t = pr_t.width - EDGE_PAD if gutter_side == "right" else EDGE_PAD

    tc = _center(target_rect)
    y_target = min(max(tc.y, EDGE_PAD), pr_t.height - EDGE_PAD)

    p_top = fitz.Point(gx_t, EDGE_PAD)
    p_mid = fitz.Point(gx_t, y_target)

    faux_start = fitz.Point(gx_t, y_target)
    if gutter_side == "right":
        end_raw = fitz.Point(target_rect.x1, min(max(y_target, target_rect.y0 + 1.0), target_rect.y1 - 1.0))
    else:
        end_raw = fitz.Point(target_rect.x0, min(max(y_target, target_rect.y0 + 1.0), target_rect.y1 - 1.0))

    end = _pull_back_point(faux_start, end_raw, ENDPOINT_PULLBACK)

    _draw_line(tp, p_top, p_mid)
    _draw_line(tp, p_mid, end)
    _draw_arrowhead(tp, p_mid, end)


# ============================================================
# Margin placement (first-page callouts)
# ============================================================

def _place_annotation_in_margin(
    page: fitz.Page,
    targets: List[fitz.Rect],
    occupied_callouts: List[fitz.Rect],
    label: str,
) -> Tuple[fitz.Rect, str, int, bool]:
    text_area = _detect_actual_text_area(page)
    pr = page.rect
    target_union = _union_rect(targets)
    target_c = _center(target_union)
    target_y = target_c.y

    target_no_go = inflate_rect(target_union, GAP_FROM_HIGHLIGHTS)
    footer_no_go = fitz.Rect(NO_GO_RECT) & pr

    MIN_CALLOUT_WIDTH = 55.0
    MAX_CALLOUT_WIDTH = 180.0
    EDGE_BUFFER = 8.0
    MIN_H = 12.0

    left_lane = (EDGE_BUFFER, max(EDGE_BUFFER, text_area.x0 - EDGE_BUFFER))
    right_lane = (min(pr.width - EDGE_BUFFER, text_area.x1 + EDGE_BUFFER), pr.width - EDGE_BUFFER)

    lanes = []
    lw = left_lane[1] - left_lane[0]
    rw = right_lane[1] - right_lane[0]
    if lw >= MIN_CALLOUT_WIDTH:
        lanes.append(("left", left_lane[0], left_lane[1], lw))
    if rw >= MIN_CALLOUT_WIDTH:
        lanes.append(("right", right_lane[0], right_lane[1], rw))

    if not lanes:
        fallback = fitz.Rect(
            EDGE_BUFFER,
            max(EDGE_BUFFER, target_y - 20),
            EDGE_BUFFER + 120,
            min(pr.height - EDGE_BUFFER, target_y + 20),
        )
        return _ensure_min_size(fallback, pr), label, 8, False

    page_mid_x = pr.width / 2.0
    target_side_pref = "left" if target_c.x < page_mid_x else "right"
    lanes.sort(key=lambda t: 0 if t[0] == target_side_pref else 1)

    occupied_buf = [inflate_rect(o, GAP_BETWEEN_CALLOUTS) for o in occupied_callouts]
    scan = [12, -12, 24, -24, 36, -36, 48, -48, 60, -60, 72, -72, 0]

    best = None  # (score, rect, wrapped, fs, safe)

    for side, x0_lane, x1_lane, lane_w in lanes:
        usable_w = min(MAX_CALLOUT_WIDTH, lane_w)
        fs, wrapped_text, w_used, h_needed = _optimize_layout_for_margin(label, usable_w)
        w_used = min(w_used, usable_w)
        if w_used < MIN_CALLOUT_WIDTH:
            continue

        for dy in scan:
            y0 = target_y + dy - h_needed / 2.0
            y1 = target_y + dy + h_needed / 2.0

            y0 = max(EDGE_BUFFER, y0)
            y1 = min(pr.height - EDGE_BUFFER, y1)

            if (y1 - y0) < MIN_H:
                y1 = min(pr.height - EDGE_BUFFER, y0 + MIN_H)
                if (y1 - y0) < MIN_H:
                    y0 = max(EDGE_BUFFER, y1 - MIN_H)

            if side == "left":
                x1 = x1_lane - 5.0
                x0 = max(x0_lane, x1 - w_used)
            else:
                x0 = x0_lane + 5.0
                x1 = min(x1_lane, x0 + w_used)

            cand = fitz.Rect(x0, y0, x1, y1)
            cand = _ensure_min_size(cand, pr)

            if cand.intersects(target_no_go):
                continue
            if cand.intersects(text_area):
                continue
            if footer_no_go.width > 0 and footer_no_go.height > 0 and cand.intersects(footer_no_go):
                continue

            conflicts = any(cand.intersects(o) for o in occupied_buf)
            safe = not conflicts

            dx = abs(_center(cand).x - target_c.x)
            dy_zero_penalty = 5.0 if dy == 0 else 0.0
            score = (0 if safe else 10_000) + dx * 0.8 + abs(dy) * 0.15 + dy_zero_penalty

            if best is None or score < best[0]:
                best = (score, cand, wrapped_text, fs, safe)

            if safe and dy != 0:
                return cand, wrapped_text, fs, True

    if best:
        _, cand, wrapped_text, fs, safe = best
        return cand, wrapped_text, fs, safe

    # last resort fallback
    side, x0_lane, x1_lane, lane_w = lanes[0]
    usable_w = min(MAX_CALLOUT_WIDTH, lane_w)
    fs, wrapped_text, w_used, h_needed = _optimize_layout_for_margin(label, usable_w)
    w_used = min(w_used, usable_w)

    y0 = max(EDGE_BUFFER, target_y - h_needed / 2.0)
    y1 = min(pr.height - EDGE_BUFFER, target_y + h_needed / 2.0)
    if (y1 - y0) < MIN_H:
        y1 = min(pr.height - EDGE_BUFFER, y0 + MIN_H)

    if side == "left":
        x1 = x1_lane - 5.0
        x0 = max(x0_lane, x1 - w_used)
    else:
        x0 = x0_lane + 5.0
        x1 = min(x1_lane, x0 + w_used)

    cand = fitz.Rect(x0, y0, x1, y1)

    if footer_no_go.width > 0 and footer_no_go.height > 0 and cand.intersects(footer_no_go):
        shift = (cand.y1 - footer_no_go.y0) + EDGE_BUFFER
        cand = _shift_rect_up(cand, shift, min_y=EDGE_BUFFER)

    cand = _ensure_min_size(cand, pr)
    return cand, wrapped_text, fs, False


# ============================================================
# Stars helper - UPDATED REGEX
# ============================================================

_STAR_CRITERIA = {"3", "2_past", "4_past"}

def _find_high_star_tokens(page: fitz.Page) -> List[str]:
    text = page.get_text("text") or ""
    tokens: List[str] = []

    # Improved: Match 4 or 5 asterisks anywhere as a standalone token
    for m in re.finditer(r"(?<!\*)\*{4,5}(?!\*)", text):
        tokens.append(m.group(0))

    # Match Unicode stars (4 or 5 filled)
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
    occupied_callouts: List[fitz.Rect] = []
    connectors_to_draw: List[Dict[str, Any]] = []

    # 1. Highlights for quotes (restricting URLs to Page 1)
    meta_url = (meta.get("source_url") or "").strip()
    for page in doc:
        for term in (quote_terms or []):
            t = (term or "").strip()
            if not t:
                continue
                
            # strict url check: if it looks like a URL, only highlight on p1
            is_url_term = _looks_like_url(t) or (meta_url and _is_same_urlish(t, meta_url))
            if is_url_term and page.number != 0:
                continue

            rects = _search_term(page, t)
            for r in _dedupe_rects(rects):
                page.draw_rect(r, color=RED, width=BOX_WIDTH)
                total_quote_hits += 1

    # 2. Metadata logic
    # Define a helper to search pages for targets
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

    def _do_job(label: str, value: Optional[str], variants: List[str] = None):
        nonlocal total_meta_hits
        val_str = str(value or "").strip()
        if not val_str: return
        
        is_url = _looks_like_url(val_str) or (meta_url and _is_same_urlish(val_str, meta_url))
        indices = [0] if is_url else None
        
        targets_by_page = {}
        needles = list(dict.fromkeys([val_str] + (variants or [])))
        for n in needles:
            for pi, r in _find_targets_across_doc(n, page_indices=indices):
                targets_by_page.setdefault(pi, []).append(r)

        if not targets_by_page: return

        # Draw boxes
        for pi, rects in targets_by_page.items():
            # Extra safety: never box URLs on other pages
            if is_url and pi != 0: continue

            p = doc.load_page(pi)
            for r in _dedupe_rects(rects):
                p.draw_rect(r, color=RED, width=BOX_WIDTH)
                total_meta_hits += 1
        
        # If we found targets on page 1, use them for callout. Else pick first avail page.
        targets_for_callout_map = {}
        if is_url:
             if 0 in targets_by_page:
                 targets_for_callout_map = {0: targets_by_page[0]}
        else:
             targets_for_callout_map = targets_by_page

        if not targets_for_callout_map: return

        # Place Callout on Page 1
        if 0 in targets_for_callout_map:
            p_targets = targets_for_callout_map[0]
        else:
            first_pi = sorted(targets_for_callout_map.keys())[0]
            p_targets = targets_for_callout_map[first_pi]

        crect, wtext, fs, _ = _place_annotation_in_margin(page1, p_targets, occupied_callouts, label)
        
        # Footer shift
        footer_no_go = fitz.Rect(NO_GO_RECT) & page1.rect
        if footer_no_go.width > 0 and footer_no_go.height > 0 and crect.intersects(footer_no_go):
            shift = (crect.y1 - footer_no_go.y0) + EDGE_PAD
            crect = _shift_rect_up(crect, shift, min_y=EDGE_PAD)
        
        crect = _ensure_min_size(crect, page1.rect)
        if not _rect_is_valid(crect): return

        # Draw White Box and Text
        page1.draw_rect(crect, color=WHITE, fill=WHITE, overlay=True)
        final_r, _, _ = _insert_textbox_fit(page1, crect, wtext, fontname=FONTNAME, fontsize=fs, color=RED)
        occupied_callouts.append(final_r)
        
        # Add to connectors (using the restricted map for URLs)
        connectors_to_draw.append({"final_rect": final_r, "targets_by_page": targets_for_callout_map})

    # Execute Jobs
    _do_job("Original source of publication.", meta.get("source_url"))
    _do_job("Venue is distinguished organization.", meta.get("venue_name"))
    _do_job("Ensemble is distinguished organization.", meta.get("ensemble_name"))
    _do_job("Performance date.", meta.get("performance_date"))
    _do_job("Beneficiary lead role evidence.", meta.get("beneficiary_name"), meta.get("beneficiary_variants"))

    # 3. Stars Logic
    if criterion_id in _STAR_CRITERIA:
        stars_map = {}
        for p in doc:
            for tok in _find_high_star_tokens(p):
                found = p.search_for(tok)
                if found:
                    stars_map.setdefault(p.number, []).extend(found)
                    for r in _dedupe_rects(found):
                        p.draw_rect(r, color=RED, width=BOX_WIDTH)
                        total_quote_hits += 1 # Count stars as quote hits

        if stars_map:
            if 0 in stars_map:
                p_targets = stars_map[0]
            else:
                first_pi = sorted(stars_map.keys())[0]
                p_targets = stars_map[first_pi]

            crect, wtext, fs, _ = _place_annotation_in_margin(page1, p_targets, occupied_callouts, "Highly acclaimed review of the distinguished performance.")
            
            # Footer shift
            footer_no_go = fitz.Rect(NO_GO_RECT) & page1.rect
            if footer_no_go.width > 0 and footer_no_go.height > 0 and crect.intersects(footer_no_go):
                shift = (crect.y1 - footer_no_go.y0) + EDGE_PAD
                crect = _shift_rect_up(crect, shift, min_y=EDGE_PAD)
            
            crect = _ensure_min_size(crect, page1.rect)
            if _rect_is_valid(crect):
                page1.draw_rect(crect, color=WHITE, fill=WHITE, overlay=True)
                final_r, _, _ = _insert_textbox_fit(page1, crect, wtext, fontname=FONTNAME, fontsize=fs, color=RED)
                occupied_callouts.append(final_r)
                connectors_to_draw.append({"final_rect": final_r, "targets_by_page": stars_map})

    # 4. Draw Connectors
    for item in connectors_to_draw:
        fr = item["final_rect"]
        for pi, rects in item["targets_by_page"].items():
            for r in _dedupe_rects(rects):
                if pi == 0:
                    s, e = _edge_to_edge_points(fr, r)
                    _draw_line(page1, s, e)
                    _draw_arrowhead(page1, s, e)
                else:
                    _draw_multipage_connector(doc, 0, fr, pi, r)

    out = io.BytesIO()
    doc.save(out)
    doc.close()
    out.seek(0)
    return out.getvalue(), {"total_quote_hits": total_quote_hits, "total_meta_hits": total_meta_hits, "criterion_id": criterion_id}
