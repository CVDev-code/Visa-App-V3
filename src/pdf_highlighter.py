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
    vx, vy = from_pt.x - to_pt.x, from_pt.y - to_pt.y
    d = math.hypot(vx, vy)
    if d == 0: return to_pt
    return fitz.Point(to_pt.x + (vx / d) * dist, to_pt.y + (vy / d) * dist)

def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))

def _ccw(A, B, C):
    """Checks if points A, B, C are in counter-clockwise order."""
    return (C.y - A.y) * (B.x - A.x) > (B.y - A.y) * (C.x - A.x)

def _segments_intersect(p1, p2, p3, p4):
    """Manual check for segment intersection to avoid PyMuPDF version issues."""
    return (_ccw(p1, p3, p4) != _ccw(p2, p3, p4)) and (_ccw(p1, p2, p3) != _ccw(p1, p2, p4))

def _segment_hits_rect(p1: fitz.Point, p2: fitz.Point, r: fitz.Rect) -> bool:
    """Checks if a line segment p1->p2 hits rectangle r."""
    if r.contains(p1) or r.contains(p2):
        return True
    # Check intersection with all 4 edges of the rectangle
    edges = [
        (fitz.Point(r.x0, r.y0), fitz.Point(r.x1, r.y0)),
        (fitz.Point(r.x1, r.y0), fitz.Point(r.x1, r.y1)),
        (fitz.Point(r.x1, r.y1), fitz.Point(r.x0, r.y1)),
        (fitz.Point(r.x0, r.y1), fitz.Point(r.x0, r.y0))
    ]
    for e1, e2 in edges:
        if _segments_intersect(p1, p2, e1, e2):
            return True
    return False

# ============================================================
# Text and Search logic
# ============================================================

def _detect_actual_text_area(page: fitz.Page) -> fitz.Rect:
    pr = page.rect
    try:
        words = page.get_text("words") or []
        if not words: return fitz.Rect(pr.width*0.1, pr.height*0.1, pr.width*0.9, pr.height*0.9)
        x0s = sorted([w[0] for w in words if w[1] > pr.height*0.1 and w[3] < pr.height*0.9])
        x1s = sorted([w[2] for w in words if w[1] > pr.height*0.1 and w[3] < pr.height*0.9])
        l = x0s[int(len(x0s)*0.05)] if x0s else pr.width*0.1
        r = x1s[int(len(x1s)*0.95)] if x1s else pr.width*0.9
        return fitz.Rect(max(pr.width*0.08, l), pr.height*0.12, min(pr.width*0.92, r), pr.height*0.88)
    except: return fitz.Rect(pr.width*0.1, pr.height*0.1, pr.width*0.9, pr.height*0.9)

def _optimize_layout_for_margin(text: str, box_width: float) -> Tuple[int, str, float, float]:
    words = (text or "").strip().split()
    if not words: return 11, "", box_width, 24.0
    for fs in FONT_SIZES:
        lines, cur, usable_w = [], "", max(30.0, box_width - 10.0)
        for w in words:
            trial = (cur + " " + w).strip() if cur else w
            if fitz.get_text_length(trial, fontname=FONTNAME, fontsize=fs) <= usable_w: cur = trial
            else:
                if cur: lines.append(cur)
                cur = w
        if cur: lines.append(cur)
        h = (len(lines) * fs * 1.25) + 10.0
        if h <= 220.0 or fs == FONT_SIZES[-1]: return fs, "\n".join(lines), box_width, h
    return 8, text, box_width, 50.0

# ============================================================
# Routing
# ============================================================

def _route_connector_page1(page, callout, target, callout_blocks, highlight_rects, start_mode="auto"):
    pr, tc = page.rect, _center(target)
    gutters = [EDGE_PAD, pr.width - EDGE_PAD]
    s_top, s_bot = _clamp(callout.y0 - 5, 5, pr.height-5), _clamp(callout.y1 + 5, 5, pr.height-5)
    start_ys = [s_bot, s_top] if start_mode == "low" or (start_mode == "auto" and abs(s_bot - tc.y) < abs(s_top - tc.y)) else [s_top, s_bot]

    best_pts, best_score = None, float("inf")
    for gx in gutters:
        start_x = _clamp(callout.x0 - 5 if gx < pr.width/2 else callout.x1 + 5, 5, pr.width-5)
        for sy in start_ys:
            start = fitz.Point(start_x, sy)
            for y in [tc.y, target.y0-2, target.y1+2]:
                y = _clamp(y, 5, pr.height-5)
                approach_x = target.x1 + 3 if gx > target.x1 else target.x0 - 3
                pts = [start, fitz.Point(gx, sy), fitz.Point(gx, y), fitz.Point(approach_x, y), 
                       _pull_back_point(fitz.Point(approach_x, y), fitz.Point(target.x1 if gx > target.x1 else target.x0, y), ENDPOINT_PULLBACK)]
                
                if any(_segment_hits_rect(pts[i], pts[i+1], br) for i in range(len(pts)-1) for br in callout_blocks): continue
                
                hits = sum(1 for i in range(len(pts)-1) for hr in highlight_rects if _segment_hits_rect(pts[i], pts[i+1], hr) and not hr.intersects(target))
                score = hits * 10000 + sum(math.hypot(pts[i+1].x-pts[i].x, pts[i+1].y-pts[i].y) for i in range(len(pts)-1))
                if score < best_score: best_score, best_pts = score, pts
                if hits == 0: return pts
    return best_pts if best_pts else [fitz.Point(callout.x1 if tc.x > callout.x1 else callout.x0, (callout.y0+callout.y1)/2), tc]

