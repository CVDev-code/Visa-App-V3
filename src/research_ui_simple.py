import streamlit as st
from typing import Dict, List
import json

# Remove this line - we'll import dynamically
# from src.ai_research import ai_search_for_evidence
from src.prompts import CRITERIA


def render_research_tab():
    """Render the AI-powered Research Assistant tab - workflow matches PDF Highlighter."""
    
    st.header("🔍 AI Research Assistant")
    st.markdown("""
    AI automatically searches the web for evidence. Preview what it finds, approve the best sources,
    and convert them to PDFs for the Highlighter tab.
    """)
    
    # Initialize session state
    if "research_results" not in st.session_state:
        st.session_state.research_results = {}  # AI search results by criterion
    if "research_approvals" not in st.session_state:
        st.session_state.research_approvals = {}  # User approvals by criterion
    if "research_feedback" not in st.session_state:
        st.session_state.research_feedback = {}  # User feedback text by criterion
    if "research_previews" not in st.session_state:
        st.session_state.research_previews = {}  # Fetched webpage content
    
    # Get shared config from sidebar
    selected_criteria = st.session_state.get("selected_criteria", [])
    beneficiary_name = st.session_state.get("beneficiary_name", "")
    beneficiary_variants = st.session_state.get("beneficiary_variants", [])
    
    if not beneficiary_name:
        st.warning("⚠️ Please enter the beneficiary name in the sidebar first.")
        st.stop()
    
    if not selected_criteria:
        st.warning("⚠️ Please select at least one criterion in the sidebar.")
        st.stop()
    
    # Display artist info
    st.info(f"**Artist:** {beneficiary_name}  \n**Variants:** {', '.join(beneficiary_variants) if beneficiary_variants else 'None'}")
    
    st.divider()
    
    # -------------------------
    # Step 1: AI Search
    # -------------------------
    st.subheader("1️⃣ AI searches the web for evidence")
    
    colA, colB = st.columns([1, 1])
    with colA:
        search_btn = st.button("🔎 Search for Evidence", type="primary")
    with colB:
        clear_btn = st.button("Clear results")
    
    if clear_btn:
        st.session_state.research_results = {}
        st.session_state.research_approvals = {}
        st.session_state.research_previews = {}
        st.success("Cleared all results.")
    
    if search_btn:
        with st.spinner("🤖 AI is searching the web for evidence... This may take 30-60 seconds."):
            try:
                # Import here to avoid module errors
                from src.ai_research import ai_search_for_evidence
                
                results = ai_search_for_evidence(
                    artist_name=beneficiary_name,
                    name_variants=beneficiary_variants,
                    selected_criteria=selected_criteria,
                    criteria_descriptions=CRITERIA,
                    feedback=None
                )
                
                st.session_state.research_results = results
                
                # Initialize approvals (default all to approved)
                for cid, items in results.items():
                    if cid not in st.session_state.research_approvals:
                        st.session_state.research_approvals[cid] = {}
                    for item in items:
                        url = item['url']
                        st.session_state.research_approvals[cid][url] = True
                
                total_found = sum(len(items) for items in results.values())
                st.success(f"✅ Found {total_found} sources across {len(results)} criteria!")
                
            except Exception as e:
                st.error(f"Error during search: {str(e)}")
    
    if not st.session_state.research_results:
        st.info("Click 'Search for Evidence' to begin. AI will find articles, reviews, and announcements.")
        st.stop()
    
    st.divider()
    
    # -------------------------
    # Step 2: Approve/Reject
    # -------------------------
    st.subheader("2️⃣ Approve / Reject sources by criterion")
    
    for cid in selected_criteria:
        if cid not in st.session_state.research_results:
            continue
        
        items = st.session_state.research_results[cid]
        crit_title = f"Criterion ({cid})"
        crit_desc = CRITERIA.get(cid, "")
        
        with st.expander(f"{crit_title}: {crit_desc}", expanded=True):
            if not items:
                st.write("No sources found for this criterion.")
                continue
            
            # Bulk actions
            b1, b2, b3 = st.columns([1, 1, 2])
            with b1:
                if st.button("Approve all", key=f"approve_all_{cid}"):
                    for item in items:
                        st.session_state.research_approvals[cid][item['url']] = True
                    st.rerun()
            with b2:
                if st.button("Reject all", key=f"reject_all_{cid}"):
                    for item in items:
                        st.session_state.research_approvals[cid][item['url']] = False
                    st.rerun()
            
            # Get approvals
            if cid not in st.session_state.research_approvals:
                st.session_state.research_approvals[cid] = {}
            approvals = st.session_state.research_approvals[cid]
            
            # Display each source
            for i, item in enumerate(items):
                url = item['url']
                title = item['title']
                source = item['source']
                relevance = item.get('relevance', '')
                excerpt = item.get('excerpt', '')
                
                # Approval checkbox
                is_approved = approvals.get(url, True)
                label = f"**{source}:** {title}"
                
                new_approval = st.checkbox(
                    label,
                    value=is_approved,
                    key=f"approval_{cid}_{i}"
                )
                approvals[url] = new_approval
                
                # Show details
                with st.container():
                    st.caption(f"🔗 {url}")
                    if relevance:
                        st.caption(f"**Why relevant:** {relevance}")
                    if excerpt:
                        with st.expander("📄 Preview excerpt", expanded=False):
                            st.markdown(excerpt)
                    
                    # PDF Preview - show exact final format
                    if st.button("📄 Preview as PDF", key=f"pdf_preview_{cid}_{i}"):
                        with st.spinner("Generating PDF preview..."):
                            try:
                                from src.web_to_pdf import convert_webpage_to_pdf_with_margins
                                import base64
                                
                                # Get full content from Tavily
                                full_content = item.get('full_content', '')
                                if not full_content:
                                    st.error("No content available for PDF generation")
                                else:
                                    # Prepare webpage data in expected format
                                    webpage_data = {
                                        'title': title,
                                        'author': '',  # Tavily doesn't always have author
                                        'date': '',
                                        'url': url,
                                        'content': full_content
                                    }
                                    
                                    # Convert to PDF with margins (same format as final export)
                                    pdf_bytes = convert_webpage_to_pdf_with_margins(
                                        webpage_data,
                                        left_margin_mm=40,
                                        right_margin_mm=40,
                                        top_margin_mm=20,
                                        bottom_margin_mm=20
                                    )
                                    
                                    # Store in session state
                                    if "pdf_previews" not in st.session_state:
                                        st.session_state.pdf_previews = {}
                                    st.session_state.pdf_previews[url] = pdf_bytes
                                    
                                    st.success("✅ PDF preview ready!")
                                    st.rerun()
                                    
                            except Exception as e:
                                st.error(f"Could not generate PDF: {str(e)}")
                    
                    # Show PDF preview if generated
                    if "pdf_previews" in st.session_state and url in st.session_state.pdf_previews:
                        with st.expander("📖 PDF Preview (Final Format)", expanded=True):
                            pdf_bytes = st.session_state.pdf_previews[url]
                            
                            # Display PDF inline
                            import base64
                            base64_pdf = base64.b64encode(pdf_bytes).decode('utf-8')
                            pdf_display = f'<iframe src="data:application/pdf;base64,{base64_pdf}" width="100%" height="800px" type="application/pdf"></iframe>'
                            
                            st.markdown("**This is exactly how the PDF will look after export:**")
                            st.markdown(pdf_display, unsafe_allow_html=True)
                            
                            # Download option
                            st.download_button(
                                label="⬇️ Download Preview PDF",
                                data=pdf_bytes,
                                file_name=f"preview_{title[:50]}.pdf",
                                mime="application/pdf",
                                key=f"download_preview_{cid}_{i}"
                            )
                
                st.markdown("---")
            
            st.session_state.research_approvals[cid] = approvals
            
            # Show counts
            approved = [url for url, ok in approvals.items() if ok]
            rejected = [url for url, ok in approvals.items() if not ok]
            st.write(f"✅ Approved: **{len(approved)}** | ❌ Rejected: **{len(rejected)}**")
            
            # Regenerate section
            st.markdown("---")
            st.markdown("**🔄 Regenerate for this criterion**")
            
            feedback_text = st.text_area(
                "Optional: Give AI feedback to find better sources",
                placeholder="e.g., 'Focus on more recent reviews' or 'Need sources from major venues only'",
                key=f"feedback_{cid}",
                height=80
            )
            
            if st.button("🔄 Regenerate", key=f"regen_{cid}"):
                with st.spinner(f"AI is searching for better sources for Criterion {cid}..."):
                    try:
                        # Import here
                        from src.ai_research import ai_search_for_evidence
                        
                        # Prepare feedback
                        feedback = {
                            "approved_urls": approved,
                            "rejected_urls": rejected,
                            "user_feedback": feedback_text
                        }
                        
                        # Search again with feedback
                        new_results = ai_search_for_evidence(
                            artist_name=beneficiary_name,
                            name_variants=beneficiary_variants,
                            selected_criteria=[cid],  # Only this criterion
                            criteria_descriptions=CRITERIA,
                            feedback=feedback
                        )
                        
                        # Merge: keep approved, add new results
                        if cid in new_results:
                            # Keep approved sources
                            kept_items = [item for item in items if approvals.get(item['url'], False)]
                            
                            # Add new sources (that aren't already approved)
                            approved_urls = set(item['url'] for item in kept_items)
                            new_items = [item for item in new_results[cid] if item['url'] not in approved_urls]
                            
                            # Update results
                            st.session_state.research_results[cid] = kept_items + new_items
                            
                            # Auto-approve new items
                            for item in new_items:
                                st.session_state.research_approvals[cid][item['url']] = True
                            
                            st.success(f"✅ Found {len(new_items)} new sources! Kept {len(kept_items)} approved.")
                            st.rerun()
                    
                    except Exception as e:
                        st.error(f"Error during regeneration: {str(e)}")
    
    st.divider()
    
    # -------------------------
    # Step 3: Convert to PDFs
    # -------------------------
    st.subheader("3️⃣ Convert approved sources to PDFs")
    
    # Count approved
    total_approved = 0
    for cid in selected_criteria:
        if cid in st.session_state.research_approvals:
            approved = [url for url, ok in st.session_state.research_approvals[cid].items() if ok]
            total_approved += len(approved)
    
    if total_approved == 0:
        st.info("No sources approved yet. Approve sources above to convert them to PDFs.")
    else:
        st.markdown(f"**{total_approved} approved sources** ready to convert.")
        
        if st.button("📄 Convert All Approved to PDFs", type="primary"):
            with st.spinner(f"Converting {total_approved} sources to PDFs..."):
                try:
                    from src.web_to_pdf import batch_convert_urls_to_pdfs
                    
                    # Prepare approved URLs by criterion
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
                    
                    # Convert to PDFs
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    def progress_callback(processed, total, message):
                        progress_bar.progress(processed / total)
                        status_text.text(message)
                    
                    pdfs_by_criterion = batch_convert_urls_to_pdfs(
                        approved_by_criterion,
                        progress_callback=progress_callback
                    )
                    
                    # Store in session state
                    st.session_state.research_pdfs = pdfs_by_criterion
                    
                    progress_bar.progress(1.0)
                    status_text.text("✅ All PDFs converted!")
                    
                    st.success(f"""
                    ✅ Converted {total_approved} sources to PDFs!
                    
                    Switch to the **PDF Highlighter** tab to continue.
                    Your converted PDFs are automatically loaded there.
                    """)
                    
                except Exception as e:
                    st.error(f"Error during conversion: {str(e)}")
