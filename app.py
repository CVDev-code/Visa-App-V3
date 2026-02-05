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
from src.research_ui_enhanced import render_research_tab

load_dotenv()
st.set_page_config(page_title="O-1 Evidence Assistant", layout="wide")

st.title("O-1 Evidence Assistant")
st.caption("Research evidence online, then upload and highlight PDFs for your O-1 petition")

# ========================================
# SIDEBAR: Unified Configuration
# ========================================
with st.sidebar:
    st.header("⚙️ Case Configuration")
    st.markdown("*These settings apply to both tabs*")
    
    # Beneficiary Information
    st.subheader("Beneficiary")
    beneficiary_name = st.text_input("Full name", value="", key="beneficiary_name_input")
    variants_raw = st.text_input("Name variants (comma-separated)", value="", key="variants_input")
    beneficiary_variants = [v.strip() for v in variants_raw.split(",") if v.strip()]
    
    # Store in session state for both tabs
    st.session_state["beneficiary_name"] = beneficiary_name
    st.session_state["beneficiary_variants"] = beneficiary_variants
    
    st.divider()
    
    # Unified Criteria Selection
    st.subheader("O-1 Criteria")
    st.caption("Select criteria for research AND highlighting")
    
    default_criteria = ["2_past", "2_future", "3", "4_past", "4_future"]
    selected_criteria_ids: list[str] = []
    
    for cid, desc in CRITERIA.items():
        checked = st.checkbox(
            f"**({cid})** {desc[:50]}...",  # Truncate for sidebar
            value=(cid in default_criteria),
            key=f"unified_crit_{cid}"
        )
        if checked:
            selected_criteria_ids.append(cid)
    
    # Store in session state for both tabs
    st.session_state["selected_criteria"] = selected_criteria_ids
    
    st.divider()
    st.caption("💡 Tip: Select criteria once - they'll be used in both Research and PDF Highlighter tabs")

# ========================================
# TABS
# ========================================
tab1, tab2 = st.tabs(["🔍 Research Assistant", "📄 PDF Highlighter"])

# ========================================
# TAB 1: RESEARCH ASSISTANT
# ========================================
with tab1:
    render_research_tab()

