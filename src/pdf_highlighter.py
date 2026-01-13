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
FONT_SIZES = [11, 10, 9, 8]

# ---- footer no-go zone ----
NO_GO_RECT = fitz.Rect(21.00, 816.00, 411.26, 830.00)

# ---- spacing knobs ----
EDGE_PAD = 12.0
GAP_FROM_HIGHLIGHTS = 10.0
GAP_BETWEEN_CALLOUTS = 10.0
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

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

def _segment_hits_rect(p1: fitz.Point, p2: fitz.Point, r: fitz.Rect) -> bool:
    if r.contains(p1) or r.contains(p2):
        return True
    edges = [
        (fitz.Point(r.x0, r.y0), fitz.Point(r.x1, r.y0)),
        (fitz.Point(r.x1, r.y0), fitz.Point(r.x1, r.y1)),
        (fitz.Point(r.x1, r.y1), fitz.Point(r.x0, r.y1)),
        (fitz.Point(r.x0, r.y1), fitz.Point(r.x0, r.y0)),
    ]
    for e1, e2 in edges:
        if fitz.intersect_segments(p1, p2, e1, e2):
            return True
    return False

def _rect_is_valid(r: fitz.Rect) -> bool:
    vals = [r.x0, r.y0, r.x1, r.y1]
    return all(math.isfinite(v) for v in vals) and (r.x1 > r.x0) and (r.y1 > r.y0)

def _ensure_min_size(r: fitz.Rect, pr: fitz.Rect, min_w: float = 55.0, min_h: float = 14.0, pad: float = 2.0) -> fitz.Rect:
    rr = fitz.Rect(r)
    cx, cy = (rr.x0 + rr.x1) / 2.0, (rr.y0 + rr.y1) / 2.0
    w, h = max(min_w, abs(rr.x1 - rr.x0)), max(min_h, abs(rr.y1 - rr.y0))
    rr = fitz.Rect(cx - w / 2.0, cy - h / 2.0, cx + w / 2.0, cy + h / 2.0)
    rr.x0, rr.y0 = max(pad, rr.x0), max(pad, rr.y0)
    rr.x1, rr.y1 = min(pr.width - pad, rr.x1), min(pr.height - pad, rr.y1)
    return rr if _rect_is_valid(rr) else fitz.Rect(pad, pad, pad + min_w, pad + min_h)

# ============================================================
# Text area detection
# ============================================================

def _get_fallback_text_area(page: fitz.Page) -> fitz.Rect:
    pr = page.rect
    return fitz.Rect(pr.width * 0.12, pr.height * 0.12, pr.width * 0.88, pr.height * 0.88)

def _detect_actual_text_area(page: fitz.Page) -> fitz.Rect:
    try:
        words = page.get_text("words") or []
        if not words: return _get_fallback_text_area(page)
        pr = page.rect
        header_limit, footer_limit = pr.height * 0.12, pr.height * 0.88
        x0s, x1s = [], []
        for w in words:
            if w[1] > header_limit and w[3] < footer_limit and len(w[4].strip()) > 1:
                x0s.append(w[0]); x1s.append(w[2])
        if not x0s: return _get_fallback_text_area(page)
        x0s.sort(); x1s.sort()
        text_left = max(pr.width * 0.08, x0s[int(len(x0s) * 0.05)])
        text_right = min(pr.width * 0.92, x1s[int(len(x1s) * 0.95)])
        return fitz.Rect(text_left, header_limit, text_right, footer_limit)
    except: return _get_fallback_text_area(page)

# ============================================================
# Text wrapping + textbox insertion
# ============================================================

def _optimize_layout_for_margin(text: str, box_width: float) -> Tuple[int, str, float, float]:
    text = (text or "").strip()
    if not text: return 11, "", box_width, 24.0
    words = text.split()
    for fs in FONT_SIZES:
        usable_w = max(30.0, box_width - 10.0)
        lines, cur = [], ""
        for w in words:
            trial = (cur + " " + w).strip() if cur else w
            if fitz.get_text_length(trial, fontname=FONTNAME, fontsize=fs) <= usable_w: cur = trial
            else:
                if cur: lines.append(cur)
                cur = w
        if cur: lines.append(cur)
        h = (len(lines) * fs * 1.25) + 10.0
        if h <= 220.0 or fs == FONT_SIZES[-1]: return fs, "\n".join(lines), box_width, h
    return FONT_SIZES[-1], text, box_width, 50.0

