import io
import zipfile

import streamlit as st
from dotenv import load_dotenv

from src.pdf_text import extract_text_from_pdf_bytes
from src.metadata import (
    autodetect_metadata,
    make_csv_template,
    parse_metadata_csv,
    merge_metadata,
)
from src.openai_terms import suggest_ovisa_quotes
from src.pdf_highlighter import annotate_pdf_bytes
from src.prompts import CRITERIA

load_dotenv()
st.set_page_config(page_title="O-1 Evidence Assistant", layout="wide")

st.title("O-1 Evidence Assistant")
st.caption("Research evidence online, then upload and highlight PDFs for your O-1 petition")

# ========================================
# Initialize session state
# ========================================
if "beneficiary_name" not in st.session_state:
    st.session_state["beneficiary_name"] = ""
if "beneficiary_variants" not in st.session_state:
    st.session_state["beneficiary_variants"] = []
if "research_results" not in st.session_state:
    st.session_state["research_results"] = {}
if "research_approvals" not in st.session_state:
    st.session_state["research_approvals"] = {}
if "research_pdfs" not in st.session_state:
    st.session_state["research_pdfs"] = {}
if "uploaded_pdfs_by_criterion" not in st.session_state:
    st.session_state["uploaded_pdfs_by_criterion"] = {}
if "ai_by_file_by_criterion" not in st.session_state:
    st.session_state["ai_by_file_by_criterion"] = {}
if "approval_by_criterion" not in st.session_state:
    st.session_state["approval_by_criterion"] = {}
if "meta_by_file" not in st.session_state:
    st.session_state["meta_by_file"] = {}

# ========================================
# MAIN TABS
# ========================================
main_tab1, main_tab2 = st.tabs(["🔍 Research Assistant", "📄 PDF Highlighter"])