# ========================================
# TAB 2: PDF HIGHLIGHTER
# ========================================
with tab2:
    st.caption(
        "Upload PDFs (or use converted ones from Research tab) → approve/reject quotes → export highlighted PDFs"
    )

    # Check if we have PDFs from Research tab
    research_pdfs = st.session_state.get("research_pdfs", {})
    has_research_pdfs = any(research_pdfs.values())
    
    if has_research_pdfs:
        st.success(f"""
        ✅ {sum(len(pdfs) for pdfs in research_pdfs.values())} PDFs ready from Research tab!
        
        These PDFs will be automatically processed. You can also upload additional PDFs below.
        """)
    
    # File uploader (can still upload additional files)
    uploaded_files = st.file_uploader(
        "Upload additional PDF files (optional if using Research PDFs)",
        type=["pdf"],
        accept_multiple_files=True,
    )
    
    # Combine uploaded files with research PDFs
    all_files = []
    
    # Add uploaded files
    if uploaded_files:
        all_files.extend(uploaded_files)
    
    # Add research PDFs as virtual files
    if research_pdfs:
        for criterion_id, pdfs_dict in research_pdfs.items():
            for filename, pdf_bytes in pdfs_dict.items():
                # Create a virtual file object
                virtual_file = io.BytesIO(pdf_bytes)
                virtual_file.name = f"[Research] {filename}"
                virtual_file.seek(0)
                all_files.append(virtual_file)
    
    if not all_files:
        st.info("👆 Upload PDFs or convert documents in the Research tab to begin.")
        st.stop()

    if not beneficiary_name.strip():
        st.warning("⚠️ Enter the beneficiary full name in the sidebar.")
        st.stop()

    if not selected_criteria_ids:
        st.warning("⚠️ Select at least one O-1 criterion in the sidebar.")
        st.stop()

    st.divider()

    # -------------------------
    # Session state
    # -------------------------
    if "ai_by_file" not in st.session_state:
        st.session_state["ai_by_file"] = {}

    if "approval" not in st.session_state:
        st.session_state["approval"] = {}

    if "csv_metadata" not in st.session_state:
        st.session_state["csv_metadata"] = None

    if "overrides_by_file" not in st.session_state:
        st.session_state["overrides_by_file"] = {}

    if "meta_by_file" not in st.session_state:
        st.session_state["meta_by_file"] = {}

    if "regen_user_feedback" not in st.session_state:
        st.session_state["regen_user_feedback"] = {}

    # -------------------------
    # Metadata
    # -------------------------
    st.subheader("🧾 Metadata (AI-detected, override if needed)")

    csv_data = None
    if len(all_files) > 1:
        with st.expander("CSV metadata overrides (bulk mode)", expanded=False):
            filenames = [f.name for f in all_files]
            template_bytes = make_csv_template(filenames)

            st.download_button(
                "⬇️ Download CSV template",
                data=template_bytes,
                file_name="o1_metadata_template.csv",
                mime="text/csv",
            )

            csv_file = st.file_uploader(
                "Upload filled CSV (optional)",
                type=["csv"],
                accept_multiple_files=False,
                key="metadata_csv_uploader",
            )

            if csv_file is not None:
                try:
                    st.session_state["csv_metadata"] = parse_metadata_csv(csv_file.getvalue())
                    applied = len([fn for fn in filenames if fn in st.session_state["csv_metadata"]])
                    st.success(f"CSV loaded. Rows matched to {applied}/{len(filenames)} uploaded PDFs.")
                except Exception as e:
                    st.session_state["csv_metadata"] = None
                    st.error(f"Could not parse CSV: {e}")

        csv_data = st.session_state.get("csv_metadata")

    # Compute & show AI metadata per file
    for f in all_files:
        # Read PDF bytes
        if isinstance(f, io.BytesIO):
            pdf_bytes = f.getvalue()
        else:
            pdf_bytes = f.getvalue()
        
        full_text = extract_text_from_pdf_bytes(pdf_bytes)

        try:
            auto = autodetect_metadata(full_text)
        except Exception as e:
            auto = {"source_url": "", "venue_name": "", "ensemble_name": "", "performance_date": ""}
            st.warning(f"Metadata AI failed for {f.name}: {e}")

        overrides = st.session_state["overrides_by_file"].get(f.name, {})
        resolved = merge_metadata(
            filename=f.name,
            auto=auto,
            csv_data=csv_data,
            overrides=overrides,
        )
        st.session_state["meta_by_file"][f.name] = resolved

        with st.expander(f"Metadata overrides for: {f.name}", expanded=False):
            st.caption("AI is the default. Type anything below to override (or use CSV in bulk mode).")

            o = dict(overrides)

            o["source_url"] = st.text_input(
                "Source URL override",
                value=o.get("source_url", "") or (resolved.get("source_url") or ""),
                key=f"url_{f.name}",
            ).strip()

            o["venue_name"] = st.text_input(
                "Venue / organisation override",
                value=o.get("venue_name", "") or (resolved.get("venue_name") or ""),
                key=f"venue_{f.name}",
            ).strip()

            o["ensemble_name"] = st.text_input(
                "Ensemble / orchestra / choir override",
                value=o.get("ensemble_name", "") or (resolved.get("ensemble_name") or ""),
                key=f"ensemble_{f.name}",
            ).strip()

            o["performance_date"] = st.text_input(
                "Performance date override",
                value=o.get("performance_date", "") or (resolved.get("performance_date") or ""),
                key=f"date_{f.name}",
            ).strip()

            st.session_state["overrides_by_file"][f.name] = {k: v for k, v in o.items() if v}

            st.write("Resolved metadata preview:")
            st.json(st.session_state["meta_by_file"][f.name])

    st.divider()

    # -------------------------
    # Step 1: Generate AI quotes
    # -------------------------
    st.subheader("1️⃣ Generate criterion-tagged quote candidates (AI)")

    colA, colB = st.columns([1, 1])
    with colA:
        run_ai = st.button("Generate for all PDFs", type="primary")
    with colB:
        clear = st.button("Clear results")

    if clear:
        st.session_state["ai_by_file"] = {}
        st.session_state["approval"] = {}
        st.success("Cleared AI results and approvals.")

    if run_ai:
        with st.spinner("Reading PDFs and generating quote candidates…"):
            for f in all_files:
                if isinstance(f, io.BytesIO):
                    pdf_bytes = f.getvalue()
                else:
                    pdf_bytes = f.getvalue()
                    
                text = extract_text_from_pdf_bytes(pdf_bytes)
                data = suggest_ovisa_quotes(
                    document_text=text,
                    beneficiary_name=beneficiary_name,
                    beneficiary_variants=beneficiary_variants,
                    selected_criteria_ids=selected_criteria_ids,
                    feedback=None,
                    user_feedback_text=None,
                )
                st.session_state["ai_by_file"][f.name] = data

                if f.name not in st.session_state["approval"]:
                    st.session_state["approval"][f.name] = {}
                for cid in selected_criteria_ids:
                    items = data.get("by_criterion", {}).get(cid, [])
                    st.session_state["approval"][f.name][cid] = {it["quote"]: True for it in items}

        st.success("Done. Review and approve/reject per criterion below.")

    st.divider()

    # -------------------------
    # Step 2: Approve/Reject
    # -------------------------
    st.subheader("2️⃣ Approve / Reject quotes by criterion")

    for f in all_files:
        st.markdown(f"## 📄 {f.name}")

        data = st.session_state["ai_by_file"].get(f.name)
        if not data:
            st.info("No AI results yet for this PDF. Click 'Generate for all PDFs'.")
            continue

        notes = data.get("notes", "")
        if notes:
            with st.expander("AI notes"):
                st.write(notes)

        by_criterion = data.get("by_criterion", {})

        uf_key = f"user_feedback_{f.name}"
        st.session_state["regen_user_feedback"].setdefault(f.name, "")
        user_feedback = st.text_area(
            "Optional instruction for regeneration (e.g. 'focus only on critical acclaim and named roles; avoid generic praise').",
            value=st.session_state["regen_user_feedback"][f.name],
            key=uf_key,
            height=80,
        )
        st.session_state["regen_user_feedback"][f.name] = user_feedback

        regen_col1, regen_col2 = st.columns([1, 3])
        with regen_col1:
            regen_btn = st.button("Regenerate with my feedback", key=f"regen_{f.name}")
        with regen_col2:
            st.caption("Tip: Approve/reject quotes below, add an instruction above, then regenerate.")

        if regen_btn:
            approved_examples = []
            rejected_examples = []
            for cid in selected_criteria_ids:
                approvals = st.session_state["approval"].get(f.name, {}).get(cid, {})
                for q, ok in approvals.items():
                    (approved_examples if ok else rejected_examples).append(q)

            feedback = {
                "approved_examples": approved_examples[:15],
                "rejected_examples": rejected_examples[:15],
            }

            with st.spinner("Regenerating with your feedback…"):
                if isinstance(f, io.BytesIO):
                    pdf_bytes = f.getvalue()
                else:
                    pdf_bytes = f.getvalue()
                    
                text = extract_text_from_pdf_bytes(pdf_bytes)
                new_data = suggest_ovisa_quotes(
                    document_text=text,
                    beneficiary_name=beneficiary_name,
                    beneficiary_variants=beneficiary_variants,
                    selected_criteria_ids=selected_criteria_ids,
                    feedback=feedback,
                    user_feedback_text=user_feedback,
                )

            st.session_state["ai_by_file"][f.name] = new_data

            st.session_state["approval"][f.name] = {}
            for cid in selected_criteria_ids:
                items = new_data.get("by_criterion", {}).get(cid, [])
                st.session_state["approval"][f.name][cid] = {it["quote"]: True for it in items}

            st.success("Regenerated. Review the updated lists below.")
            st.rerun()

        for cid in selected_criteria_ids:
            crit_title = f"Criterion ({cid})"
            crit_desc = CRITERIA.get(cid, "")
            items = by_criterion.get(cid, [])

            with st.expander(
                f"{crit_title}: {crit_desc}",
                expanded=(cid.startswith(("2", "4")) or cid == "3"),
            ):
                if not items:
                    st.write("No candidates found for this criterion in this document.")
                    continue

                b1, b2, b3 = st.columns([1, 1, 2])
                with b1:
                    if st.button("Approve all", key=f"approve_all_{f.name}_{cid}"):
                        st.session_state["approval"][f.name][cid] = {it["quote"]: True for it in items}
                with b2:
                    if st.button("Reject all", key=f"reject_all_{f.name}_{cid}"):
                        st.session_state["approval"][f.name][cid] = {it["quote"]: False for it in items}

                approvals = st.session_state["approval"].get(f.name, {}).get(cid, {})

                for i, it in enumerate(items):
                    q = it["quote"]
                    strength = it.get("strength", "medium")
                    label = f"[{strength}] {q}"
                    approvals[q] = st.checkbox(
                        label,
                        value=approvals.get(q, True),
                        key=f"chk_{f.name}_{cid}_{i}",
                    )

                st.session_state["approval"][f.name][cid] = approvals

                approved = [q for q, ok in approvals.items() if ok]
                rejected = [q for q, ok in approvals.items() if not ok]
                st.write(f"✅ Approved: **{len(approved)}** | ❌ Rejected: **{len(rejected)}**")

    st.divider()

    # -------------------------
    # Step 3: Export
    # -------------------------
    st.subheader("3️⃣ Export highlighted PDFs by criterion")


    def build_annotated_pdf_bytes(pdf_bytes: bytes, quotes: list[str], criterion_id: str, filename: str):
        resolved = st.session_state["meta_by_file"].get(filename, {}) or {}

        meta = {
            "source_url": resolved.get("source_url") or "",
            "venue_name": resolved.get("venue_name") or "",
            "ensemble_name": resolved.get("ensemble_name") or "",
            "performance_date": resolved.get("performance_date") or "",
            "beneficiary_name": beneficiary_name,
            "beneficiary_variants": beneficiary_variants,
        }

        return annotate_pdf_bytes(pdf_bytes, quotes, criterion_id=criterion_id, meta=meta)


    zip_btn = st.button("Export ALL selected criteria as ZIP (all PDFs)", type="primary")

    zip_buffer = None
    if zip_btn:
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for f in all_files:
                data = st.session_state["ai_by_file"].get(f.name)
                if not data:
                    continue
                for cid in selected_criteria_ids:
                    approvals = st.session_state["approval"].get(f.name, {}).get(cid, {})
                    approved_quotes = [q for q, ok in approvals.items() if ok]
                    if not approved_quotes:
                        continue

                    if isinstance(f, io.BytesIO):
                        pdf_bytes = f.getvalue()
                    else:
                        pdf_bytes = f.getvalue()

                    out_bytes, report = build_annotated_pdf_bytes(
                        pdf_bytes,
                        approved_quotes,
                        cid,
                        filename=f.name,
                    )
                    out_name = f.name.replace(".pdf", f"_criterion-{cid}_highlighted.pdf")
                    zf.writestr(out_name, out_bytes)

        zip_buffer.seek(0)

    if zip_buffer:
        st.download_button(
            "⬇️ Download ZIP",
            data=zip_buffer.getvalue(),
            file_name="o1_criterion_highlighted_pdfs.zip",
            mime="application/zip",
        )

    st.caption("You can also export per PDF/per criterion below:")

    for f in all_files:
        data = st.session_state["ai_by_file"].get(f.name)
        if not data:
            continue

        st.markdown(f"### 📄 {f.name}")

        for cid in selected_criteria_ids:
            approvals = st.session_state["approval"].get(f.name, {}).get(cid, {})
            approved_quotes = [q for q, ok in approvals.items() if ok]
            if not approved_quotes:
                continue

            if st.button(f"Generate PDF for Criterion {cid}", key=f"gen_{f.name}_{cid}"):
                with st.spinner("Annotating…"):
                    if isinstance(f, io.BytesIO):
                        pdf_bytes = f.getvalue()
                    else:
                        pdf_bytes = f.getvalue()
                        
                    out_bytes, report = build_annotated_pdf_bytes(
                        pdf_bytes,
                        approved_quotes,
                        cid,
                        filename=f.name,
                    )

                out_name = f.name.replace(".pdf", f"_criterion-{cid}_highlighted.pdf")

                st.success(
                    f"Created {out_name} — quotes: {report.get('total_quote_hits', 0)} | meta: {report.get('total_meta_hits', 0)}"
                )

                st.download_button(
                    f"⬇️ Download {out_name}",
                    data=out_bytes,
                    file_name=out_name,
                    mime="application/pdf",
                    key=f"dl_{f.name}_{cid}",
                )

    st.divider()
    st.caption("O-1 PDF Highlighter • Criterion-based extraction + approval workflow + per-criterion exports")