def _insert_textbox_fit(page: fitz.Page, rect: fitz.Rect, text: str, **kwargs) -> Tuple[fitz.Rect, float, int]:
    pr = page.rect
    r = _ensure_min_size(fitz.Rect(rect), pr)
    fs = int(kwargs.get("fontsize", 11))
    ret = page.insert_textbox(r, text, align=kwargs.get("align", 0), fontname=kwargs.get("fontname", FONTNAME), fontsize=fs, color=kwargs.get("color", RED))
    return r, ret, fs

# ============================================================
# De-duplication
# ============================================================

def _rect_area(r: fitz.Rect) -> float:
    return max(0.0, (r.x1 - r.x0) * (r.y1 - r.y0))

def _dedupe_rects(rects: List[fitz.Rect], pad: float = 1.0) -> List[fitz.Rect]:
    if not rects: return []
    rr = sorted([fitz.Rect(r) for r in rects], key=_rect_area, reverse=True)
    kept = []
    for r in rr:
        if not any(inflate_rect(k, pad).contains(inflate_rect(r, pad)) for k in kept):
            kept.append(r)
    return sorted(kept, key=lambda r: (r.y0, r.x0))

# ============================================================
# Search and URL helpers
# ============================================================

def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "")).strip()

def _search_term(page: fitz.Page, term: str) -> List[fitz.Rect]:
    t = _normalize_spaces(term)
    if not t: return []
    hits = page.search_for(t)
    if not hits and len(t) > _CHUNK:
        # Simple chunking if exact fails
        hits = page.search_for(t[:_CHUNK])
    return hits

def _looks_like_url(s: str) -> bool:
    s = (s or "").strip().lower()
    return any(s.startswith(x) for x in ["http://", "https://", "www."])

def _is_same_urlish(a: str, b: str) -> bool:
    def clean(s): return re.sub(r"^https?://|www\.", "", (s or "").strip().lower()).rstrip("/")
    return clean(a) == clean(b) if a and b else False

# ============================================================
# Drawing
# ============================================================

def _draw_arrowhead(page: fitz.Page, start: fitz.Point, end: fitz.Point):
    vx, vy = end.x - start.x, end.y - start.y
    d = math.hypot(vx, vy)
    if d == 0: return
    ux, uy = vx / d, vy / d
    bx, by = end.x - ux * ARROW_LEN, end.y - uy * ARROW_LEN
    p1 = fitz.Point(bx - uy * ARROW_HALF_WIDTH, by + ux * ARROW_HALF_WIDTH)
    p2 = fitz.Point(bx + uy * ARROW_HALF_WIDTH, by - ux * ARROW_HALF_WIDTH)
    page.draw_polyline([p1, end, p2, p1], color=RED, fill=RED, width=0.0)

def _draw_line(page: fitz.Page, a: fitz.Point, b: fitz.Point):
    page.draw_line(a, b, color=RED, width=LINE_WIDTH)

def _draw_poly_connector(page: fitz.Page, pts: List[fitz.Point]):
    if len(pts) < 2: return
    for a, b in zip(pts, pts[1:]): _draw_line(page, a, b)
    _draw_arrowhead(page, pts[-2], pts[-1])

# ============================================================
# Placement logic
# ============================================================

def _compute_equal_margins(page: fitz.Page) -> Tuple[fitz.Rect, fitz.Rect, fitz.Rect]:
    pr, text_area = page.rect, _detect_actual_text_area(page)
    lane_w = max(60.0, min(text_area.x0 - EDGE_PAD, (pr.width - EDGE_PAD) - text_area.x1))
    return text_area, fitz.Rect(EDGE_PAD, EDGE_PAD, EDGE_PAD + lane_w, pr.height - EDGE_PAD), \
           fitz.Rect(pr.width - EDGE_PAD - lane_w, EDGE_PAD, pr.width - EDGE_PAD, pr.height - EDGE_PAD)

