"""
Research Tab - Tab 1
Gather evidence with 3 input methods per criterion in dropdown format
"""

import streamlit as st
from src.prompts import CRITERIA


def render_research_tab():
    """
    Main research interface with dropdowns for each criterion
    """
    
    st.header("🔍 Research & Gather Evidence")
    st.markdown("Gather sources for each criterion using upload, URLs, or AI agent")
    
    beneficiary_name = st.session_state.beneficiary_name
    
    # Show all criteria as dropdowns
    st.divider()
    
    for cid, desc in CRITERIA.items():
        render_criterion_research(cid, desc, beneficiary_name)
    
    # Summary at bottom
    st.divider()
    render_research_summary()


def render_criterion_research(cid: str, desc: str, beneficiary_name: str):
    """
    Single criterion research section with 3 input methods + approval
    """
    
    # Count current results
    results = st.session_state.research_results.get(cid, [])
    approvals = st.session_state.research_approvals.get(cid, {})
    approved_count = sum(1 for url, approved in approvals.items() if approved)
    
    status = f"({len(results)} sources, {approved_count} approved)" if results else ""
    
    with st.expander(f"📋 **Criterion ({cid}):** {desc} {status}", expanded=len(results) == 0):
        
        # ========================================
        # 3 INPUT METHODS
        # ========================================
        st.markdown("### 📥 Gather Sources")
        
        col1, col2, col3 = st.columns(3)
        
        # METHOD 1: Upload
        with col1:
            st.markdown("**📤 Upload PDFs**")
            uploaded = st.file_uploader(
                "Choose PDF files",
                type=["pdf"],
                accept_multiple_files=True,
                key=f"upload_{cid}",
                label_visibility="collapsed"
            )
            
            if uploaded:
                # Convert uploads to "results" format
                if cid not in st.session_state.research_results:
                    st.session_state.research_results[cid] = []
                if cid not in st.session_state.research_approvals:
                    st.session_state.research_approvals[cid] = {}
                
                for file in uploaded:
                    file_url = f"upload://{file.name}"
                    
                    # Check if already added
                    if not any(r['url'] == file_url for r in st.session_state.research_results[cid]):
                        st.session_state.research_results[cid].append({
                            'url': file_url,
                            'title': file.name,
                            'source': 'Uploaded PDF',
                            'excerpt': f'User uploaded: {file.name}',
                            'pdf_bytes': file.read()
                        })
                        st.session_state.research_approvals[cid][file_url] = True
                
                st.success(f"✅ {len(uploaded)} file(s)")
        
        # METHOD 2: URLs
        with col2:
            st.markdown("**🔗 Paste URLs**")
            urls_text = st.text_area(
                "Enter URLs (one per line)",
                placeholder="https://example.com/article",
                height=100,
                key=f"urls_{cid}",
                label_visibility="collapsed"
            )
            
            if st.button("Add URLs", key=f"add_urls_{cid}", use_container_width=True):
                urls = [u.strip() for u in urls_text.split("\n") if u.strip()]
                
                if urls:
                    if cid not in st.session_state.research_results:
                        st.session_state.research_results[cid] = []
                    if cid not in st.session_state.research_approvals:
                        st.session_state.research_approvals[cid] = {}
                    
                    for url in urls:
                        # Check if already added
                        if not any(r['url'] == url for r in st.session_state.research_results[cid]):
                            st.session_state.research_results[cid].append({
                                'url': url,
                                'title': url.split('/')[-1] or 'Article',
                                'source': 'URL',
                                'excerpt': f'Source: {url}'
                            })
                            st.session_state.research_approvals[cid][url] = True
                    
                    st.success(f"✅ Added {len(urls)} URL(s)")
                    st.rerun()
        
        # METHOD 3: AI Agent
        with col3:
            st.markdown("**🤖 AI Agent**")
            
            if st.button("🔍 Search with AI", key=f"ai_{cid}", use_container_width=True):
                with st.spinner("🤖 AI Agent searching..."):
                    try:
                        from src.ai_assistant import search_with_ai_assistant
                        
                        results_found = search_with_ai_assistant(
                            artist_name=beneficiary_name,
                            criterion_id=cid,
                            criterion_description=desc,
                            name_variants=st.session_state.beneficiary_variants,
                            artist_field=st.session_state.artist_field,
                            max_results=10
                        )
                        
                        if results_found:
                            # Add to research results
                            if cid not in st.session_state.research_results:
                                st.session_state.research_results[cid] = []
                            if cid not in st.session_state.research_approvals:
                                st.session_state.research_approvals[cid] = {}
                            
                            for item in results_found:
                                url = item['url']
                                if not any(r['url'] == url for r in st.session_state.research_results[cid]):
                                    st.session_state.research_results[cid].append(item)
                                    st.session_state.research_approvals[cid][url] = True
                            
                            st.success(f"✅ AI Agent found {len(results_found)} sources!")
                            st.rerun()
                        else:
                            st.warning("AI Agent found no results")
                    
                    except Exception as e:
                        st.error(f"AI Agent error: {str(e)}")
                        
                        # Show helpful message if assistant not configured
                        if "OPENAI_ASSISTANT_ID" in str(e):
                            with st.expander("📖 How to set up AI Agent"):
                                st.markdown("""
                                **Step 1:** Go to https://platform.openai.com/assistants
                                
                                **Step 2:** Click "Create Assistant"
                                
                                **Step 3:** Configure:
                                - Name: "O-1 Visa Evidence Researcher"
                                - Model: gpt-4o
                                - Tools: Enable "Web Search"
                                - Instructions: (see documentation)
                                
                                **Step 4:** Copy the Assistant ID (starts with `asst_...`)
                                
                                **Step 5:** Add to Streamlit Secrets:
                                ```
                                OPENAI_ASSISTANT_ID = "asst_abc123..."
                                ```
                                """)
                        else:
                            st.info("💡 Try the Upload or URL methods instead")
        
        # ========================================
        # REVIEW & APPROVE RESULTS
        # ========================================
        if not results:
            st.info("👆 Use one of the methods above to gather sources")
            return
        
        st.divider()
        st.markdown("### ✅ Review & Approve Sources")
        
        # Bulk actions
        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            if st.button("✅ Approve All", key=f"approve_all_{cid}"):
                for item in results:
                    approvals[item['url']] = True
                st.rerun()
        
        with col2:
            if st.button("❌ Reject All", key=f"reject_all_{cid}"):
                for item in results:
                    approvals[item['url']] = False
                st.rerun()
        
        with col3:
            if st.button("🗑️ Clear All Results", key=f"clear_{cid}"):
                st.session_state.research_results[cid] = []
                st.session_state.research_approvals[cid] = {}
                st.rerun()
        
        st.markdown("---")
        
        # Show each result with checkbox
        for i, item in enumerate(results):
            url = item['url']
            title = item.get('title', 'Untitled')
            source = item.get('source', 'Unknown')
            excerpt = item.get('excerpt', '')
            
            is_approved = approvals.get(url, True)
            
            # Checkbox for approval
            new_approval = st.checkbox(
                f"**[{source}]** {title}",
                value=is_approved,
                key=f"approve_{cid}_{i}"
            )
            approvals[url] = new_approval
            
            # Show excerpt and URL
            if excerpt:
                st.caption(f"📝 {excerpt[:200]}...")
            st.caption(f"🔗 {url}")
            
            st.markdown("---")
        
        st.session_state.research_approvals[cid] = approvals
        
        # Show counts
        approved = sum(1 for ok in approvals.values() if ok)
        rejected = sum(1 for ok in approvals.values() if not ok)
        st.write(f"**✅ Approved: {approved}** | **❌ Rejected: {rejected}**")
        
        # Regenerate option
        st.divider()
        st.markdown("### 🔄 Not satisfied?")
        
        feedback_text = st.text_area(
            "Tell AI what to improve",
            placeholder="e.g., 'Need more from major publications'",
            key=f"feedback_{cid}",
            height=60
        )
        
        if st.button("🔄 Regenerate with AI", key=f"regen_{cid}"):
            with st.spinner("Regenerating..."):
                try:
                    from src.ai_assistant import search_with_ai_assistant
                    
                    # Get approved/rejected URLs
                    approved_urls = [url for url, ok in approvals.items() if ok]
                    rejected_urls = [url for url, ok in approvals.items() if not ok]
                    
                    # Build feedback message
                    feedback_msg = feedback_text or ""
                    
                    if rejected_urls:
                        feedback_msg += f"\n\nAvoid sources like these (rejected):\n"
                        for url in rejected_urls[:3]:  # Show first 3 as examples
                            feedback_msg += f"- {url}\n"
                    
                    new_results = search_with_ai_assistant(
                        artist_name=beneficiary_name,
                        criterion_id=cid,
                        criterion_description=desc,
                        name_variants=st.session_state.beneficiary_variants,
                        artist_field=st.session_state.artist_field,
                        feedback=feedback_msg,
                        max_results=10
                    )
                    
                    if new_results:
                        # Keep approved, add new
                        kept = [r for r in results if approvals.get(r['url'], False)]
                        kept_urls = {r['url'] for r in kept}
                        new_items = [r for r in new_results if r['url'] not in kept_urls]
                        
                        st.session_state.research_results[cid] = kept + new_items
                        
                        # Auto-approve new
                        for item in new_items:
                            st.session_state.research_approvals[cid][item['url']] = True
                        
                        st.success(f"✅ Found {len(new_items)} new sources!")
                        st.rerun()
                
                except Exception as e:
                    st.error(f"Error: {str(e)}")


