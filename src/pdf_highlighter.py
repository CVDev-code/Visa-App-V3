import io, math, fitz

# Standard Config
RED = (1, 0, 0)
WHITE = (1, 1, 1)
L_WIDTH = 1.5
LEFT_LABELS = {"Original source of publication.", "Venue is distinguished organization.", "Ensemble is distinguished organization."}

def annotate_pdf_bytes(pdf_bytes, quote_terms, criterion_id, meta):
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    page = doc[0]
    width, height = page.rect.width, page.rect.height

    # 1. Define safe zones (The Gutters)
    # We assume standard 72pt margins if we can't find text
    left_gutter_x = 40 
    right_gutter_x = width - 40

    # 2. Search and Highlight
    # Combine quotes and meta into one list of things to find
    search_targets = []
    if quote_terms:
        for q in quote_terms: search_targets.append(("Quote", q))
    
    # Specific Metadata keys
    meta_jobs = [
        ("Original source of publication.", meta.get("source_url")),
        ("Venue is distinguished organization.", meta.get("venue_name")),
        ("Ensemble is distinguished organization.", meta.get("ensemble_name")),
        ("Performance date.", meta.get("performance_date")),
        ("Beneficiary lead role evidence.", meta.get("beneficiary_name"))
    ]

    all_obstacles = [] # To prevent labels from overlapping

    # 3. Draw Highlights and Prepare Callouts
    draw_queue = []
    for label, val in meta_jobs:
        if not val: continue
        hits = page.search_for(val)
        if not hits: continue
        
        # Draw red box around target
        for r in hits:
            page.draw_rect(r, color=RED, width=1.5)
        
        # Decide Side
        side = "left" if label in LEFT_LABELS else "right"
        target_rect = hits[0]
        
        # Label placement: In the margin, at the same height as the target
        x_pos = 10 if side == "left" else width - 70
        c_rect = fitz.Rect(x_pos, target_rect.y0, x_pos + 60, target_rect.y0 + 30)
        
        # Simple Nudge: If this spot is taken, move down
        while any(c_rect.intersects(o) for o in all_obstacles):
            c_rect.y0 += 35
            c_rect.y1 += 35
        
        all_obstacles.append(c_rect)
        draw_queue.append((c_rect, target_rect, side, label))

    # 4. Draw Callouts and "Gutter" Lines
    for c_rect, t_rect, side, label in draw_queue:
        # Draw the white box and red text
        page.draw_rect(c_rect, color=WHITE, fill=WHITE)
        page.insert_textbox(c_rect, label, fontsize=8, fontname="times-bold", color=RED)
        
        # Routing Logic: 
        # Start (Label) -> Gutter -> Vertical Alignment -> Target
        if side == "left":
            p1 = fitz.Point(c_rect.x1, (c_rect.y0 + c_rect.y1)/2) # Right edge of label
            p2 = fitz.Point(left_gutter_x, p1.y)                  # Into gutter
            p3 = fitz.Point(left_gutter_x, (t_rect.y0 + t_rect.y1)/2) # Down gutter to target height
            p4 = fitz.Point(t_rect.x0, p3.y)                      # To target box
        else:
            p1 = fitz.Point(c_rect.x0, (c_rect.y0 + c_rect.y1)/2) # Left edge of label
            p2 = fitz.Point(right_gutter_x, p1.y)                 # Into gutter
            p3 = fitz.Point(right_gutter_x, (t_rect.y0 + t_rect.y1)/2)
            p4 = fitz.Point(t_rect.x1, p3.y)

        # Draw the "Snake" line
        page.draw_line(p1, p2, color=RED, width=L_WIDTH)
        page.draw_line(p2, p3, color=RED, width=L_WIDTH)
        page.draw_line(p3, p4, color=RED, width=L_WIDTH)
        
        # Ending indicator (Small dot)
        page.draw_circle(p4, 1.5, color=RED, fill=RED)

    # Final Save
    out = io.BytesIO()
    doc.save(out)
    return out.getvalue(), {"criterion_id": criterion_id}