def _place_callout_in_lane(page, lane, text_area, target_union, occupied, label):
    pr = page.rect
    fs, wrapped, w_used, h_needed = _optimize_layout_for_margin(label, lane.width - 8)
    target_y = _center(target_union).y
    
    for dy in [0, 25, -25, 50, -50, 75, -75, 100, -100]:
        cy = _clamp(target_y + dy, lane.y0 + h_needed/2, lane.y1 - h_needed/2)
        cand = fitz.Rect(lane.x0 + 4, cy - h_needed/2, lane.x0 + 4 + w_used, cy + h_needed/2)
        if not any(inflate_rect(cand, GAP_BETWEEN_CALLOUTS).intersects(o) for o in occupied):
            return cand, wrapped, fs
    return fitz.Rect(lane.x0 + 4, lane.y0 + 20, lane.x0 + 4 + w_used, lane.y0 + 20 + h_needed), wrapped, fs

# ============================================================
# Connector routing
# ============================================================

def _route_connector_page1(page, callout, target, callout_blocks, highlight_rects, start_mode="auto"):
    pr = page.rect
    tc = _center(target)
    gutters = [EDGE_PAD, pr.width - EDGE_PAD]
    
    # Target-side Y candidates
    y_candidates = sorted({_clamp(y, EDGE_PAD, pr.height - EDGE_PAD) for y in [tc.y, target.y0-5, target.y1+5]}, key=lambda y: abs(y - tc.y))
    
    # Decide start Y based on mode
    s_top, s_bot = _clamp(callout.y0 - 5, EDGE_PAD, pr.height-EDGE_PAD), _clamp(callout.y1 + 5, EDGE_PAD, pr.height-EDGE_PAD)
    start_ys = [s_bot, s_top] if start_mode == "low" or (start_mode == "auto" and abs(s_bot - tc.y) < abs(s_top - tc.y)) else [s_top, s_bot]

    best_pts, best_score = None, float("inf")

    for gx in gutters:
        # Nudge x away from box
        start_x = _clamp(callout.x0 - 5 if gx < pr.width/2 else callout.x1 + 5, EDGE_PAD, pr.width-EDGE_PAD)
        
        for sy in start_ys:
            start = fitz.Point(start_x, sy)
            for y in y_candidates:
                approach_x = target.x1 + 3 if gx > target.x1 else target.x0 - 3
                end_raw = fitz.Point(target.x1 if gx > target.x1 else target.x0, _clamp(y, target.y0+1, target.y1-1))
                pts = [start, fitz.Point(gx, sy), fitz.Point(gx, y), fitz.Point(approach_x, y), _pull_back_point(fitz.Point(approach_x, y), end_raw, ENDPOINT_PULLBACK)]
                
                # Check Hard Obstacles
                if any(_segment_hits_rect(pts[i], pts[i+1], br) for i in range(len(pts)-1) for br in callout_blocks):
                    continue
                
                # Soft Score (hits + length)
                hits = sum(1 for i in range(len(pts)-1) for hr in highlight_rects if _segment_hits_rect(pts[i], pts[i+1], hr) and not hr.intersects(target))
                dist = sum(math.hypot(pts[i+1].x-pts[i].x, pts[i+1].y-pts[i].y) for i in range(len(pts)-1))
                score = hits * 10000 + dist
                
                if score < best_score:
                    best_score, best_pts = score, pts
                if hits == 0: return pts

    return best_pts if best_pts else [fitz.Point(callout.x0 if tc.x < callout.x0 else callout.x1, (callout.y0+callout.y1)/2), tc]

