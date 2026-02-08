"""
Highlighter Tab - Tab 2
Processes and highlights PDFs from all input sources
"""

import streamlit as st
from src.prompts import CRITERIA


def render_highlighter_tab():
    """
    Main highlighter interface.
    Shows all PDFs organized by criterion, highlights quotes.
    """
    
    st.header("✨ Highlight & Review Evidence")
    st.markdown("""
    Review and highlight quotes in your gathered evidence.
    PDFs are organized by criterion for easy export.
    """)
    
    # First, prepare all PDFs (uploads + converted URLs)
    prepare_all_pdfs()
    
    st.divider()
    
    # Count total PDFs available
    total_pdfs = sum(len(pdfs) for pdfs in st.session_state.criterion_pdfs.values())
    
    if total_pdfs == 0:
        st.info("""
        📂 **No PDFs yet!**
        
        Go to **Gather Evidence** tab to:
        - Upload PDF files
        - Add URLs to convert
        - Use AI agent to find sources
        """)
        return
    
    st.success(f"📄 **{total_pdfs} PDF(s) ready** across {len(st.session_state.criterion_pdfs)} criteria")
    
    # Highlight all button
    col1, col2 = st.columns([3, 1])
    with col1:
        if st.button("✨ Highlight All PDFs", type="primary", use_container_width=True):
            highlight_all_pdfs()
    
    with col2:
        if st.button("🗑️ Clear All", use_container_width=True):
            if st.session_state.get('confirm_clear'):
                clear_all_highlights()
                st.session_state.confirm_clear = False
                st.rerun()
            else:
                st.session_state.confirm_clear = True
                st.warning("Click again to confirm")
    
    st.divider()
    
    # Show each criterion's PDFs
    for cid in st.session_state.selected_criteria:
        if cid not in st.session_state.criterion_pdfs:
            continue
        
        pdfs = st.session_state.criterion_pdfs[cid]
        if not pdfs:
            continue
        
        desc = CRITERIA.get(cid, "")
        
        with st.expander(f"📋 Criterion ({cid}): {desc} - {len(pdfs)} PDF(s)", expanded=True):
            render_criterion_pdfs(cid, pdfs)


def prepare_all_pdfs():
    """
    Combine uploaded PDFs and converted PDFs into criterion_pdfs.
    This runs automatically to sync state.
    """
    
    # Add uploaded files to criterion_pdfs
    for cid, uploads in st.session_state.criterion_uploads.items():
        if cid not in st.session_state.criterion_pdfs:
            st.session_state.criterion_pdfs[cid] = {}
        
        for filename, pdf_bytes in uploads:
            # Add if not already there
            if filename not in st.session_state.criterion_pdfs[cid]:
                st.session_state.criterion_pdfs[cid][filename] = pdf_bytes


def render_criterion_pdfs(cid: str, pdfs: dict):
    """
    Render all PDFs for a criterion with highlight controls
    """
    
    # Bulk actions
    col1, col2 = st.columns(2)
    with col1:
        if st.button(f"✨ Highlight All in ({cid})", key=f"highlight_all_{cid}", use_container_width=True):
            highlight_criterion_pdfs(cid, pdfs)
    
    with col2:
        if st.button(f"🗑️ Remove All from ({cid})", key=f"remove_all_{cid}", use_container_width=True):
            st.session_state.criterion_pdfs[cid] = {}
            if cid in st.session_state.criterion_highlights:
                del st.session_state.criterion_highlights[cid]
            st.rerun()
    
    st.markdown("---")
    
    # Show each PDF
    for filename in pdfs.keys():
        render_single_pdf(cid, filename)