# ========================================
# TAB 1: RESEARCH ASSISTANT
# ========================================
with main_tab1:
    st.header("🔍 AI Research Assistant")
    st.markdown("AI searches for evidence and shows you relevant excerpts. Approve the best ones, then convert to PDFs.")
    
    # Beneficiary name input (no criteria selection here)
    st.subheader("Beneficiary Information")
    beneficiary_name = st.text_input("Full name", value=st.session_state.get("beneficiary_name", ""), key="beneficiary_name_input")
    variants_raw = st.text_input("Name variants (comma-separated)", value="", key="variants_input")
    beneficiary_variants = [v.strip() for v in variants_raw.split(",") if v.strip()]
    
    # Update session state
    st.session_state["beneficiary_name"] = beneficiary_name
    st.session_state["beneficiary_variants"] = beneficiary_variants
    
    if not beneficiary_name:
        st.warning("⚠️ Please enter the beneficiary name above to begin.")
        st.stop()
    
    st.divider()
    
    # Search button
    st.subheader("1️⃣ Search for Evidence")
    
    col1, col2 = st.columns([1, 1])
    with col1:
        search_btn = st.button("🔎 Search All Criteria", type="primary", key="research_search_btn")
    with col2:
        clear_btn = st.button("Clear all results", key="research_clear_btn")
    
    if clear_btn:
        st.session_state.research_results = {}
        st.session_state.research_approvals = {}
        st.session_state.research_pdfs = {}
        st.success("Cleared.")
        st.rerun()
    
    if search_btn:
        with st.spinner("🤖 AI is searching all criteria... This may take 1-2 minutes."):
            try:
                from src.ai_research import ai_search_for_evidence
                
                # Search ALL criteria
                all_criteria = list(CRITERIA.keys())
                
                results = ai_search_for_evidence(
                    artist_name=beneficiary_name,
                    name_variants=beneficiary_variants,
                    selected_criteria=all_criteria,
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
                st.info("💡 Tip: Check artist name spelling. Try searching manually first to verify online presence.")
    
    if not st.session_state.research_results:
        st.info("Click 'Search All Criteria' to begin.")
        st.stop()
    
    st.divider()
    
    # ========================================
    # CRITERION SELECTION (Vertical dropdown instead of horizontal tabs)
    # ========================================
    st.subheader("2️⃣ Review Results by Criterion")
    
    # Create dropdown for criterion selection
    criterion_options = {f"({cid}) {CRITERIA[cid]}": cid for cid in CRITERIA.keys()}
    selected_criterion_label = st.selectbox(
        "Select criterion to review:",
        options=list(criterion_options.keys()),
        key="research_criterion_selector"
    )
    
    cid = criterion_options[selected_criterion_label]
    criterion_desc = CRITERIA[cid]
    
    # Display selected criterion
    st.markdown(f"### Criterion ({cid})")
    st.markdown(f"**{criterion_desc}**")
    st.divider()
    
    if cid not in st.session_state.research_results:
        st.info("No results found for this criterion. Try searching again.")
    else:
        items = st.session_state.research_results[cid]
        
        with st.expander(f"📋 {len(items)} sources found - Click to review", expanded=False):
            if not items:
                st.write("No sources found.")
            else:
                
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
            
            # Display each source
            for i, item in enumerate(items):
                url = item['url']
                title = item['title']
                source = item.get('source', 'Unknown')
                relevance = item.get('relevance', '')
                excerpt = item.get('excerpt', '')
                
                # Approval checkbox
                is_approved = approvals.get(url, True)
                
                display_text = f"**[{source}]** {title}"
                
                new_approval = st.checkbox(
                    display_text,
                    value=is_approved,
                    key=f"approve_{cid}_{i}"
                )
                approvals[url] = new_approval
                
                # Show details
                if relevance:
                    st.caption(f"**Why relevant:** {relevance}")
                if excerpt:
                    st.caption(f"**Excerpt:** \"{excerpt}\"")
                
                st.caption(f"🔗 {url}")
                st.markdown("---")
            
            st.session_state.research_approvals[cid] = approvals
            
            # Show counts
            approved = [url for url, ok in approvals.items() if ok]
            rejected = [url for url, ok in approvals.items() if not ok]
            st.write(f"✅ Approved: **{len(approved)}** | ❌ Rejected: **{len(rejected)}**")
            
            # Regenerate
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
            
            # Convert approved sources to PDFs for this criterion
            st.subheader("3️⃣ Convert Approved Sources to PDFs")
            
            approved_count = sum(1 for url, ok in st.session_state.research_approvals.get(cid, {}).items() if ok)
            
            if approved_count == 0:
            st.info("No sources approved. Approve sources above to convert them.")
            else:
            st.markdown(f"**{approved_count} approved sources** ready for conversion.")
            
            if st.button(f"📄 Convert to PDFs ({approved_count} sources)", type="primary", key=f"convert_{cid}"):
                with st.spinner(f"Converting {approved_count} sources..."):
                    try:
                        from src.web_to_pdf import batch_convert_urls_to_pdfs
                        
                        # Prepare approved URLs for this criterion only
                        items = st.session_state.research_results[cid]
                        approvals = st.session_state.research_approvals.get(cid, {})
                        
                        approved_items = [
                            {"url": item['url'], "title": item['title']}
                            for item in items
                            if approvals.get(item['url'], False)
                        ]
                        
                        if not approved_items:
                            st.warning("No approved items to convert.")
                            continue
                        
                        approved_by_criterion = {cid: approved_items}
                        
                        # Convert
                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        
                        def progress_callback(processed, total, message):
                            if total > 0:
                                progress_bar.progress(min(processed / total, 1.0))
                            status_text.text(message)
                        
                        pdfs = batch_convert_urls_to_pdfs(
                            approved_by_criterion,
                            progress_callback=progress_callback
                        )
                        
                        # Save to session state
                        if cid not in st.session_state.research_pdfs:
                            st.session_state.research_pdfs[cid] = {}
                        st.session_state.research_pdfs[cid].update(pdfs.get(cid, {}))
                        
                        progress_bar.progress(1.0)
                        status_text.text("✅ Done!")
                        
                        total_converted = len(pdfs.get(cid, {}))
                        
                        if total_converted > 0:
                            st.success(f"""
                            ✅ Converted {total_converted} sources for Criterion ({cid})!
                            
                            Switch to **PDF Highlighter** tab and go to Criterion ({cid}) to analyze them.
                            """)
                        else:
                            st.warning("⚠️ No PDFs were converted. Check the error messages above.")
                        
                    except Exception as e:
                            import traceback
                            st.error(f"Error: {str(e)}")
                            with st.expander("Full error traceback"):
                                st.code(traceback.format_exc())


# ========================================
# TAB 2: PDF HIGHLIGHTER
# ========================================
with main_tab2:
    st.header("📄 PDF Highlighter")
    st.caption("Analyze PDFs (converted from Research or uploaded) and highlight evidence for each criterion")
    
    if not st.session_state.get("beneficiary_name"):
        st.warning("⚠️ Enter the beneficiary name in the Research tab first.")
        st.stop()
    
    beneficiary_name = st.session_state["beneficiary_name"]
    beneficiary_variants = st.session_state.get("beneficiary_variants", [])
    
    st.info(f"**Beneficiary:** {beneficiary_name}")
    
    st.divider()
    
    # ========================================
    # CRITERION SELECTION (Vertical dropdown instead of horizontal tabs)
    # ========================================
    st.subheader("Analyze PDFs by Criterion")
    
    # Create dropdown for criterion selection
    highlighter_criterion_options = {f"({cid}) {CRITERIA[cid]}": cid for cid in CRITERIA.keys()}
    selected_highlighter_label = st.selectbox(
        "Select criterion to analyze:",
        options=list(highlighter_criterion_options.keys()),
        key="highlighter_criterion_selector"
    )
    
    cid = highlighter_criterion_options[selected_highlighter_label]
    criterion_desc = CRITERIA[cid]
    
    # Display selected criterion
    st.markdown(f"### Criterion ({cid})")
    st.markdown(f"**{criterion_desc}**")
    st.divider()
    
    # ========================================
    # File upload for this criterion
    # ========================================
    st.subheader("📂 Documents")
        
        # Show research PDFs for this criterion
        research_pdfs = st.session_state.research_pdfs.get(cid, {})
        if research_pdfs:
            st.success(f"✅ {len(research_pdfs)} PDFs ready from Research tab")
        
        # Upload additional PDFs for this criterion
        uploaded_files = st.file_uploader(
            f"Upload additional PDFs for Criterion ({cid})",
            type=["pdf"],
            accept_multiple_files=True,
            key=f"uploader_{cid}"
        )
        
        # Combine research PDFs and uploaded files
        all_files = []
        
        # Add research PDFs
        if research_pdfs:
            for filename, pdf_bytes in research_pdfs.items():
                virtual_file = io.BytesIO(pdf_bytes)
                virtual_file.name = f"[Research] {filename}"
                virtual_file.seek(0)
                all_files.append(virtual_file)
        
        # Add uploaded files
        if uploaded_files:
            all_files.extend(uploaded_files)
        
        if not all_files:
            st.info("👆 Upload PDFs or convert documents in the Research tab for this criterion.")
            continue
        
        st.write(f"**{len(all_files)} documents** ready for analysis")
        
        st.divider()
        
        # ========================================
        # AI Analysis
        # ========================================
        st.subheader("🤖 AI Quote Extraction")
        
        if st.button(f"Generate quotes for all PDFs", type="primary", key=f"gen_all_{cid}"):
            progress = st.progress(0)
            status = st.empty()
            
            for idx, f in enumerate(all_files):
                status.text(f"Processing {f.name}...")
                
                try:
                    # Read PDF
                    if isinstance(f, io.BytesIO):
                        pdf_bytes = f.getvalue()
                    else:
                        pdf_bytes = f.getvalue()
                    
                    text = extract_text_from_pdf_bytes(pdf_bytes)
                    
                    # Auto-detect metadata
                    try:
                        auto_meta = autodetect_metadata(text)
                    except Exception:
                        auto_meta = {"source_url": "", "venue_name": "", "ensemble_name": "", "performance_date": ""}
                    
                    st.session_state["meta_by_file"][f.name] = auto_meta
                    
                    # Generate quotes
                    data = suggest_ovisa_quotes(
                        document_text=text,
                        beneficiary_name=beneficiary_name,
                        beneficiary_variants=beneficiary_variants,
                        selected_criteria_ids=[cid],  # Only this criterion
                        feedback=None,
                        user_feedback_text=None,
                    )
                    
                    # Store results
                    if cid not in st.session_state.ai_by_file_by_criterion:
                        st.session_state.ai_by_file_by_criterion[cid] = {}
                    st.session_state.ai_by_file_by_criterion[cid][f.name] = data
                    
                    # Initialize approvals
                    if cid not in st.session_state.approval_by_criterion:
                        st.session_state.approval_by_criterion[cid] = {}
                    if f.name not in st.session_state.approval_by_criterion[cid]:
                        st.session_state.approval_by_criterion[cid][f.name] = {}
                    
                    items = data.get("by_criterion", {}).get(cid, [])
                    st.session_state.approval_by_criterion[cid][f.name] = {
                        it["quote"]: True for it in items
                    }
                    
                except Exception as e:
                    st.error(f"Error processing {f.name}: {e}")
                
                progress.progress((idx + 1) / len(all_files))
            
            status.text("✅ Done!")
            st.success("All PDFs analyzed!")
            st.rerun()
        
        st.divider()
        
        # ========================================
        # Show quotes for each file with dropdown
        # ========================================
        st.subheader("📝 Review & Approve Quotes")
        
        ai_results = st.session_state.ai_by_file_by_criterion.get(cid, {})
        
        if not ai_results:
            st.info("Click 'Generate quotes for all PDFs' above to begin.")
            continue
        
        for f in all_files:
            data = ai_results.get(f.name)
            
            if not data:
                continue
            
            # Dropdown for each file
            with st.expander(f"📄 {f.name}", expanded=False):
                notes = data.get("notes", "")
                if notes:
                    st.info(f"**AI notes:** {notes}")
                
                by_criterion = data.get("by_criterion", {})
                items = by_criterion.get(cid, [])
                
                if not items:
                    st.write("No candidates found in this document.")
                    continue
                
                # Bulk actions
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("✅ Approve all", key=f"approve_all_{cid}_{f.name}"):
                        st.session_state.approval_by_criterion[cid][f.name] = {
                            it["quote"]: True for it in items
                        }
                        st.rerun()
                with col2:
                    if st.button("❌ Reject all", key=f"reject_all_{cid}_{f.name}"):
                        st.session_state.approval_by_criterion[cid][f.name] = {
                            it["quote"]: False for it in items
                        }
                        st.rerun()
                
                st.markdown("---")
                
                # Get approvals
                if cid not in st.session_state.approval_by_criterion:
                    st.session_state.approval_by_criterion[cid] = {}
                if f.name not in st.session_state.approval_by_criterion[cid]:
                    st.session_state.approval_by_criterion[cid][f.name] = {}
                
                approvals = st.session_state.approval_by_criterion[cid][f.name]
                
                # Show each quote
                for i, it in enumerate(items):
                    q = it["quote"]
                    strength = it.get("strength", "medium")
                    label = f"[{strength}] {q}"
                    
                    approvals[q] = st.checkbox(
                        label,
                        value=approvals.get(q, True),
                        key=f"chk_{cid}_{f.name}_{i}"
                    )
                
                st.session_state.approval_by_criterion[cid][f.name] = approvals
                
                # Show counts
                approved = [q for q, ok in approvals.items() if ok]
                rejected = [q for q, ok in approvals.items() if not ok]
                st.write(f"✅ Approved: **{len(approved)}** | ❌ Rejected: **{len(rejected)}**")
                
                st.markdown("---")
                
                # Regenerate
                st.markdown("**🔄 Regenerate with feedback**")
                
                user_feedback = st.text_area(
                    "Optional instruction",
                    placeholder="e.g., 'focus only on critical acclaim'",
                    key=f"feedback_{cid}_{f.name}",
                    height=60
                )
                
                if st.button("🔄 Regenerate", key=f"regen_{cid}_{f.name}"):
                    with st.spinner("Regenerating..."):
                        try:
                            # Read PDF
                            if isinstance(f, io.BytesIO):
                                pdf_bytes = f.getvalue()
                            else:
                                pdf_bytes = f.getvalue()
                            
                            text = extract_text_from_pdf_bytes(pdf_bytes)
                            
                            approved_examples = [q for q, ok in approvals.items() if ok]
                            rejected_examples = [q for q, ok in approvals.items() if not ok]
                            
                            feedback = {
                                "approved_examples": approved_examples[:15],
                                "rejected_examples": rejected_examples[:15],
                            }
                            
                            new_data = suggest_ovisa_quotes(
                                document_text=text,
                                beneficiary_name=beneficiary_name,
                                beneficiary_variants=beneficiary_variants,
                                selected_criteria_ids=[cid],
                                feedback=feedback,
                                user_feedback_text=user_feedback,
                            )
                            
                            st.session_state.ai_by_file_by_criterion[cid][f.name] = new_data
                            
                            items = new_data.get("by_criterion", {}).get(cid, [])
                            st.session_state.approval_by_criterion[cid][f.name] = {
                                it["quote"]: True for it in items
                            }
                            
                            st.success("Regenerated!")
                            st.rerun()
                            
                        except Exception as e:
                            st.error(f"Error: {e}")
                
                st.markdown("---")
                
                # Export this file
                if approved:
                    if st.button(f"📥 Export highlighted PDF", key=f"export_{cid}_{f.name}"):
                        with st.spinner("Creating highlighted PDF..."):
                            try:
                                if isinstance(f, io.BytesIO):
                                    pdf_bytes = f.getvalue()
                                else:
                                    pdf_bytes = f.getvalue()
                                
                                resolved = st.session_state["meta_by_file"].get(f.name, {}) or {}
                                
                                meta = {
                                    "source_url": resolved.get("source_url") or "",
                                    "venue_name": resolved.get("venue_name") or "",
                                    "ensemble_name": resolved.get("ensemble_name") or "",
                                    "performance_date": resolved.get("performance_date") or "",
                                    "beneficiary_name": beneficiary_name,
                                    "beneficiary_variants": beneficiary_variants,
                                }
                                
                                out_bytes, report = annotate_pdf_bytes(
                                    pdf_bytes,
                                    approved,
                                    criterion_id=cid,
                                    meta=meta
                                )
                                
                                out_name = f.name.replace(".pdf", f"_criterion-{cid}_highlighted.pdf")
                                
                                st.success(f"✅ Highlighted {report.get('total_quote_hits', 0)} quotes")
                                
                                st.download_button(
                                    f"⬇️ Download {out_name}",
                                    data=out_bytes,
                                    file_name=out_name,
                                    mime="application/pdf",
                                    key=f"dl_{cid}_{f.name}",
                                )
                                
                            except Exception as e:
                                st.error(f"Error: {e}")
        
        st.divider()
        
        # ========================================
        # Export all for this criterion
        # ========================================
        st.subheader("📦 Export All PDFs")
        
        if st.button(f"Export all highlighted PDFs as ZIP", type="primary", key=f"zip_{cid}"):
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
                for f in all_files:
                    data = ai_results.get(f.name)
                    if not data:
                        continue
                    
                    if cid not in st.session_state.approval_by_criterion:
                        continue
                    if f.name not in st.session_state.approval_by_criterion[cid]:
                        continue
                    
                    approvals = st.session_state.approval_by_criterion[cid][f.name]
                    approved_quotes = [q for q, ok in approvals.items() if ok]
                    
                    if not approved_quotes:
                        continue
                    
                    if isinstance(f, io.BytesIO):
                        pdf_bytes = f.getvalue()
                    else:
                        pdf_bytes = f.getvalue()
                    
                    resolved = st.session_state["meta_by_file"].get(f.name, {}) or {}
                    
                    meta = {
                        "source_url": resolved.get("source_url") or "",
                        "venue_name": resolved.get("venue_name") or "",
                        "ensemble_name": resolved.get("ensemble_name") or "",
                        "performance_date": resolved.get("performance_date") or "",
                        "beneficiary_name": beneficiary_name,
                        "beneficiary_variants": beneficiary_variants,
                    }
                    
                    out_bytes, report = annotate_pdf_bytes(
                        pdf_bytes,
                        approved_quotes,
                        criterion_id=cid,
                            meta=meta
                        )
                        
                        out_name = f.name.replace(".pdf", f"_criterion-{cid}_highlighted.pdf")
                        zf.writestr(out_name, out_bytes)
                
                zip_buffer.seek(0)
                
                st.download_button(
                    f"⬇️ Download ZIP for Criterion ({cid})",
                    data=zip_buffer.getvalue(),
                    file_name=f"criterion-{cid}_highlighted_pdfs.zip",
                    mime="application/zip",
                    key=f"dl_zip_{cid}"
                )

st.divider()
st.caption("O-1 Evidence Assistant • AI-powered research and PDF highlighting")