def _draw_multipage_connector(doc, cp_idx, c_rect, tp_idx, t_rect):
    cp, tp = doc.load_page(cp_idx), doc.load_page(tp_idx)
    gx = cp.rect.width - EDGE_PAD if _center(c_rect).x > cp.rect.width/2 else EDGE_PAD
    start = fitz.Point(c_rect.x1 if gx > c_rect.x1 else c_rect.x0, c_rect.y1 + 2)
    _draw_poly_connector(cp, [start, fitz.Point(gx, start.y), fitz.Point(gx, cp.rect.height - EDGE_PAD)])
    
    for i in range(cp_idx + 1, tp_idx):
        p = doc.load_page(i)
        _draw_line(p, fitz.Point(gx, EDGE_PAD), fitz.Point(gx, p.rect.height - EDGE_PAD))
        
    ty = _clamp(_center(t_rect).y, EDGE_PAD, tp.rect.height - EDGE_PAD)
    end_raw = fitz.Point(t_rect.x1 if gx > t_rect.x1 else t_rect.x0, ty)
    _draw_poly_connector(tp, [fitz.Point(gx, EDGE_PAD), fitz.Point(gx, ty), _pull_back_point(fitz.Point(gx, ty), end_raw, 2)])

# ============================================================
# Main process
# ============================================================

def annotate_pdf_bytes(pdf_bytes: bytes, quote_terms: List[str], criterion_id: str, meta: Dict) -> Tuple[bytes, Dict]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if not doc: return pdf_bytes, {}
    
    page1 = doc[0]
    text_area, left_lane, right_lane = _compute_equal_margins(page1)
    page1_redboxes, all_callouts, connectors_to_draw = [], [], []
    occ_l, occ_r = [], []

    # 1) Quotes
    for p in doc:
        for t in (quote_terms or []):
            if _looks_like_url(t) and p.number != 0: continue
            for r in _dedupe_rects(p.search_for(t)):
                p.draw_rect(r, color=RED, width=BOX_WIDTH)
                if p.number == 0: page1_redboxes.append(r)

    # 2) Metadata Jobs
    jobs = [
        ("Original source of publication.", meta.get("source_url")),
        ("Venue is distinguished organization.", meta.get("venue_name")),
        ("Ensemble is distinguished organization.", meta.get("ensemble_name")),
        ("Performance date.", meta.get("performance_date")),
        ("Beneficiary lead role evidence.", meta.get("beneficiary_name"), meta.get("beneficiary_variants"))
    ]

    for label, val, *vars in jobs:
        if not val: continue
        needles = [val] + (vars[0] if vars else [])
        targets = {}
        for n in needles:
            for i in ([0] if _looks_like_url(val) else range(len(doc))):
                hits = doc[i].search_for(n)
                if hits:
                    targets.setdefault(i, []).extend(hits)
                    for r in hits:
                        doc[i].draw_rect(r, color=RED, width=BOX_WIDTH)
                        if i == 0: page1_redboxes.append(r)
        
        if targets:
            side = "left" if label in SIDE_LEFT_LABELS else "right"
            lane, occ = (left_lane, occ_l) if side == "left" else (right_lane, occ_r)
            c_rect, wtext, fs = _place_callout_in_lane(page1, lane, text_area, _union_rect(targets.get(0, targets[min(targets)])), occ, label)
            page1.draw_rect(c_rect, color=WHITE, fill=WHITE, overlay=True)
            final_r, _, _ = _insert_textbox_fit(page1, c_rect, wtext, fontsize=fs)
            occ.append(final_r); all_callouts.append(final_r)
            connectors_to_draw.append({"final_rect": final_r, "targets_by_page": targets, "label": label})

    # 3) Connectors (Fixed Logic)
    redboxes_p1 = _dedupe_rects(page1_redboxes, 0.5)
    for item in connectors_to_draw:
        fr, label = item["final_rect"], item["label"]
        # CRITICAL FIX: Exclude self from obstacles
        blocks = [inflate_rect(c, 1.0) for c in all_callouts if c != fr]
        
        for pi, rects in item["targets_by_page"].items():
            if pi == 0:
                mode = "low" if "Original" in label or "acclaimed" in label else "auto"
                for r in _dedupe_rects(rects):
                    pts = _route_connector_page1(page1, fr, r, blocks, redboxes_p1, mode)
                    _draw_poly_connector(page1, pts)
            else:
                for r in _dedupe_rects(rects):
                    _draw_multipage_connector(doc, 0, fr, pi, r)

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue(), {"criterion_id": criterion_id}
