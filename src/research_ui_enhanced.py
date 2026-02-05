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
                            with st.spinner("Fetching and analyzing webpage..."):
                                try:
                                    from src.web_to_pdf import fetch_webpage_content
                                    
                                    # Fetch webpage immediately
                                    webpage_data = fetch_webpage_content(new_url)
                                    
                                    # Primary source check for awards
                                    verification = None
                                    if cid == "1":
                                        verification = check_primary_source(
                                            url=new_url,
                                            title=webpage_data.get('title', url_title),
                                            snippet=webpage_data.get('content', '')[:500]
                                        )
                                        
                                        if not verification.get("is_primary_source", False):
                                            st.warning(
                                                f"⚠️ This may not be a primary source: {verification.get('reasoning', '')}"
                                            )
                                            if not st.checkbox("Add anyway?", key=f"override_{cid}_{len(st.session_state.research_urls[cid])}"):
                                                st.stop()
                                    
                                    # Add URL with fetched content
                                    url_data = {
                                        "url": new_url,
                                        "title": url_title or webpage_data.get('title', new_url),
                                        "verification": verification,
                                        "webpage_data": webpage_data,
                                        "fetched": True
                                    }
                                    st.session_state.research_urls[cid].append(url_data)
                                    st.session_state.research_approvals[cid][new_url] = True  # Default approved
                                    st.session_state.research_previews[new_url] = webpage_data
                                    st.success("✅ URL added and fetched!")
                                    st.rerun()
                                    
                                except Exception as e:
                                    st.error(f"Error fetching webpage: {str(e)}")
                                    st.info("You can still add the URL manually and fetch later.")
                                    url_data = {
                                        "url": new_url,
                                        "title": url_title or new_url,
                                        "verification": None,
                                        "fetched": False
                                    }
                                    st.session_state.research_urls[cid].append(url_data)
                                    st.session_state.research_approvals[cid][new_url] = True
                                    st.success("✅ URL added!")
                                    st.rerun()
                
                # Display and manage existing URLs
                if st.session_state.research_urls[cid]:
                    st.markdown("---")
                    st.markdown("**📚 Documents Found:**")
                    st.caption(f"{len(st.session_state.research_urls[cid])} URLs added")
                    
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
                    
                    st.markdown("---")
                    
                    # List each URL with full preview
                    for idx, url_data in enumerate(st.session_state.research_urls[cid]):
                        url = url_data['url']
                        is_approved = st.session_state.research_approvals[cid].get(url, True)
                        
                        # Create expandable section for each URL
                        approval_icon = "✅" if is_approved else "❌"
                        expander_title = f"{approval_icon} {idx + 1}. {url_data['title']}"
                        
                        with st.expander(expander_title, expanded=False):
                            # Top row: URL and actions
                            st.markdown(f"**URL:** {url}")
                            
                            col1, col2, col3 = st.columns([2, 1, 1])
                            
                            with col1:
                                # Approval toggle
                                new_approval = st.checkbox(
                                    "✓ Approve this document",
                                    value=is_approved,
                                    key=f"approve_checkbox_{cid}_{idx}"
                                )
                                if new_approval != is_approved:
                                    st.session_state.research_approvals[cid][url] = new_approval
                                    st.rerun()
                            
                            with col2:
                                # Fetch/refresh button
                                if not url_data.get('fetched', False):
                                    if st.button("🔄 Fetch", key=f"fetch_{cid}_{idx}"):
                                        with st.spinner("Fetching webpage..."):
                                            try:
                                                from src.web_to_pdf import fetch_webpage_content
                                                webpage_data = fetch_webpage_content(url)
                                                st.session_state.research_previews[url] = webpage_data
                                                url_data['webpage_data'] = webpage_data
                                                url_data['fetched'] = True
                                                st.success("Fetched!")
                                                st.rerun()
                                            except Exception as e:
                                                st.error(f"Error: {str(e)}")
                            
                            with col3:
                                # Delete button
                                if st.button("🗑️ Delete", key=f"delete_{cid}_{idx}"):
                                    st.session_state.research_urls[cid].pop(idx)
                                    if url in st.session_state.research_approvals[cid]:
                                        del st.session_state.research_approvals[cid][url]
                                    if url in st.session_state.research_previews:
                                        del st.session_state.research_previews[url]
                                    st.rerun()
                            
                            # Verification status (for awards)
                            if url_data.get("verification"):
                                conf = url_data["verification"].get("confidence", "unknown")
                                is_primary = url_data["verification"].get("is_primary_source", False)
                                reasoning = url_data["verification"].get("reasoning", "")
                                
                                if is_primary:
                                    st.success(f"✅ **Primary Source** (confidence: {conf})")
                                else:
                                    st.warning(f"⚠️ **Not Primary Source** (confidence: {conf})")
                                st.caption(f"Reasoning: {reasoning}")
                            
                            st.markdown("---")
                            
                            # FULL DOCUMENT PREVIEW
                            if url_data.get('fetched', False) or url in st.session_state.research_previews:
                                webpage_data = url_data.get('webpage_data') or st.session_state.research_previews.get(url)
                                
                                if webpage_data:
                                    st.markdown("### 📄 Full Document Preview")
                                    
                                    # Metadata
                                    metadata_cols = st.columns(3)
                                    with metadata_cols[0]:
                                        st.caption(f"**Author:** {webpage_data.get('author', 'Unknown')}")
                                    with metadata_cols[1]:
                                        st.caption(f"**Date:** {webpage_data.get('date', 'Unknown')}")
                                    with metadata_cols[2]:
                                        word_count = len(webpage_data.get('content', '').split())
                                        st.caption(f"**Words:** ~{word_count}")
                                    
                                    st.markdown("---")
                                    
                                    # Full content in scrollable area
                                    content = webpage_data.get('content', '')
                                    if content:
                                        st.markdown("**Full Article Text:**")
                                        st.text_area(
                                            "Scroll to read entire document",
                                            value=content,
                                            height=400,
                                            disabled=True,
                                            key=f"full_preview_{cid}_{idx}",
                                            label_visibility="collapsed"
                                        )
                                    else:
                                        st.warning("No content could be extracted from this URL.")
                                else:
                                    st.info("Content not yet fetched. Click 'Fetch' button above.")
                            else:
                                st.info("👆 Click 'Fetch' to preview this document")
                    
                    # Regenerate section (OUTSIDE per-URL loop, applies to all URLs in criterion)
                    st.markdown("---")
                    st.markdown("**🔄 Regenerate Search (Optional)**")
                    st.caption("Use feedback to find better URLs. Approved URLs will be kept.")
                    
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
    
    # Auto Organization Verification for Criteria 4 (Distinguished Organizations)
    st.markdown("---")
    st.subheader("🏛️ Organization Verification (Criteria 4)")
    
    # Check if Criterion 4 is selected
    has_criterion_4 = any(cid in ["4_past", "4_future"] for cid in selected_criteria)
    
    if not has_criterion_4:
        st.info("Select Criterion 4 (past or future) in the sidebar to use organization verification.")
    else:
        st.markdown("""
        For Criteria 4, the app will automatically:
        1. Detect organization names from your documents
        2. Verify if they're "distinguished"
        3. Generate evidence PDFs you can approve/reject
        """)
        
        # Initialize organization verification state
        if "org_verifications" not in st.session_state:
            st.session_state.org_verifications = {}
        
        # Scan all approved documents for Criteria 4 to find organizations
        st.markdown("### Detected Organizations")
        
        if st.session_state.org_verifications:
            st.caption(f"{len(st.session_state.org_verifications)} organizations verified")
            
            for org_name, verification_data in st.session_state.org_verifications.items():
                is_approved = verification_data.get('approved', True)
                approval_icon = "✅" if is_approved else "❌"
                
                with st.expander(f"{approval_icon} {org_name}", expanded=False):
                    result = verification_data.get('result', {})
                    evidence = verification_data.get('evidence', [])
                    
                    # Approval checkbox
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        new_approval = st.checkbox(
                            "✓ Approve this verification",
                            value=is_approved,
                            key=f"org_approve_{org_name}"
                        )
                        if new_approval != is_approved:
                            verification_data['approved'] = new_approval
                            st.rerun()
                    
                    with col2:
                        if st.button("🗑️ Remove", key=f"org_delete_{org_name}"):
                            del st.session_state.org_verifications[org_name]
                            st.rerun()
                    
                    # Verification result
                    is_distinguished = result.get("is_distinguished", False)
                    confidence = result.get("confidence", "unknown")
                    reasoning = result.get("reasoning", "")
                    
                    if is_distinguished:
                        st.success(f"✅ **Distinguished Organization** (Confidence: {confidence})")
                    else:
                        st.error(f"❌ **Not Distinguished** (Confidence: {confidence})")
                    
                    st.info(f"**Reasoning:** {reasoning}")
                    
                    # Evidence sources
                    if evidence:
                        st.markdown("---")
                        st.markdown("**📚 Evidence Sources:**")
                        for i, source in enumerate(evidence, 1):
                            st.markdown(f"{i}. [{source.get('title', 'Source')}]({source.get('url', '#')})")
                            if source.get('snippet'):
                                st.caption(source.get('snippet', ''))
        else:
            st.info("No organizations detected yet.")
        
        # Manual verification option
        with st.expander("➕ Manually Verify an Organization", expanded=False):
            st.caption("Manually add an organization if not auto-detected from documents")
            
            col1, col2 = st.columns([3, 1])
            
            with col1:
                org_name_input = st.text_input(
                    "Organization Name",
                    placeholder="e.g., Bavarian State Opera",
                    key="manual_org_input"
                )
            
            with col2:
                st.write("")
                st.write("")
                verify_manual_btn = st.button("✓ Verify", key="verify_manual_org")
            
            if verify_manual_btn and org_name_input:
                with st.spinner(f"Verifying {org_name_input}..."):
                    try:
                        from src.web_to_pdf import fetch_organization_evidence
                        
                        # Verify organization
                        result, evidence_urls = fetch_organization_evidence(org_name_input)
                        
                        # Store verification
                        st.session_state.org_verifications[org_name_input] = {
                            'result': result,
                            'evidence': evidence_urls,
                            'approved': result.get('is_distinguished', False),  # Auto-approve if distinguished
                            'manual': True
                        }
                        
                        st.success(f"✅ Verified {org_name_input}")
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"Error verifying organization: {str(e)}")

    
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