def render_research_summary():
    """Show summary and convert to PDFs button"""
    
    st.subheader("📊 Summary")
    
    total_sources = sum(len(results) for results in st.session_state.research_results.values())
    total_approved = sum(
        sum(1 for ok in approvals.values() if ok)
        for approvals in st.session_state.research_approvals.values()
    )
    
    col1, col2 = st.columns(2)
    with col1:
        st.metric("Total Sources", total_sources)
    with col2:
        st.metric("Approved Sources", total_approved)
    
    if total_approved == 0:
        st.info("No sources approved yet. Approve sources above to continue.")
        return
    
    st.divider()
    st.markdown(f"### 🔄 Ready to process {total_approved} approved sources")
    
    if st.button("🔄 Convert to PDFs & Continue to Highlight Tab", type="primary", use_container_width=True):
        with st.spinner(f"Processing {total_approved} sources..."):
            convert_approved_to_pdfs()


def convert_approved_to_pdfs():
    """Convert all approved sources to PDFs"""
    
    from src.web_to_pdf import batch_convert_urls_to_pdfs
    
    # Separate uploads from URLs
    for cid, results in st.session_state.research_results.items():
        approvals = st.session_state.research_approvals.get(cid, {})
        
        if cid not in st.session_state.criterion_pdfs:
            st.session_state.criterion_pdfs[cid] = {}
        
        # Process each approved result
        urls_to_convert = []
        
        for item in results:
            url = item['url']
            
            if not approvals.get(url, False):
                continue  # Skip rejected
            
            # Check if upload
            if url.startswith('upload://'):
                # Already have PDF bytes
                filename = url.replace('upload://', '')
                st.session_state.criterion_pdfs[cid][filename] = item['pdf_bytes']
            else:
                # URL to convert
                urls_to_convert.append({
                    'url': url,
                    'title': item.get('title', 'source')
                })
        
        # Convert URLs
        if urls_to_convert:
            try:
                pdfs = batch_convert_urls_to_pdfs(
                    {cid: urls_to_convert},
                    progress_callback=None
                )
                
                if cid in pdfs:
                    st.session_state.criterion_pdfs[cid].update(pdfs[cid])
            
            except Exception as e:
                st.error(f"Error converting criterion {cid}: {str(e)}")
    
    total_pdfs = sum(len(pdfs) for pdfs in st.session_state.criterion_pdfs.values())
    
    st.success(f"""
    ✅ Processed {total_pdfs} PDFs!
    
    **Go to the Highlight & Export tab** to continue →
    """)
