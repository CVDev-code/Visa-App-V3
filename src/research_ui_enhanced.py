import streamlit as st
from typing import Dict, List
import json

from src.research_assistant import (
    generate_search_queries,
    verify_organization_distinguished,
    check_primary_source
)
from src.prompts import CRITERIA


def render_research_tab():
    """Render the enhanced Research Assistant tab with full preview and approval workflow."""
    
    st.header("🔍 Research Assistant")
    st.markdown("""
    Find evidence online, preview documents, approve the best ones, and convert them to PDFs
    automatically - ready for the PDF Highlighter tab.
    """)
    
    # Initialize session state
    if "research_results" not in st.session_state:
        st.session_state.research_results = {}
    if "research_urls" not in st.session_state:
        st.session_state.research_urls = {}  # URLs by criterion
    if "research_previews" not in st.session_state:
        st.session_state.research_previews = {}  # Webpage content cache
    if "research_approvals" not in st.session_state:
        st.session_state.research_approvals = {}  # Approval status
    if "research_feedback" not in st.session_state:
        st.session_state.research_feedback = {}  # User feedback by criterion
    if "research_pdfs" not in st.session_state:
        st.session_state.research_pdfs = {}  # Converted PDFs
    
    # Get shared criteria from sidebar (will be set in main app.py)
    selected_criteria = st.session_state.get("selected_criteria", [])
    beneficiary_name = st.session_state.get("beneficiary_name", "")
    beneficiary_variants = st.session_state.get("beneficiary_variants", [])
    
    if not beneficiary_name:
        st.warning("⚠️ Please enter the beneficiary name in the sidebar first.")
        st.stop()
    
    if not selected_criteria:
        st.warning("⚠️ Please select at least one criterion in the sidebar.")
        st.stop()
    
    # Artist Information Display
    st.subheader("1. Artist Information")
    st.info(f"**Artist:** {beneficiary_name}  \n**Variants:** {', '.join(beneficiary_variants) if beneficiary_variants else 'None'}")
    
    # Generate Search Queries
    st.subheader("2. Generate Search Queries")
    
    if st.button("🔎 Generate Search Queries", type="primary"):
        with st.spinner("Generating targeted search queries..."):
            queries = generate_search_queries(
                artist_name=beneficiary_name,
                name_variants=beneficiary_variants,
                selected_criteria=selected_criteria,
                criteria_descriptions=CRITERIA
            )
            st.session_state.research_results = queries
            st.success(f"Generated queries for {len(queries)} criteria!")
    
    # Display Search Queries and URL Management
    if st.session_state.research_results:
        st.subheader("3. Find & Add URLs")
        st.markdown("**Use these queries to find evidence, then paste URLs below:**")
        
        for cid in selected_criteria:
            if cid not in st.session_state.research_results:
                continue
                
            with st.expander(f"📋 Criterion {cid}: {CRITERIA.get(cid, '')}", expanded=True):
                queries = st.session_state.research_results[cid]
                
                # Show generated queries
                st.markdown("**🔍 Suggested Search Queries:**")
                for i, query in enumerate(queries, 1):
                    st.code(query, language=None)
                
                st.markdown("---")
                
                # Initialize data structures for this criterion
                if cid not in st.session_state.research_urls:
                    st.session_state.research_urls[cid] = []
                if cid not in st.session_state.research_approvals:
                    st.session_state.research_approvals[cid] = {}
                
                # URL input section
                st.markdown("**➕ Add URL:**")
                
                col1, col2, col3 = st.columns([3, 2, 1])
                
                with col1:
                    new_url = st.text_input(
                        "Paste URL",
                        key=f"url_input_{cid}",
                        placeholder="https://example.com/article"
                    )
                
                with col2:
                    url_title = st.text_input(
                        "Title/Description",
                        key=f"url_title_{cid}",
                        placeholder="Brief description"
                    )
                
                with col3:
                    st.write("")  # Spacing
                    st.write("")
                    add_button = st.button("Add", key=f"add_url_{cid}")
                
                if add_button and new_url:
                    if not new_url.startswith("http"):
                        st.error("Please enter a valid URL starting with http:// or https://")
                    else:
                        # Check if URL already exists
                        existing = [u for u in st.session_state.research_urls[cid] if u['url'] == new_url]
                        if existing:
                            st.warning("This URL is already added!")
                        else:
                            # Primary source check for awards
                            verification = None
                            if cid == "1":
                                with st.spinner("Verifying primary source..."):
                                    verification = check_primary_source(
                                        url=new_url,
                                        title=url_title,
                                        snippet=""
                                    )
                                
                                if not verification.get("is_primary_source", False):
                                    st.warning(
                                        f"⚠️ This may not be a primary source: {verification.get('reasoning', '')}"
                                    )
                                    if not st.checkbox("Add anyway?", key=f"override_{cid}_{len(st.session_state.research_urls[cid])}"):
                                        st.stop()
                            
                            # Add URL
                            url_data = {
                                "url": new_url,
                                "title": url_title or new_url,
                                "verification": verification,
                                "fetched": False
                            }
                            st.session_state.research_urls[cid].append(url_data)
                            st.session_state.research_approvals[cid][new_url] = True  # Default approved
                            st.success("✅ URL added!")
                            st.rerun()
                
                # Display and manage existing URLs
                if st.session_state.research_urls[cid]:
                    st.markdown("---")
                    st.markdown("**📚 URLs Found:**")
                    
                    # Bulk actions
                    col1, col2 = st.columns(2)
                    with col1:
                        if st.button("✅ Approve All", key=f"approve_all_urls_{cid}"):
                            for url_data in st.session_state.research_urls[cid]:
                                st.session_state.research_approvals[cid][url_data['url']] = True
                            st.rerun()
                    with col2:
                        if st.button("❌ Reject All", key=f"reject_all_urls_{cid}"):
                            for url_data in st.session_state.research_urls[cid]:
                                st.session_state.research_approvals[cid][url_data['url']] = False
                            st.rerun()
                    
                    # List URLs with preview and approval
                    for idx, url_data in enumerate(st.session_state.research_urls[cid]):
                        url = url_data['url']
                        
                        # Approval checkbox
                        is_approved = st.session_state.research_approvals[cid].get(url, True)
                        new_approval = st.checkbox(
                            f"**{idx + 1}.** {url_data['title']}",
                            value=is_approved,
                            key=f"approve_{cid}_{idx}"
                        )
                        st.session_state.research_approvals[cid][url] = new_approval
                        
                        col1, col2, col3 = st.columns([4, 1, 1])
                        
                        with col1:
                            st.caption(f"🔗 {url}")
                            if url_data.get("verification"):
                                conf = url_data["verification"].get("confidence", "unknown")
                                is_primary = url_data["verification"].get("is_primary_source", False)
                                if is_primary:
                                    st.success(f"✅ Primary source ({conf})")
                                else:
                                    st.warning(f"⚠️ Not primary ({conf})")
                        
                        with col2:
                            # Preview button
                            if st.button("👁️ Preview", key=f"preview_{cid}_{idx}"):
                                with st.spinner("Fetching webpage..."):
                                    try:
                                        from src.web_to_pdf import fetch_webpage_content
                                        webpage_data = fetch_webpage_content(url)
                                        st.session_state.research_previews[url] = webpage_data
                                        url_data['fetched'] = True
                                        st.success("Fetched!")
                                        st.rerun()
                                    except Exception as e:
                                        st.error(f"Error: {str(e)}")
                        
                        with col3:
                            # Delete button
                            if st.button("🗑️", key=f"delete_{cid}_{idx}"):
                                st.session_state.research_urls[cid].pop(idx)
                                if url in st.session_state.research_approvals[cid]:
                                    del st.session_state.research_approvals[cid][url]
                                if url in st.session_state.research_previews:
                                    del st.session_state.research_previews[url]
                                st.rerun()
                        
                        # Show preview if fetched
                        if url in st.session_state.research_previews:
                            preview_data = st.session_state.research_previews[url]
                            with st.expander(f"📄 Preview: {preview_data.get('title', 'Document')}", expanded=False):
                                st.markdown(f"**Author:** {preview_data.get('author', 'Unknown')}")
                                st.markdown(f"**Date:** {preview_data.get('date', 'Unknown')}")
                                st.markdown("---")
                                content = preview_data.get('content', '')
                                # Show first 2000 chars with option to see more
                                if len(content) > 2000:
                                    st.text_area(
                                        "Content Preview",
                                        value=content[:2000] + "\n\n[...content continues...]",
                                        height=300,
                                        disabled=True,
                                        key=f"preview_content_{cid}_{idx}"
                                    )
                                else:
                                    st.text_area(
                                        "Content Preview",
                                        value=content,
                                        height=300,
                                        disabled=True,
                                        key=f"preview_content_{cid}_{idx}"
                                    )
                        
                        st.markdown("---")
                    
                    # Regenerate section
                    st.markdown("**🔄 Regenerate Search (Optional)**")
                    feedback_key = f"feedback_{cid}"
                    feedback_text = st.text_area(
                        "Instructions for finding better URLs",
                        placeholder="e.g., 'Focus on major opera houses only' or 'Need more recent articles'",
                        key=feedback_key,
                        height=80
                    )
                    
                    if st.button("🔄 Regenerate with Feedback", key=f"regen_{cid}"):
                        # Get approved and rejected examples
                        approved = [u['url'] for u in st.session_state.research_urls[cid] 
                                   if st.session_state.research_approvals[cid].get(u['url'], False)]
                        rejected = [u['url'] for u in st.session_state.research_urls[cid] 
                                   if not st.session_state.research_approvals[cid].get(u['url'], True)]
                        
                        with st.spinner("Generating new search queries..."):
                            # This would call the AI again with feedback
                            # For now, show message
                            st.info(f"""
                            Regenerating with feedback:
                            - Keeping {len(approved)} approved URLs
                            - Finding replacements for {len(rejected)} rejected URLs
                            - Using your feedback: "{feedback_text}"
                            
                            (Implementation: Call generate_search_queries with feedback parameter)
                            """)
    
    # Organization Verification Tool
    st.markdown("---")
    st.subheader("🏛️ Organization Verification Tool")
    st.markdown("Verify if a venue/organization is 'distinguished' and save evidence.")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        org_name = st.text_input(
            "Organization Name",
            placeholder="e.g., Bavarian State Opera",
            key="org_verify_input"
        )
    
    with col2:
        st.write("")
        st.write("")
        verify_button = st.button("✓ Verify", key="verify_org_button")
    
    if verify_button and org_name:
        with st.spinner(f"Verifying {org_name}..."):
            result = verify_organization_distinguished(
                organization_name=org_name,
                context=""
            )
            
            is_distinguished = result.get("is_distinguished", False)
            confidence = result.get("confidence", "unknown")
            reasoning = result.get("reasoning", "")
            
            if is_distinguished:
                st.success(f"✅ **Distinguished Organization** (Confidence: {confidence})")
            else:
                st.error(f"❌ **Not Distinguished** (Confidence: {confidence})")
            
            st.info(f"**Reasoning:** {reasoning}")
            
            # Option to save evidence
            if is_distinguished:
                if st.button("💾 Save as Evidence PDF", key="save_org_evidence"):
                    st.info("Feature coming: This will create a PDF document with the verification and source evidence.")
    
    # Convert Approved URLs to PDFs
    st.markdown("---")
    st.subheader("4. Convert Approved URLs to PDFs")
    
    # Count approved URLs
    total_approved = sum(
        sum(1 for url_data in st.session_state.research_urls.get(cid, [])
            if st.session_state.research_approvals.get(cid, {}).get(url_data['url'], True))
        for cid in selected_criteria
    )
    
    if total_approved == 0:
        st.info("No URLs approved yet. Add and approve URLs above.")
    else:
        st.markdown(f"**{total_approved} approved URLs** ready to convert.")
        
        if st.button("📄 Convert All Approved to PDFs", type="primary", key="convert_all"):
            with st.spinner(f"Converting {total_approved} documents to PDFs..."):
                from src.web_to_pdf import batch_convert_urls_to_pdfs
                
                # Prepare approved URLs by criterion
                approved_by_criterion = {}
                for cid in selected_criteria:
                    approved_urls = [
                        url_data for url_data in st.session_state.research_urls.get(cid, [])
                        if st.session_state.research_approvals.get(cid, {}).get(url_data['url'], True)
                    ]
                    if approved_urls:
                        approved_by_criterion[cid] = approved_urls
                
                # Convert to PDFs
                try:
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    
                    def progress_callback(processed, total, message):
                        progress_bar.progress(processed / total)
                        status_text.text(message)
                    
                    pdfs_by_criterion = batch_convert_urls_to_pdfs(
                        approved_by_criterion,
                        progress_callback=progress_callback
                    )
                    
                    st.session_state.research_pdfs = pdfs_by_criterion
                    
                    progress_bar.progress(1.0)
                    status_text.text("✅ All PDFs converted!")
                    
                    st.success(f"""
                    ✅ Converted {total_approved} documents to PDFs!
                    
                    These PDFs are now ready in the **PDF Highlighter** tab.
                    Switch to that tab to continue with quote extraction.
                    """)
                    
                except Exception as e:
                    st.error(f"Error during conversion: {str(e)}")
        
        # Show preview of what will be converted
        with st.expander("📋 Preview: What will be converted", expanded=False):
            for cid in selected_criteria:
                approved_urls = [
                    url_data for url_data in st.session_state.research_urls.get(cid, [])
                    if st.session_state.research_approvals.get(cid, {}).get(url_data['url'], True)
                ]
                if approved_urls:
                    st.markdown(f"**Criterion {cid}:** {len(approved_urls)} documents")
                    for url_data in approved_urls:
                        st.markdown(f"- {url_data['title']}")
    
    # Export research data
    if st.session_state.research_urls:
        st.markdown("---")
        st.subheader("💾 Export Research Data")
        
        if st.button("📥 Export as JSON"):
            export_data = {
                "artist_name": beneficiary_name,
                "name_variants": beneficiary_variants,
                "selected_criteria": selected_criteria,
                "urls_by_criterion": st.session_state.research_urls,
                "approvals": st.session_state.research_approvals
            }
            
            json_str = json.dumps(export_data, indent=2)
            st.download_button(
                label="Download JSON",
                data=json_str,
                file_name=f"{beneficiary_name.replace(' ', '_')}_research.json",
                mime="application/json"
            )
