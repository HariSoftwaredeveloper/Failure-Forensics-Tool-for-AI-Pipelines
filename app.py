import streamlit as st
import pandas as pd
import json
import os
import plotly.express as px
import plotly.graph_objects as go
from datetime import datetime

import db
import pipeline
import analyzer
import tracer

# Set Streamlit Page Configuration
st.set_page_config(
    page_title="AI Pipeline Failure Forensics Explorer",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Sleek CSS for premium visual wow-factor
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;500;700&family=JetBrains+Mono:wght@400;500&display=swap');

/* Typography */
html, body, [class*="css"] {
    font-family: 'Outfit', sans-serif;
}
code, pre, [class*="mono"] {
    font-family: 'JetBrains Mono', monospace;
}

/* Card layout */
.metric-card {
    background: #0f172a;
    border: 1px solid #1e293b;
    border-radius: 12px;
    padding: 20px;
    text-align: center;
    box-shadow: 0 4px 6px -1px rgb(0 0 0 / 0.1);
    transition: transform 0.2s, border-color 0.2s;
}
.metric-card:hover {
    transform: translateY(-2px);
    border-color: #38bdf8;
}
.metric-num {
    font-size: 2rem;
    font-weight: 700;
    color: #38bdf8;
    margin-bottom: 4px;
}
.metric-label {
    font-size: 0.85rem;
    color: #94a3b8;
    text-transform: uppercase;
    letter-spacing: 0.05em;
}

/* Pipeline Node Visual styling */
.pipeline-wrapper {
    display: flex;
    align-items: center;
    justify-content: space-between;
    background-color: #0b0f19;
    border: 1px solid #1e293b;
    border-radius: 16px;
    padding: 28px;
    margin: 20px 0;
    overflow-x: auto;
}
.pipeline-node-box {
    flex: 1;
    min-width: 180px;
    background: #1e293b;
    border: 2px solid #334155;
    border-radius: 12px;
    padding: 18px;
    text-align: center;
    transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
    cursor: pointer;
    box-shadow: 0 4px 12px rgba(0,0,0,0.25);
}
.pipeline-node-box:hover {
    transform: translateY(-4px);
    box-shadow: 0 12px 20px rgba(0,0,0,0.4);
}
.pipeline-node-box.selected {
    border-color: #38bdf8;
    box-shadow: 0 0 15px rgba(56, 189, 248, 0.4);
}
.node-title {
    font-size: 1.1rem;
    font-weight: 700;
    margin-bottom: 6px;
    letter-spacing: 0.02em;
}
.node-status-label {
    font-size: 0.8rem;
    font-weight: 600;
    padding: 2px 8px;
    border-radius: 9999px;
    display: inline-block;
    margin-bottom: 8px;
}
.status-healthy {
    background-color: rgba(16, 185, 129, 0.15);
    color: #34d399;
    border: 1px solid rgba(16, 185, 129, 0.3);
}
.status-warning {
    background-color: rgba(245, 158, 11, 0.15);
    color: #fbbf24;
    border: 1px solid rgba(245, 158, 11, 0.3);
}
.status-error {
    background-color: rgba(239, 68, 68, 0.15);
    color: #f87171;
    border: 1px solid rgba(239, 68, 68, 0.3);
}
.node-meta {
    font-size: 0.75rem;
    color: #94a3b8;
    margin-top: 4px;
}
.pipeline-arrow-icon {
    color: #475569;
    font-size: 24px;
    margin: 0 15px;
    font-weight: bold;
}

/* Forensics Card */
.forensics-box {
    background: linear-gradient(135deg, #1e1b4b 0%, #0f172a 100%);
    border: 2px solid #4338ca;
    border-radius: 12px;
    padding: 24px;
    margin-bottom: 25px;
}
.forensics-title {
    font-size: 1.25rem;
    font-weight: 700;
    color: #818cf8;
    display: flex;
    align-items: center;
    gap: 8px;
    margin-bottom: 12px;
}
.forensics-badge {
    background-color: #ef4444;
    color: white;
    padding: 2px 10px;
    border-radius: 4px;
    font-size: 0.75rem;
    font-weight: 700;
}
</style>
""", unsafe_allow_html=True)

# ----------------- SIDEBAR & NAVIGATION -----------------

st.sidebar.title("🕵️ Forensics Portal")
st.sidebar.markdown("*Failure Forensics Tool for AI Pipelines*")
st.sidebar.markdown("---")

nav_selection = st.sidebar.radio(
    "Navigation",
    ["🔍 Trace Explorer", "📊 Failure Analytics", "🧪 Evaluation Suite"],
    index=0
)

# Fetch all traces from DB
traces = db.get_all_traces()

# Calculate stats
total_traces = len(traces)
failed_traces = sum(1 for t in traces if t["status"] == "FAILED" or t["root_cause_step"] is not None)
success_rate = ((total_traces - failed_traces) / total_traces * 100) if total_traces > 0 else 100
flagged_traces = sum(1 for t in traces if t["human_flagged"] == 1)

# Sidebar stats overview
st.sidebar.markdown("---")
st.sidebar.subheader("System Status")
st.sidebar.metric("Success Rate", f"{success_rate:.1f}%")
st.sidebar.metric("Flagged Issues", flagged_traces)
st.sidebar.metric("Processed Documents", total_traces)

# ----------------- PAGE 1: TRACE EXPLORER -----------------

if nav_selection == "🔍 Trace Explorer":
    st.title("🔍 Interactive Trace Explorer")
    st.markdown("Inspect and debug document processing pipelines in real time.")
    
    # KPI cards row
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f'<div class="metric-card"><div class="metric-num">{total_traces}</div><div class="metric-label">Total Traces</div></div>', unsafe_allow_html=True)
    with col2:
        st.markdown(f'<div class="metric-card"><div class="metric-num" style="color: #ef4444;">{failed_traces}</div><div class="metric-label">Failed / Flagged</div></div>', unsafe_allow_html=True)
    with col3:
        st.markdown(f'<div class="metric-card"><div class="metric-num" style="color: #10b981;">{success_rate:.1f}%</div><div class="metric-label">Success Rate</div></div>', unsafe_allow_html=True)
    with col4:
        st.markdown(f'<div class="metric-card"><div class="metric-num" style="color: #eab308;">{flagged_traces}</div><div class="metric-label">Human Flagged</div></div>', unsafe_allow_html=True)
        
    st.markdown("### Filters")
    f_col1, f_col2, f_col3 = st.columns([2, 1, 1])
    
    with f_col1:
        search_query = st.text_input("Search source document contents:", "")
    with f_col2:
        status_filter = st.selectbox("Status Filter", ["All", "Healthy", "Failed / Quality Drop", "Human Flagged"])
    with f_col3:
        sort_order = st.selectbox("Sort By Time", ["Newest First", "Oldest First"])
        
    # Apply filtering
    filtered_traces = traces
    if search_query:
        filtered_traces = [t for t in filtered_traces if search_query.lower() in (t["input_doc"] or "").lower()]
        
    if status_filter == "Healthy":
        filtered_traces = [t for t in filtered_traces if t["status"] == "SUCCESS" and t["root_cause_step"] is None]
    elif status_filter == "Failed / Quality Drop":
        filtered_traces = [t for t in filtered_traces if t["status"] == "FAILED" or t["root_cause_step"] is not None]
    elif status_filter == "Human Flagged":
        filtered_traces = [t for t in filtered_traces if t["human_flagged"] == 1]
        
    if sort_order == "Oldest First":
        filtered_traces = sorted(filtered_traces, key=lambda x: x["created_at"])
    else:
        filtered_traces = sorted(filtered_traces, key=lambda x: x["created_at"], reverse=True)
        
    if not filtered_traces:
        st.info("No traces matched the criteria.")
    else:
        # Create a dropdown to select a trace
        trace_options = {f"{t['trace_id'][:8]}... | {t['status']} | {t['created_at'][:19].replace('T', ' ')}": t['trace_id'] for t in filtered_traces}
        selected_trace_key = st.selectbox("Select a Trace to Investigate:", list(trace_options.keys()))
        selected_trace_id = trace_options[selected_trace_key]
        
        # Fetch trace details
        trace_details = db.get_trace_details(selected_trace_id)
        trace_obj = trace_details["trace"]
        spans = trace_details["spans"]
        
        st.markdown("---")
        st.subheader(f"Trace Details: `{selected_trace_id}`")
        
        # Display the custom HTML/CSS Pipeline Node graph
        st.markdown("#### Pipeline Node Flow")
        st.markdown("*Hover over nodes to inspect details. Click nodes to jump to detailed step inspector below.*")
        
        nodes_html = '<div class="pipeline-wrapper">'
        
        # Define step execution order
        pipeline_steps = ["Intake", "Extraction", "Classification", "Summarization"]
        
        # Get span details mapped by name
        spans_by_name = {s["name"]: s for s in spans}
        
        for idx, step in enumerate(pipeline_steps):
            span = spans_by_name.get(step)
            
            node_class = "node-success"
            status_text = "Healthy"
            meta_text = "N/A"
            border_class = ""
            
            if span:
                latency_ms = int(span["latency"] * 1000)
                conf = span["confidence"]
                meta_text = f"{latency_ms} ms"
                if span["tokens_used"]:
                    meta_text += f" | {span['tokens_used']} tokens"
                    
                if span["status"] == "FAILED":
                    node_class = "status-error"
                    status_text = "💥 Crashed"
                elif conf is not None and conf <= 2:
                    node_class = "status-warning"
                    status_text = f"⚠ Low Conf ({conf}/5)"
                else:
                    node_class = "status-healthy"
                    status_text = f"✔ Healthy ({conf}/5)" if conf else "✔ Success"
            else:
                # Step didn't run because prior step failed
                node_class = "status-error"
                status_text = "🚫 Not Run"
                meta_text = "Skipped"
                
            nodes_html += f"""
            <div class="pipeline-node-box">
                <div class="node-title">{step}</div>
                <div class="node-status-label {node_class}">{status_text}</div>
                <div class="node-meta">{meta_text}</div>
            </div>
            """
            
            if idx < len(pipeline_steps) - 1:
                nodes_html += '<div class="pipeline-arrow-icon">➔</div>'
                
        nodes_html += '</div>'
        st.markdown(nodes_html, unsafe_allow_html=True)
        
        # Forensics Diagnostic Card
        if trace_obj["root_cause_step"] or trace_obj["status"] == "FAILED":
            st.markdown(f"""
            <div class="forensics-box">
                <div class="forensics-title">
                    🕵️ Root Cause Diagnosis & Structured Evidence Chain
                    <span class="forensics-badge">{trace_obj["root_cause_type"] or "Pipeline Crash"}</span>
                </div>
                <p><strong>Root Cause Step:</strong> <code style="color: #818cf8; font-weight: bold;">{trace_obj["root_cause_step"] or "Intake"}</code></p>
                <p><strong>Evidence Chain / Explanation:</strong></p>
                <div style="background-color: rgba(0,0,0,0.3); border-radius: 6px; padding: 16px; border-left: 4px solid #ef4444; font-size: 0.95rem;">
                    {trace_obj["root_cause_explanation"] or "Trace crashed during processing. Detailed exception logs recorded in the step details below."}
                </div>
            </div>
            """, unsafe_allow_html=True)
            
        # Layout splits into details and input/output explorer
        det_col1, det_col2 = st.columns([1, 1])
        
        with det_col1:
            st.markdown("#### Input Document Source Text")
            st.code(trace_obj["input_doc"], language="text")
            
        with det_col2:
            st.markdown("#### Final Pipeline Output JSON")
            if trace_obj["final_output"]:
                try:
                    formatted_out = json.dumps(json.loads(trace_obj["final_output"]), indent=2)
                    st.code(formatted_out, language="json")
                except:
                    st.code(trace_obj["final_output"], language="text")
            else:
                st.error(f"Pipeline crashed. Error trace: \n{trace_obj['error_message']}")
                
        # Detailed Step Inspector
        st.markdown("### 📋 Detailed Step Inspector")
        step_tabs = st.tabs(pipeline_steps)
        
        for idx, step in enumerate(pipeline_steps):
            with step_tabs[idx]:
                span = spans_by_name.get(step)
                if not span:
                    st.info(f"Step '{step}' did not execute because a preceding step failed.")
                else:
                    sub_col1, sub_col2 = st.columns(2)
                    with sub_col1:
                        st.markdown("##### Inputs Received")
                        try:
                            st.json(json.loads(span["input_data"]))
                        except:
                            st.code(span["input_data"])
                    with sub_col2:
                        st.markdown("##### Outputs Produced")
                        try:
                            st.json(json.loads(span["output_data"]))
                        except:
                            st.code(span["output_data"])
                            
                    # Metadata row
                    m_col1, m_col2, m_col3, m_col4 = st.columns(4)
                    m_col1.metric("Status", span["status"])
                    m_col2.metric("Latency", f"{span['latency']*1000:.0f} ms")
                    m_col3.metric("Confidence Score", f"{span['confidence']}/5" if span['confidence'] else "N/A")
                    m_col4.metric("Tokens Consumed", span["tokens_used"] if span["tokens_used"] else "N/A")
                    
                    # LLM Prompt & Raw response collapsible
                    if span["prompt"]:
                        with st.expander("Show Raw LLM Prompts & Responses"):
                            st.markdown("**Prompt Sent to LLM:**")
                            st.code(span["prompt"], language="text")
                            st.markdown("**Raw Response Received:**")
                            st.code(span["raw_response"], language="text")
                            
        # Diff View Section (For failed or flagged traces)
        if trace_obj["status"] == "FAILED" or trace_obj["root_cause_step"] is not None or trace_obj["human_flagged"] == 1:
            st.markdown("---")
            st.markdown("### 🔀 Failure Diff View")
            st.markdown("Compare produced outputs versus what the pipeline *should* have produced.")
            
            diff_step = trace_obj["root_cause_step"] or "Extraction"
            diff_span = spans_by_name.get(diff_step)
            
            diff_col1, diff_col2 = st.columns(2)
            with diff_col1:
                st.markdown(f"#### Produced Output ({diff_step})")
                if diff_span:
                    try:
                        st.json(json.loads(diff_span["output_data"]))
                    except:
                        st.code(diff_span["output_data"])
                else:
                    st.code("No output was produced due to a step crash.")
                    
            with diff_col2:
                st.markdown(f"#### Target Output (Should-Have-Produced)")
                if trace_obj["corrected_output"]:
                    try:
                        st.json(json.loads(trace_obj["corrected_output"]))
                    except:
                        st.code(trace_obj["corrected_output"])
                else:
                    st.info("No corrected output has been supplied yet. Submit feedback below to establish a target.")
                    
        # Feedback & Flagging Interface
        st.markdown("---")
        st.markdown("### 🛠️ Feedback & Evaluation Loop")
        st.markdown("Verify the diagnosis, override taxonomy, and capture corrected outputs to update regression suites.")
        
        feed_col1, feed_col2 = st.columns(2)
        with feed_col1:
            default_cat = trace_obj["human_category"] or trace_obj["root_cause_type"] or "Extraction Hallucination"
            category_options = ["Extraction Hallucination", "Misclassification", "Propagation Error", "Prompt Failure", "Context Loss", "Other"]
            if default_cat not in category_options:
                category_options.append(default_cat)
            
            selected_cat = st.selectbox("Assign/Confirm Failure Category:", category_options, index=category_options.index(default_cat))
            human_notes = st.text_area("Write diagnostic notes/override reasons:", trace_obj["human_notes"] or "")
            
        with feed_col2:
            # Pre-populate corrected output with the actual output of the root cause step to make editing easy
            default_corr = trace_obj["corrected_output"]
            if not default_corr:
                rc_step = trace_obj["root_cause_step"] or "Extraction"
                rc_span = spans_by_name.get(rc_step)
                if rc_span:
                    default_corr = rc_span["output_data"]
                    
            corrected_out_str = st.text_area("Supply Corrected Output JSON (creates an evaluation case):", default_corr or "")
            
        if st.button("Submit Feedback & Flag Trace", type="primary"):
            try:
                # Basic JSON validation if corrected output provided
                if corrected_out_str:
                    json.loads(corrected_out_str)
                
                db.flag_trace(
                    trace_id=selected_trace_id,
                    human_category=selected_cat,
                    human_notes=human_notes,
                    corrected_output=corrected_out_str if corrected_out_str else None
                )
                st.success("Trace successfully flagged! Feedback and evaluation case updated.")
                st.rerun()
            except json.JSONDecodeError:
                st.error("Invalid JSON formatted output. Please supply a valid JSON string.")
            except Exception as e:
                st.error(f"Error saving feedback: {e}")

# ----------------- PAGE 2: FAILURE ANALYTICS -----------------

elif nav_selection == "📊 Failure Analytics":
    st.title("📊 Failure Analytics Dashboard")
    st.markdown("Aggregated failure classification models and diagnostic stats.")
    
    analytics = db.get_failure_analytics()
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.markdown("### 🏆 Common Failure Categories")
        types_df = pd.DataFrame(analytics["types_distribution"])
        if types_df.empty:
            st.info("No failure metrics available yet.")
        else:
            fig = px.bar(
                types_df, 
                x="failure_type", 
                y="count", 
                labels={"failure_type": "Failure Category", "count": "Frequency"},
                color="failure_type",
                color_discrete_sequence=px.colors.qualitative.Dark24
            )
            fig.update_layout(showlegend=False, template="plotly_dark", plot_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig, use_container_width=True)
            
    with col2:
        st.markdown("### 🎯 Suspect Step Frequency")
        steps_df = pd.DataFrame(analytics["steps_distribution"])
        if steps_df.empty:
            st.info("No step distribution available yet.")
        else:
            fig = px.pie(
                steps_df, 
                names="root_cause_step", 
                values="count",
                color="root_cause_step",
                color_discrete_sequence=px.colors.qualitative.Safe
            )
            fig.update_layout(template="plotly_dark", plot_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig, use_container_width=True)
            
    st.markdown("---")
    st.subheader("Performance & Latency Analysis")
    
    # Latency by step
    conn = db.get_db_connection()
    df_spans = pd.read_sql_query("SELECT name, latency FROM spans WHERE status='SUCCESS'", conn)
    conn.close()
    
    if not df_spans.empty:
        fig_lat = px.box(
            df_spans, 
            x="name", 
            y="latency", 
            points="all", 
            labels={"name": "Pipeline Step", "latency": "Latency (seconds)"},
            title="Step Latency Distribution (Seconds)"
        )
        fig_lat.update_layout(template="plotly_dark")
        st.plotly_chart(fig_lat, use_container_width=True)
    else:
        st.info("No latency stats recorded yet.")

# ----------------- PAGE 3: EVALUATION SUITE -----------------

elif nav_selection == "🧪 Evaluation Suite":
    st.title("🧪 Evaluation & Regression Suite")
    st.markdown("Run automated checks on confirmed failure cases to detect pipeline quality regression over time.")
    
    eval_cases = db.get_eval_cases()
    
    if not eval_cases:
        st.info("No evaluation cases harvested from flags yet. Go to the Trace Explorer to flag issues and provide corrected outputs.")
    else:
        st.subheader("Harvested Evaluation Test Suite")
        st.dataframe(pd.DataFrame(eval_cases)[["case_id", "failing_step", "category", "created_at"]])
        
        if st.button("Run Regression Testing", type="primary"):
            st.markdown("### Regression Test Run Results")
            progress_bar = st.progress(0)
            
            results = []
            passed_cases = 0
            
            for idx, case in enumerate(eval_cases):
                progress_bar.progress((idx + 1) / len(eval_cases))
                
                # Fetch case details
                case_id = case["case_id"]
                step = case["failing_step"]
                input_doc = case["input_doc"]
                target_json = json.loads(case["corrected_output"])
                
                # Run the evaluation case through the corresponding step
                status = "FAILED"
                new_output_str = ""
                error_msg = ""
                
                try:
                    # Configure mock mode so tests are deterministic and run local rules
                    os.environ["USE_MOCK_LLM"] = "true"
                    
                    if step == "Intake":
                        res = pipeline.step_intake(pipeline.IntakeInput(raw_text=input_doc))
                        new_output_str = res.json()
                    elif step == "Extraction":
                        res = pipeline.step_extraction(pipeline.ExtractionInput(text=input_doc))
                        new_output_str = json.dumps(res.dict())
                    elif step == "Classification":
                        # We need to supply mock extracted fields
                        res = pipeline.step_classification(pipeline.ClassificationInput(text=input_doc, extracted_fields={}))
                        new_output_str = json.dumps(res.dict())
                    elif step == "Summarization":
                        res = pipeline.step_summarization(pipeline.SummarizationInput(text=input_doc, extracted_fields={}, category="Invoice"))
                        new_output_str = json.dumps(res.dict())
                        
                    # Compare output quality
                    # Check if output parsed correctly
                    new_json = json.loads(new_output_str)
                    
                    # For a simple regression check:
                    # Check if new output has resolved the error (e.g. is no longer flagging low confidence or contains the correct target fields)
                    # Let's check key similarity or exact match
                    is_correct = True
                    for k, v in target_json.items():
                        if k in new_json and new_json[k] == v:
                            continue
                        # If value doesn't match and it's a critical field
                        if k in ["amount", "vendor", "category"] and new_json.get(k) != v:
                            is_correct = False
                            
                    # Since we are running mock/local mode, if it meets local standard
                    if is_correct:
                        status = "RESOLVED (PASS)"
                        passed_cases += 1
                    else:
                        status = "REGRESSED (FAIL)"
                        error_msg = f"Mismatch: expected {target_json} but got {new_json}"
                        
                except Exception as e:
                    status = "ERROR"
                    error_msg = str(e)
                    
                results.append({
                    "Case ID": case_id,
                    "Step": step,
                    "Target Output": case["corrected_output"],
                    "New Output": new_output_str or error_msg,
                    "Status": status
                })
                
            progress_bar.empty()
            
            # Show regression summary metrics
            reg_pct = (passed_cases / len(eval_cases)) * 100
            st.metric("Regression Pass Rate", f"{reg_pct:.1f}%", f"{passed_cases} / {len(eval_cases)} Passed")
            
            st.table(pd.DataFrame(results))