# ============================================================
# Main Entry
# ============================================================

def annotate_pdf_bytes(pdf_bytes: bytes, quote_terms: List[str], criterion_id: str, meta: Dict) -> Tuple[bytes, Dict]:
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    if not doc: return pdf_bytes, {}
    
    page1 = doc[0]
    text_area = _detect_actual_text_area(page1)
    lane_w = max(60.0, min(text_area.x0 - EDGE_PAD, (page1.rect.width - EDGE_PAD) - text_area.x1))
    left_lane = fitz.Rect(EDGE_PAD, EDGE_PAD, EDGE_PAD + lane_w, page1.rect.height - EDGE_PAD)
    right_lane = fitz.Rect(page1.rect.width - EDGE_PAD - lane_w, EDGE_PAD, page1.rect.width - EDGE_PAD, page1.rect.height - EDGE_PAD)

    page1_redboxes, all_callouts, connectors_to_draw = [], [], []
    occ_l, occ_r = [], []

    # Process Labels
    jobs = [
        ("Original source of publication.", meta.get("source_url")),
        ("Venue is distinguished organization.", meta.get("venue_name")),
        ("Ensemble is distinguished organization.", meta.get("ensemble_name")),
        ("Performance date.", meta.get("performance_date")),
        ("Beneficiary lead role evidence.", meta.get("beneficiary_name"), meta.get("beneficiary_variants"))
    ]

    for label, val, *vars in jobs:
        if not val: continue
        targets = {}
        for n in [val] + (vars[0] if vars else []):
            for i in range(len(doc)):
                hits = doc[i].search_for(n)
                if hits:
                    targets.setdefault(i, []).extend(hits)
                    for r in hits:
                        doc[i].draw_rect(r, color=RED, width=BOX_WIDTH)
                        if i == 0: page1_redboxes.append(r)
        
        if targets:
            side = "left" if label in SIDE_LEFT_LABELS else "right"
            lane, occ = (left_lane, occ_l) if side == "left" else (right_lane, occ_r)
            fs, wtext, w_u, h_n = _optimize_layout_for_margin(label, lane.width - 8)
            target_y = _center(_union_rect(targets.get(0, targets[min(targets)]))).y
            
            c_rect = None
            for dy in [0, 30, -30, 60, -60]:
                cy = _clamp(target_y + dy, lane.y0 + h_n/2, lane.y1 - h_n/2)
                cand = fitz.Rect(lane.x0 + 4, cy - h_n/2, lane.x0 + 4 + w_u, cy + h_n/2)
                if not any(inflate_rect(cand, 5).intersects(o) for o in occ):
                    c_rect = cand; break
            
            if not c_rect: c_rect = fitz.Rect(lane.x0 + 4, lane.y0 + 10, lane.x0 + 4 + w_u, lane.y0 + 10 + h_n)
            
            page1.draw_rect(c_rect, color=WHITE, fill=WHITE, overlay=True)
            page1.insert_textbox(c_rect, wtext, fontname=FONTNAME, fontsize=fs, color=RED)
            occ.append(c_rect); all_callouts.append(c_rect)
            connectors_to_draw.append({"final_rect": c_rect, "targets_by_page": targets, "label": label})

    # Draw connectors with self-collision fix
    for item in connectors_to_draw:
        fr = item["final_rect"]
        blocks = [inflate_rect(c, 1.0) for c in all_callouts if c != fr] # The Fix
        for pi, rects in item["targets_by_page"].items():
            for r in rects:
                if pi == 0:
                    pts = _route_connector_page1(page1, fr, r, blocks, page1_redboxes)
                    for a, b in zip(pts, pts[1:]): page1.draw_line(a, b, color=RED, width=LINE_WIDTH)
                    vx, vy = pts[-1].x - pts[-2].x, pts[-1].y - pts[-2].y
                    d = math.hypot(vx, vy)
                    if d > 0:
                        ux, uy = vx/d, vy/d
                        bx, by = pts[-1].x - ux*ARROW_LEN, pts[-1].y - uy*ARROW_LEN
                        p1 = fitz.Point(bx - uy*ARROW_HALF_WIDTH, by + ux*ARROW_HALF_WIDTH)
                        p2 = fitz.Point(bx + uy*ARROW_HALF_WIDTH, by - ux*ARROW_HALF_WIDTH)
                        page1.draw_polyline([p1, pts[-1], p2, p1], color=RED, fill=RED, width=0)

    out = io.BytesIO()
    doc.save(out)
    return out.getvalue(), {"criterion_id": criterion_id}
