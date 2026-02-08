"""
O-1 Visa Evidence Assistant - Restructured App
Three input methods for each criterion: Upload, URL, AI Agent
"""

import streamlit as st
from src.prompts import CRITERIA

# Page config
st.set_page_config(
    page_title="O-1 Visa Evidence Assistant",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Initialize session state
def init_session_state():
    """Initialize all session state variables"""
    defaults = {
        "beneficiary_name": "",
        "beneficiary_variants": [],
        "selected_criteria": [],
        "artist_field": "",
        
        # Store inputs by criterion - each can have multiple sources
        "criterion_uploads": {},      # {cid: [(filename, bytes), ...]}
        "criterion_urls": {},          # {cid: [url1, url2, ...]}
        "criterion_agent_results": {}, # {cid: [{url, title, ...}, ...]}
        
        # Processed PDFs ready for highlighting
        "criterion_pdfs": {},          # {cid: {filename: bytes, ...}}
        
        # Highlighting results
        "criterion_highlights": {},    # {cid: {filename: {quotes, metadata}, ...}}
    }
    
    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default

init_session_state()

# Sidebar - Global Settings
with st.sidebar:
    st.header("⚙️ Global Settings")
    
    st.session_state.beneficiary_name = st.text_input(
        "Beneficiary Name",
        value=st.session_state.beneficiary_name,
        placeholder="e.g., Yo-Yo Ma"
    )
    
    variants_text = st.text_area(
        "Name Variants (one per line)",
        value="\n".join(st.session_state.beneficiary_variants),
        placeholder="e.g.:\nYo Yo Ma\nYoYo Ma",
        height=80
    )
    st.session_state.beneficiary_variants = [
        v.strip() for v in variants_text.split("\n") if v.strip()
    ]
    
    st.session_state.artist_field = st.text_input(
        "Field (optional)",
        value=st.session_state.artist_field,
        placeholder="e.g., Classical Music"
    )
    
    st.divider()
    
    st.subheader("Select Criteria")
    st.caption("Choose which criteria to gather evidence for")
    
    selected = []
    for cid, desc in CRITERIA.items():
        if st.checkbox(
            f"({cid}) {desc[:50]}...",
            value=cid in st.session_state.selected_criteria,
            key=f"select_{cid}"
        ):
            selected.append(cid)
    
    st.session_state.selected_criteria = selected
    
    if not st.session_state.beneficiary_name:
        st.warning("⚠️ Please enter beneficiary name")
    
    if not st.session_state.selected_criteria:
        st.warning("⚠️ Please select at least one criterion")

# Main App
st.title("📄 O-1 Visa Evidence Assistant")

if not st.session_state.beneficiary_name or not st.session_state.selected_criteria:
    st.info("""
    👈 **Get started:**
    1. Enter beneficiary name in sidebar
    2. Select criteria to work on
    3. Choose a tab below to begin gathering evidence
    """)
    st.stop()

# Create tabs
tab1, tab2, tab3, tab4 = st.tabs([
    "📂 Gather Evidence",
    "✨ Highlight & Review", 
    "💬 ChatGPT Helper",
    "📦 Export Package"
])

# ============================================================
# TAB 1: GATHER EVIDENCE
# ============================================================
with tab1:
    from src.evidence_gatherer import render_evidence_gatherer
    render_evidence_gatherer()

# ============================================================
# TAB 2: HIGHLIGHT & REVIEW
# ============================================================
with tab2:
    from src.highlighter_tab import render_highlighter_tab
    render_highlighter_tab()

# ============================================================
# TAB 3: CHATGPT HELPER
# ============================================================
with tab3:
    from src.chatgpt_helper import show_chatgpt_helper
    show_chatgpt_helper()

# ============================================================
# TAB 4: EXPORT PACKAGE
# ============================================================
with tab4:
    from src.export_package import render_export_tab
    render_export_tab()
