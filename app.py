"""
O-1 Visa Evidence Assistant
2-Tab Workflow: Research → Highlight & Export
"""

import streamlit as st
import streamlit.components.v1 as components
from src.prompts import CRITERIA

# Page config
st.set_page_config(
    page_title="O-1 Visa Evidence Assistant",
    page_icon="📄",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Initialize session state
def init_session_state():
    """Initialize all session state variables"""
    defaults = {
        "beneficiary_name": "",
        "beneficiary_variants": [],
        "artist_field": "",
        
        # Tab 1: Research results by criterion
        "research_results": {},      # {cid: [{url, title, excerpt, source}, ...]}
        "research_approvals": {},    # {cid: {url: True/False, ...}}
        "skip_highlighting": {},     # {cid: {filename: True/False, ...}} - True = skip highlighting
        
        # Tab 2: PDFs and highlights by criterion  
        "criterion_pdfs": {},        # {cid: {filename: bytes, ...}}
        "highlight_results": {},     # {cid: {filename: {quotes: {...}, notes: ""}, ...}}
        "highlight_approvals": {},   # {cid: {filename: {quote_text: True/False, ...}}}
        "goto_tab": None,            # "research" or "highlight" to trigger tab switch
    }
    
    for key, default in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default

init_session_state()

# App header
st.title("📄 O-1 Visa Evidence Assistant")

# Artist name input (always visible at top)
col1, col2 = st.columns([2, 1])

with col1:
    st.session_state.beneficiary_name = st.text_input(
        "Beneficiary Name",
        value=st.session_state.beneficiary_name,
        placeholder="e.g., Yo-Yo Ma",
        help="Enter the artist's full name"
    )

with col2:
    st.session_state.artist_field = st.text_input(
        "Field (optional)",
        value=st.session_state.artist_field,
        placeholder="e.g., Classical Music"
    )

# Name variants (collapsible)
with st.expander("📝 Name Variants (optional)"):
    variants_text = st.text_area(
        "Enter name variants (one per line)",
        value="\n".join(st.session_state.beneficiary_variants),
        placeholder="e.g.:\nYo Yo Ma\nYoYo Ma",
        height=80
    )
    st.session_state.beneficiary_variants = [
        v.strip() for v in variants_text.split("\n") if v.strip()
    ]

if not st.session_state.beneficiary_name:
    st.info("👆 Please enter beneficiary name to begin")
    st.stop()

st.divider()

# Create tabs
tab1, tab2 = st.tabs([
    "🔍 Research & Gather Evidence",
    "✨ Highlight & Export"
])

# ============================================================
# TAB 1: RESEARCH & GATHER EVIDENCE
# ============================================================
with tab1:
    from src.research_tab import render_research_tab
    render_research_tab()

# ============================================================
# TAB 2: HIGHLIGHT & EXPORT
# ============================================================
with tab2:
    from src.highlight_tab import render_highlight_tab
    render_highlight_tab()


# Handle programmatic tab navigation (e.g., "Next Page" / "Back")
goto_tab = st.session_state.get("goto_tab")
if goto_tab:
    tab_index = 0 if goto_tab == "research" else 1
    components.html(
        f"""
        <script>
        const tabs = window.parent.document.querySelectorAll('button[data-baseweb="tab"]');
        if (tabs.length > {tab_index}) {{
            tabs[{tab_index}].click();
        }}
        </script>
        """,
        height=0,
        width=0,
    )
    st.session_state["goto_tab"] = None
