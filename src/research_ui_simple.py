import streamlit as st
from typing import Dict, List
import json


def render_research_tab():
    """
    Simplified Research Assistant - matches PDF Highlighter workflow exactly.
    
    Flow:
    1. AI searches → finds sources
    2. Shows excerpts (like quotes in PDF Highlighter)
    3. Approve/reject based on excerpts
    4. Convert approved → PDFs go to Highlighter tab
    """
    
    st.header("🔍 AI Research Assistant")
    st.markdown("""
    AI searches for evidence and shows you relevant excerpts. 
    Approve the best ones, then convert to PDFs.
    """)
    
    # Initialize session state
    if "research_results" not in st.session_state:
        st.session_state.research_results = {}
    if "research_approvals" not in st.session_state:
        st.session_state.research_approvals = {}
    
    # Get shared config
    selected_criteria = st.session_state.get("selected_criteria", [])
    beneficiary_name = st.session_state.get("beneficiary_name", "")
    beneficiary_variants = st.session_state.get("beneficiary_variants", [])
    
    if not beneficiary_name:
        st.warning("⚠️ Please enter the beneficiary name in the sidebar first.")
        st.stop()
    
    if not selected_criteria:
        st.warning("⚠️ Please select at least one criterion in the sidebar.")
        st.stop()
    
    st.info(f"**Artist:** {beneficiary_name}")
    st.divider()
    
    # -------------------------
    # Step 1: AI Search
    # -------------------------
    st.subheader("1️⃣ AI searches for evidence")
    
    colA, colB = st.columns([1, 1])
    with colA:
        search_btn = st.button("🔎 Search for Evidence", type="primary")
    with colB:
        clear_btn = st.button("Clear results")
    
    if clear_btn:
        st.session_state.research_results = {}
        st.session_state.research_approvals = {}
        st.success("Cleared.")
    
    if search_btn:
        with st.spinner("🤖 AI is searching... This may take 30-60 seconds."):
            try:
                from src.ai_research import ai_search_for_evidence
                from src.prompts import CRITERIA
                
                results = ai_search_for_evidence(
                    artist_name=beneficiary_name,
                    name_variants=beneficiary_variants,
                    selected_criteria=selected_criteria,
                    criteria_descriptions=CRITERIA,
                    feedback=None
                )
                
                st.session_state.research_results = results
                
                # Initialize approvals (default all approved)
                for cid, items in results.items():
                    if cid not in st.session_state.research_approvals:
                        st.session_state.research_approvals[cid] = {}
                    for item in items:
                        url = item['url']
                        st.session_state.research_approvals[cid][url] = True
                
                total = sum(len(items) for items in results.values())
                st.success(f"✅ Found {total} sources across {len(results)} criteria!")
                
            except Exception as e:
                st.error(f"Error: {str(e)}")
                st.info("💡 Tip: Check artist name spelling. Try searching manually in ChatGPT first to verify online presence.")
    
    if not st.session_state.research_results:
        st.info("Click 'Search for Evidence' to begin.")
        st.stop()
    
    st.divider()
    
    # -------------------------
    # Step 2: Approve/Reject (LIKE PDF HIGHLIGHTER)
    # -------------------------
    st.subheader("2️⃣ Approve / Reject sources")
    st.caption("Review excerpts below - approve the strong ones, reject weak ones")
    
    for cid in selected_criteria:
        if cid not in st.session_state.research_results:
            continue
        
        items = st.session_state.research_results[cid]
        from src.prompts import CRITERIA
        crit_desc = CRITERIA.get(cid, "")
        
        with st.expander(f"📋 Criterion ({cid}): {crit_desc}", expanded=True):
            if not items:
                st.write("No sources found.")
                continue
            
            # Bulk actions
            col1, col2 = st.columns(2)
            with col1:
                if st.button("✅ Approve all", key=f"approve_all_{cid}"):
                    for item in items:
                        st.session_state.research_approvals[cid][item['url']] = True
                    st.rerun()
            with col2:
                if st.button("❌ Reject all", key=f"reject_all_{cid}"):
                    for item in items:
                        st.session_state.research_approvals[cid][item['url']] = False
                    st.rerun()
            
            st.markdown("---")
            
            # Get approvals
            if cid not in st.session_state.research_approvals:
                st.session_state.research_approvals[cid] = {}
            approvals = st.session_state.research_approvals[cid]
            
            # Display each source (LIKE PDF HIGHLIGHTER QUOTES)
            for i, item in enumerate(items):
                url = item['url']
                title = item['title']
                source = item.get('source', 'Unknown')
                relevance = item.get('relevance', '')
                excerpt = item.get('excerpt', '')
                
                # Approval checkbox (LIKE QUOTE CHECKBOX)
                is_approved = approvals.get(url, True)
                
                # Format like PDF highlighter: [source] excerpt
                display_text = f"**[{source}]** {title}"
                
                new_approval = st.checkbox(
                    display_text,
                    value=is_approved,
                    key=f"approve_{cid}_{i}"
                )
                approvals[url] = new_approval
                
                # Show details in compact format
                with st.container():
                    if relevance:
                        st.caption(f"**Why relevant:** {relevance}")
                    if excerpt:
                        st.caption(f"**Excerpt:** \"{excerpt}\"")
                    
                    # URL and optional full preview
                    col1, col2 = st.columns([4, 1])
                    with col1:
                        st.caption(f"🔗 {url}")
                    with col2:
                        # Optional: Preview full article if needed
                        if st.button("👁️", key=f"view_{cid}_{i}", help="View full article"):
                            st.info("Opening in new tab - click the URL above")
                
                st.markdown("---")
            
            st.session_state.research_approvals[cid] = approvals
            
            # Show counts (LIKE PDF HIGHLIGHTER)
            approved = [url for url, ok in approvals.items() if ok]
            rejected = [url for url, ok in approvals.items() if not ok]
            st.write(f"✅ Approved: **{len(approved)}** | ❌ Rejected: **{len(rejected)}**")
            
            # Regenerate (LIKE PDF HIGHLIGHTER)
            st.markdown("---")
            st.markdown("**🔄 Not satisfied? Regenerate**")
            
            feedback_text = st.text_area(
                "Optional: Tell AI what to improve",
                placeholder="e.g., 'Need more from major publications' or 'Avoid local papers'",
                key=f"feedback_{cid}",
                height=60
            )
            
            if st.button("🔄 Regenerate", key=f"regen_{cid}"):
                with st.spinner("Searching for better sources..."):
                    try:
                        from src.ai_research import ai_search_for_evidence
                        from src.prompts import CRITERIA
                        
                        feedback = {
                            "approved_urls": approved,
                            "rejected_urls": rejected,
                            "user_feedback": feedback_text
                        }
                        
                        new_results = ai_search_for_evidence(
                            artist_name=beneficiary_name,
                            name_variants=beneficiary_variants,
                            selected_criteria=[cid],
                            criteria_descriptions=CRITERIA,
                            feedback=feedback
                        )
                        
                        if cid in new_results:
                            # Keep approved, add new
                            kept = [item for item in items if approvals.get(item['url'], False)]
                            approved_urls = set(item['url'] for item in kept)
                            new_items = [item for item in new_results[cid] if item['url'] not in approved_urls]
                            
                            st.session_state.research_results[cid] = kept + new_items
                            
                            # Auto-approve new
                            for item in new_items:
                                st.session_state.research_approvals[cid][item['url']] = True
                            
                            st.success(f"✅ Found {len(new_items)} new sources! Kept {len(kept)} approved.")
                            st.rerun()
                    
                    except Exception as e:
                        st.error(f"Error: {str(e)}")
    
    st.divider()
    
    # -------------------------
    # Step 3: Convert to PDFs
    # -------------------------
    st.subheader("3️⃣ Convert approved to PDFs")
    
    total_approved = sum(
        sum(1 for url, ok in st.session_state.research_approvals.get(cid, {}).items() if ok)
        for cid in selected_criteria
    )
    
    if total_approved == 0:
        st.info("No sources approved. Approve sources above.")
    else:
        st.markdown(f"**{total_approved} approved sources** ready.")
        
        if st.button("📄 Convert All to PDFs", type="primary"):
            with st.spinner(f"Converting {total_approved} sources..."):
                try:
                    from src.web_to_pdf import batch_convert_urls_to_pdfs
                    
                    # Prepare approved URLs
                    approved_by_criterion = {}
                    for cid in selected_criteria:
                        if cid not in st.session_state.research_results:
                            continue
                        
                        items = st.session_state.research_results[cid]
                        approvals = st.session_state.research_approvals.get(cid, {})
                        
                        approved_items = [
                            {"url": item['url'], "title": item['title']}
                            for item in items
                            if approvals.get(item['url'], False)
                        ]
                        
                        if approved_items:
                            approved_by_criterion[cid] = approved_items
                    
                    # Convert
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    def progress_callback(processed, total, message):
                        progress_bar.progress(processed / total)
                        status_text.text(message)
                    
                    pdfs = batch_convert_urls_to_pdfs(
                        approved_by_criterion,
                        progress_callback=progress_callback
                    )
                    
                    st.session_state.research_pdfs = pdfs
                    
                    progress_bar.progress(1.0)
                    status_text.text("✅ Done!")
                    
                    st.success(f"""
                    ✅ Converted {total_approved} sources!
                    
                    Switch to **PDF Highlighter** tab to continue.
                    """)
                    
                except Exception as e:
                    st.error(f"Error: {str(e)}")