def render_single_pdf(cid: str, filename: str):
    """Render a single PDF with highlighting controls"""
    
    # Check if already highlighted
    is_highlighted = (
        cid in st.session_state.criterion_highlights and
        filename in st.session_state.criterion_highlights[cid]
    )
    
    status_icon = "✅" if is_highlighted else "⏳"
    
    col1, col2, col3 = st.columns([3, 1, 1])
    
    with col1:
        st.markdown(f"{status_icon} **{filename}**")
    
    with col2:
        if st.button("✨ Highlight", key=f"highlight_{cid}_{filename}", use_container_width=True):
            highlight_single_pdf(cid, filename)
    
    with col3:
        if st.button("🗑️ Remove", key=f"remove_{cid}_{filename}", use_container_width=True):
            del st.session_state.criterion_pdfs[cid][filename]
            if cid in st.session_state.criterion_highlights and filename in st.session_state.criterion_highlights[cid]:
                del st.session_state.criterion_highlights[cid][filename]
            st.rerun()
    
    # Show highlights if available
    if is_highlighted:
        highlights = st.session_state.criterion_highlights[cid][filename]
        quotes = highlights.get('quotes', {})
        
        total_quotes = sum(len(q_list) for q_list in quotes.values())
        
        with st.expander(f"📝 {total_quotes} quote(s) found", expanded=False):
            if total_quotes == 0:
                st.caption("No quotes found in this document")
            else:
                for criterion_id, quote_list in quotes.items():
                    if quote_list:
                        st.markdown(f"**Criterion ({criterion_id}):** {len(quote_list)} quotes")
                        for i, q in enumerate(quote_list[:3], 1):  # Show first 3
                            quote_text = q.get('quote', '')
                            strength = q.get('strength', 'medium')
                            st.caption(f"{i}. [{strength}] \"{quote_text[:100]}...\"")
                        if len(quote_list) > 3:
                            st.caption(f"... and {len(quote_list) - 3} more")
    
    st.markdown("---")


def highlight_all_pdfs():
    """Highlight all PDFs across all criteria"""
    
    total = sum(len(pdfs) for pdfs in st.session_state.criterion_pdfs.values())
    
    progress_bar = st.progress(0)
    status = st.empty()
    
    processed = 0
    
    for cid, pdfs in st.session_state.criterion_pdfs.items():
        for filename in pdfs.keys():
            status.text(f"Highlighting {filename}...")
            
            try:
                highlight_single_pdf(cid, filename, show_success=False)
            except Exception as e:
                st.error(f"Error highlighting {filename}: {e}")
            
            processed += 1
            progress_bar.progress(processed / total)
    
    progress_bar.progress(1.0)
    status.empty()
    
    st.success(f"✅ Highlighted {processed} PDF(s)!")
    st.rerun()


def highlight_criterion_pdfs(cid: str, pdfs: dict):
    """Highlight all PDFs in a criterion"""
    
    progress_bar = st.progress(0)
    status = st.empty()
    
    total = len(pdfs)
    processed = 0
    
    for filename in pdfs.keys():
        status.text(f"Highlighting {filename}...")
        
        try:
            highlight_single_pdf(cid, filename, show_success=False)
        except Exception as e:
            st.error(f"Error: {e}")
        
        processed += 1
        progress_bar.progress(processed / total)
    
    progress_bar.progress(1.0)
    status.empty()
    
    st.success(f"✅ Highlighted {processed} PDF(s) in criterion ({cid})!")
    st.rerun()


def highlight_single_pdf(cid: str, filename: str, show_success: bool = True):
    """
    Extract quotes from a single PDF and store in criterion_highlights
    """
    
    # Get PDF bytes
    pdf_bytes = st.session_state.criterion_pdfs[cid][filename]
    
    # Extract text
    from src.pdf_text import extract_text_from_pdf_bytes
    text = extract_text_from_pdf_bytes(pdf_bytes)
    
    # Get quotes using OpenAI
    from src.openai_terms import suggest_ovisa_quotes
    
    result = suggest_ovisa_quotes(
        document_text=text,
        beneficiary_name=st.session_state.beneficiary_name,
        beneficiary_variants=st.session_state.beneficiary_variants,
        selected_criteria_ids=[cid],  # Only this criterion
        feedback=None,
        user_feedback_text=None
    )
    
    # Store results
    if cid not in st.session_state.criterion_highlights:
        st.session_state.criterion_highlights[cid] = {}
    
    st.session_state.criterion_highlights[cid][filename] = {
        'quotes': result.get('by_criterion', {}),
        'notes': result.get('notes', ''),
        'pdf_bytes': pdf_bytes  # Store original PDF
    }
    
    if show_success:
        total_quotes = sum(len(q) for q in result.get('by_criterion', {}).values())
        st.success(f"✅ Found {total_quotes} quotes in {filename}")


def clear_all_highlights():
    """Clear all highlights and PDFs"""
    st.session_state.criterion_pdfs = {}
    st.session_state.criterion_highlights = {}
    st.session_state.criterion_uploads = {}
    st.session_state.criterion_urls = {}
    st.session_state.criterion_agent_results = {}
    st.success("🗑️ Cleared all data")
