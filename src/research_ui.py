import streamlit as st
from typing import Dict, List
from src.research_assistant import (
    generate_search_queries,
    verify_organization_distinguished,
    check_primary_source
)
from src.prompts import CRITERIA


def render_research_tab():
    """Render the Research Assistant tab in the Streamlit app."""
    
    st.header("🔍 Research Assistant")
    st.markdown("""
    This tool helps you find evidence for O-1 criteria by generating targeted search queries
    and verifying sources. Results are organized by criterion.
    """)
    
    # Initialize session state
    if "research_results" not in st.session_state:
        st.session_state.research_results = {}
    if "saved_urls" not in st.session_state:
        st.session_state.saved_urls = {}
    
    # Artist Information
    st.subheader("1. Artist Information")
    col1, col2 = st.columns([2, 1])
    
    with col1:
        artist_name = st.text_input(
            "Artist Name",
            placeholder="e.g., Jane Smith",
            help="Primary name of the beneficiary"
        )
    
    with col2:
        name_variants_input = st.text_area(
            "Name Variants (optional)",
            placeholder="e.g., J. Smith\nJane S. Smith",
            help="Alternative spellings or versions of the name (one per line)",
            height=100
        )
    
    name_variants = [v.strip() for v in name_variants_input.split("\n") if v.strip()]
    
    # Criterion Selection
    st.subheader("2. Select Criteria to Research")
    
    selected_criteria = []
    cols = st.columns(3)
    
    for idx, (cid, desc) in enumerate(CRITERIA.items()):
        with cols[idx % 3]:
            if st.checkbox(f"**{cid}**", key=f"research_crit_{cid}"):
                selected_criteria.append(cid)
                st.caption(desc)
    
    # Generate Search Queries
    st.subheader("3. Generate Search Queries")
    
    if st.button("🔎 Generate Search Queries", type="primary", disabled=not artist_name or not selected_criteria):
        if not artist_name:
            st.error("Please enter an artist name")
        elif not selected_criteria:
            st.error("Please select at least one criterion")
        else:
            with st.spinner("Generating targeted search queries..."):
                queries = generate_search_queries(
                    artist_name=artist_name,
                    name_variants=name_variants,
                    selected_criteria=selected_criteria,
                    criteria_descriptions=CRITERIA
                )
                st.session_state.research_results = queries
                st.success(f"Generated queries for {len(queries)} criteria!")
    
    # Display Search Queries and Results
    if st.session_state.research_results:
        st.subheader("4. Search Results")
        st.markdown("**Use these queries in Google/ChatGPT to find evidence. Add URLs below.**")
        
        for cid in selected_criteria:
            if cid in st.session_state.research_results:
                with st.expander(f"📋 Criterion {cid}: {CRITERIA.get(cid, '')}", expanded=True):
                    queries = st.session_state.research_results[cid]
                    
                    # Show generated queries
                    st.markdown("**Suggested Search Queries:**")
                    for i, query in enumerate(queries, 1):
                        st.code(query, language=None)
                        # Add copy button would be nice but requires custom component
                    
                    st.markdown("---")
                    
                    # URL input section
                    st.markdown("**📎 Add URLs Found:**")
                    
                    # Initialize saved URLs for this criterion
                    if cid not in st.session_state.saved_urls:
                        st.session_state.saved_urls[cid] = []
                    
                    # Input for new URL
                    new_url = st.text_input(
                        "Paste URL",
                        key=f"url_input_{cid}",
                        placeholder="https://example.com/article"
                    )
                    
                    col1, col2, col3 = st.columns([2, 2, 1])
                    
                    with col1:
                        url_title = st.text_input(
                            "Title/Description",
                            key=f"url_title_{cid}",
                            placeholder="Brief description"
                        )
                    
                    with col2:
                        source_type = st.selectbox(
                            "Source Type",
                            ["Review", "Announcement", "Award Notice", "Program", "Other"],
                            key=f"source_type_{cid}"
                        )
                    
                    with col3:
                        st.write("")  # Spacing
                        st.write("")  # Spacing
                        add_button = st.button("➕ Add", key=f"add_url_{cid}")
                    
                    if add_button and new_url:
                        # Validate URL
                        if not new_url.startswith("http"):
                            st.error("Please enter a valid URL starting with http:// or https://")
                        else:
                            # Check if it's a primary source for awards
                            verification_result = None
                            if cid == "1":  # Awards criterion
                                with st.spinner("Verifying primary source..."):
                                    verification_result = check_primary_source(
                                        url=new_url,
                                        title=url_title,
                                        snippet=""
                                    )
                                
                                if not verification_result.get("is_primary_source", False):
                                    st.warning(
                                        f"⚠️ This may not be a primary source: {verification_result.get('reasoning', '')}"
                                    )
                                    if not st.checkbox("Add anyway?", key=f"override_{cid}_{len(st.session_state.saved_urls[cid])}"):
                                        st.stop()
                            
                            # Add to saved URLs
                            st.session_state.saved_urls[cid].append({
                                "url": new_url,
                                "title": url_title or new_url,
                                "source_type": source_type,
                                "verification": verification_result
                            })
                            st.success("✅ URL added!")
                            st.rerun()
                    
                    # Display saved URLs
                    if st.session_state.saved_urls[cid]:
                        st.markdown("**Saved URLs:**")
                        for idx, url_data in enumerate(st.session_state.saved_urls[cid]):
                            col1, col2 = st.columns([5, 1])
                            
                            with col1:
                                st.markdown(f"**{idx + 1}.** [{url_data['title']}]({url_data['url']})")
                                st.caption(f"Type: {url_data['source_type']}")
                                
                                # Show verification status for awards
                                if url_data.get("verification"):
                                    confidence = url_data["verification"].get("confidence", "unknown")
                                    is_primary = url_data["verification"].get("is_primary_source", False)
                                    
                                    if is_primary:
                                        st.success(f"✅ Primary source (confidence: {confidence})")
                                    else:
                                        st.warning(f"⚠️ Not primary source (confidence: {confidence})")
                            
                            with col2:
                                if st.button("🗑️", key=f"delete_{cid}_{idx}"):
                                    st.session_state.saved_urls[cid].pop(idx)
                                    st.rerun()
    
    # Organization Verification Tool
    st.markdown("---")
    st.subheader("🏛️ Organization Verification Tool")
    st.markdown("Check if a venue/organization is 'distinguished' for O-1 purposes.")
    
    col1, col2 = st.columns([3, 1])
    
    with col1:
        org_name = st.text_input(
            "Organization Name",
            placeholder="e.g., Bavarian State Opera",
            key="org_verify_input"
        )
    
    with col2:
        st.write("")  # Spacing
        st.write("")  # Spacing
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
    
    # Export functionality
    if st.session_state.saved_urls:
        st.markdown("---")
        st.subheader("💾 Export Research Results")
        
        if st.button("📥 Export as JSON"):
            import json
            export_data = {
                "artist_name": artist_name,
                "name_variants": name_variants,
                "urls_by_criterion": st.session_state.saved_urls
            }
            
            json_str = json.dumps(export_data, indent=2)
            st.download_button(
                label="Download JSON",
                data=json_str,
                file_name=f"{artist_name.replace(' ', '_')}_research.json",
                mime="application/json"
            )
