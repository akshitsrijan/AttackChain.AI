"""
AttackChain Advisor — Streamlit UI Frontend.

Provides a modern, progressive dashboard showing every reasoning stage
of the AttackChain Advisor neuro-symbolic pipeline.
"""

import datetime
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

import networkx as nx
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

# Fix python imports path to resolve backend modules in 'pipeline' subfolder
sys.path.append(str(Path(__file__).parent / "pipeline"))

from response_synthesis import analyze
from graph_traversal import GRAPH

# ------------------------------------------------------------
# Streamlit Page Config
# ------------------------------------------------------------
st.set_page_config(
    page_title="AttackChain Advisor",
    page_icon="🛡️",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ------------------------------------------------------------
# Custom CSS Theme injection
# ------------------------------------------------------------
st.markdown(
    """
    <style>
    /* Dark Theme Cyber Design */
    .stApp {
        background-color: #0E1117;
        color: #E0E6ED;
    }
    .main {
        background-color: #0E1117;
    }
    /* Rounded Container Cards */
    .advisor-card {
        background-color: #161B22;
        border: 1px solid #30363D;
        padding: 24px;
        border-radius: 12px;
        margin-bottom: 24px;
        box-shadow: 0 4px 10px rgba(0, 0, 0, 0.3);
    }
    .card-title {
        font-size: 1.35rem;
        font-weight: bold;
        color: #FF4B4B;
        margin-bottom: 16px;
        display: flex;
        align-items: center;
        gap: 10px;
    }
    .flow-arrow {
        text-align: center;
        font-size: 1.8rem;
        color: #FF4B4B;
        margin: 12px 0;
        font-weight: bold;
    }
    /* bottom executive summary card */
    .summary-card {
        background-color: #0A192F;
        border: 1px solid #172A45;
        padding: 24px;
        border-radius: 12px;
        margin-top: 32px;
        margin-bottom: 32px;
        box-shadow: 0 4px 12px rgba(0, 0, 0, 0.4);
    }
    .stage-box-active {
        border-left: 4px solid #FF4B4B;
        background-color: #1F191D;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ------------------------------------------------------------
# Interactive Graph Visualization Generator
# ------------------------------------------------------------
def generate_plotly_graph(chain_nodes: List[str], chain_edges: List[Dict[str, str]]) -> go.Figure:
    """
    Computes NetworkX node layouts and returns an interactive Plotly figure.
    Highlights nodes and edges traversed in the attack chain.
    """
    # Deterministic position layout
    pos = nx.spring_layout(GRAPH, seed=42)

    edge_x = []
    edge_y = []
    highlight_edge_x = []
    highlight_edge_y = []

    # Map target-source pairs for validation highlighting
    highlighted_pairs = set()
    for edge in chain_edges:
        src = edge.get("source")
        tgt = edge.get("target")
        if src and tgt:
            highlighted_pairs.add((src, tgt))
            highlighted_pairs.add((tgt, src))

    for u, v in GRAPH.edges():
        x0, y0 = pos[u]
        x1, y1 = pos[v]

        is_highlighted = (u, v) in highlighted_pairs or (v, u) in highlighted_pairs
        if is_highlighted:
            highlight_edge_x.extend([x0, x1, None])
            highlight_edge_y.extend([y0, y1, None])
        else:
            edge_x.extend([x0, x1, None])
            edge_y.extend([y0, y1, None])

    # Plotly Scatter trace for regular edges
    edge_trace = go.Scatter(
        x=edge_x, y=edge_y,
        line=dict(width=1, color='#30363D'),
        hoverinfo='none',
        mode='lines'
    )

    # Plotly Scatter trace for highlighted edges
    highlight_edge_trace = go.Scatter(
        x=highlight_edge_x, y=highlight_edge_y,
        line=dict(width=3, color='#FF4B4B'),
        hoverinfo='none',
        mode='lines'
    )

    node_x = []
    node_y = []
    node_text = []
    node_color = []
    node_size = []
    node_line_color = []
    node_line_width = []

    path_nodes = set(chain_nodes)

    # Load titles from node definitions inside responses
    from graph_traversal import KNOWLEDGE_INDEX

    for node in GRAPH.nodes():
        x, y = pos[node]
        node_x.append(x)
        node_y.append(y)

        node_info = KNOWLEDGE_INDEX.get(node, {})
        title = node_info.get("title", "[Outside Curated Set]")
        node_text.append(f"<b>ID:</b> {node}<br><b>Title:</b> {title}")

        if node in path_nodes:
            node_color.append('#FF4B4B')
            node_size.append(18)
            node_line_color.append('#FFFFFF')
            node_line_width.append(2)
        else:
            node_color.append('#161B22')
            node_size.append(10)
            node_line_color.append('#8B949E')
            node_line_width.append(1)

    # Plotly Scatter trace for nodes
    node_trace = go.Scatter(
        x=node_x, y=node_y,
        mode='markers',
        hoverinfo='text',
        text=node_text,
        marker=dict(
            showscale=False,
            color=node_color,
            size=node_size,
            line=dict(color=node_line_color, width=node_line_width)
        )
    )

    # Assemble Plotly Figure
    fig = go.Figure(
        data=[edge_trace, highlight_edge_trace, node_trace],
        layout=go.Layout(
            showlegend=False,
            hovermode='closest',
            margin=dict(b=0, l=0, r=0, t=0),
            xaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            yaxis=dict(showgrid=False, zeroline=False, showticklabels=False),
            plot_bgcolor='rgba(0,0,0,0)',
            paper_bgcolor='rgba(0,0,0,0)',
            height=400
        )
    )

    return fig

# ------------------------------------------------------------
# HEADER & INTRODUCTION
# ------------------------------------------------------------
st.title("🛡️ AttackChain Advisor")
st.markdown("### *Hybrid Neuro-Symbolic AI for Explainable Attack Chain Discovery*")
st.markdown(
    """
    AttackChain Advisor uses a hybrid neuro-symbolic approach to map researcher observations to formal vulnerability knowledge, 
    assess dataset quality markers, and traverse complementary cross-reference linkages to map complete attack chains.
    """
)
st.markdown("---")

# ------------------------------------------------------------
# INPUT CARD
# ------------------------------------------------------------
st.markdown("### 📝 Enter Observation")
observation = st.text_area(
    label="Input researcher findings or system logs:",
    placeholder="Example: I noticed CRLF injection in URIs was tolerated without validation by legacy handlers...",
    height=120
)

# Analyze trigger
analyze_clicked = st.button("Analyze Attack Chain", use_container_width=True)

if analyze_clicked:
    if not observation.strip():
        st.error("Please enter a valid observation before analyzing.")
    else:
        # Run backend logic synchronously
        result = analyze(observation)

        # RENDER PROGRESSIVE WORKFLOW
        st.markdown("### ⚡ Pipeline Execution Progress")
        stages = [
            "Intent Extraction",
            "Semantic Retrieval",
            "Quality Ranking",
            "Knowledge Graph",
            "Validation",
            "AI Explanation"
        ]

        messages = [
            "Extracting cybersecurity intent...",
            "Searching semantic knowledge...",
            "Ranking high-quality entries...",
            "Traversing knowledge graph...",
            "Validating reasoning...",
            "Generating explainable report..."
        ]

        progress_cols = st.columns(6)
        placeholders = [col.empty() for col in progress_cols]

        # Stage simulation loop
        for step in range(6):
            for idx, ph in enumerate(placeholders):
                if idx < step:
                    ph.markdown(f"**Stage {idx+1}**\n\n🟢 {stages[idx]}\n\n*Completed*")
                elif idx == step:
                    ph.markdown(f"**Stage {idx+1}**\n\n🔄 {stages[idx]}\n\n*{messages[step]}*")
                else:
                    ph.markdown(f"**Stage {idx+1}**\n\n⚪ {stages[idx]}\n\n*Pending*")
            time.sleep(0.5)

        # Mark all stages complete
        for idx, ph in enumerate(placeholders):
            ph.markdown(f"**Stage {idx+1}**\n\n🟢 {stages[idx]}\n\n*Completed*")

        st.markdown("---")

        # ------------------------------------------------------------
        # CARD 1: Intent Extraction
        # ------------------------------------------------------------
        st.markdown(
            f"""
            <div class='advisor-card'>
                <div class='card-title'>🔍 Card 1: Intent Extraction</div>
                <p><b>Extracted Cybersecurity Intent:</b></p>
                <blockquote style='border-left: 3px solid #FF4B4B; padding-left: 10px; font-style: italic;'>
                    "{result['intent']}"
                </blockquote>
                <p style='font-size: 0.85rem; color: #8B949E;'>
                    Processed via: <code>{result['metadata']['model_used'] or 'Local Fallback'}</code>
                </p>
            </div>
            """,
            unsafe_allow_html=True
        )

        # ------------------------------------------------------------
        # CARD 2: Semantic Retrieval
        # ------------------------------------------------------------
        top_retrieved = result["retrieval"][0] if result["retrieval"] else {}
        st.markdown(
            f"""
            <div class='advisor-card'>
                <div class='card-title'>📥 Card 2: Semantic Retrieval</div>
                <p><b>Top Retrieved Match:</b> <code>{top_retrieved.get('id', 'N/A')}</code> — {top_retrieved.get('title', 'N/A')}</p>
                <ul>
                    <li><b>Semantic Similarity Score:</b> <code>{top_retrieved.get('similarity', 0.0):.4f}</code></li>
                    <li><b>Category:</b> <code>{top_retrieved.get('category', 'unknown')}</code></li>
                    <li><b>Dataset Confidence:</b> <code>{top_retrieved.get('confidence', 'unknown')}</code></li>
                </ul>
            </div>
            """,
            unsafe_allow_html=True
        )

        # ------------------------------------------------------------
        # CARD 3: Quality Ranking
        # ------------------------------------------------------------
        top_ranked = result["ranking"][0] if result["ranking"] else {}
        reasoning_details = top_ranked.get("ranking_reason", {})
        st.markdown(
            f"""
            <div class='advisor-card'>
                <div class='card-title'>📊 Card 3: Quality Ranking (Reranking)</div>
                <p>Adjusts semantic similarity using objective IEEE DataPort quality checklist dimensions.</p>
                <ul>
                    <li><b>Final Composite Score:</b> <code>{top_ranked.get('composite_score', 0.0):.4f}</code></li>
                    <li><b>Quality Score:</b> <code>{top_ranked.get('quality_score', 0.0):.4f}</code></li>
                    <li><b>Checks Passed:</b> <code>{top_ranked.get('pass_count', 0)} / 8</code></li>
                    <li><b>Confidence Tier:</b> <code>{top_ranked.get('confidence_tier', 'unknown')}</code></li>
                </ul>
                <p><b>Ranking Reason:</b></p>
                <div style='background-color: #1A1F2C; border: 1px solid #30363D; padding: 12px; border-radius: 8px; font-size: 0.9rem;'>
                    {reasoning_details.get('explanation', 'Reranked based on semantic similarity and passed checks count.')}
                </div>
            </div>
            """,
            unsafe_allow_html=True
        )

        # ------------------------------------------------------------
        # CARD 4: Knowledge Graph Flow & Network Visualizer
        # ------------------------------------------------------------
        st.markdown("### 🕸️ Card 4: Knowledge Graph Traversal")
        st.write("Discovered attack path and connectivity inside the knowledge base network topology:")

        attack_chain = result["graph"]["attack_chain"]
        
        # Display the vertical nodes flow
        for i, node in enumerate(attack_chain):
            nid = node.get("entry_id")
            title = node.get("title", "[Outside Curated Set]")
            exists = node.get("exists_in_quality_dataset", False)
            badge = "Curated" if exists else "Out-of-range"
            badge_bg = "#1E3A1E" if exists else "#3A1E1E"
            badge_color = "#4CAF50" if exists else "#F44336"

            st.markdown(
                f"""
                <div style='background-color: #161B22; border: 1px solid #30363D; padding: 16px; border-radius: 8px;'>
                    <b>Step {i+1}: {nid}</b> — {title}
                    <span style='float: right; font-size: 0.8rem; background-color: {badge_bg}; color: {badge_color}; padding: 3px 8px; border-radius: 4px;'>{badge}</span>
                </div>
                """,
                unsafe_allow_html=True
            )

            if i < len(attack_chain) - 1:
                st.markdown("<div class='flow-arrow'>↓</div>", unsafe_allow_html=True)

        st.markdown("<br>", unsafe_allow_html=True)
        st.write("**Graph Statistics:**")
        g_stats = result["graph"]["graph_statistics"]
        st.markdown(
            f"- **Chain Length:** {result['graph']['chain_length']} nodes\n"
            f"- **Edges Followed:** {g_stats['edges_followed']}\n"
            f"- **Reachable Nodes:** {len(result['graph']['reachable_nodes'])} total nodes in sub-graph"
        )

        # Display Plotly graph visualization
        st.write("**Interactive Topological Visualization:**")
        chain_node_ids = [n["entry_id"] for n in attack_chain]
        fig = generate_plotly_graph(chain_node_ids, result["graph"]["edges"])
        st.plotly_chart(fig, use_container_width=True)
        st.markdown("---")

        # ------------------------------------------------------------
        # CARD 5: Validation Checkbox Panel
        # ------------------------------------------------------------
        st.markdown("### 📋 Card 5: Knowledge Consistency Validation")
        val = result["validation"]
        passed_checks = val.get("checks", {})
        issues = val.get("issues", [])

        val_cols = st.columns(4)
        with val_cols[0]:
            if passed_checks.get("retrieval"):
                st.markdown("🟢 **Retrieval**\n\n✔ Passed")
            else:
                st.markdown("🔴 **Retrieval**\n\n✘ Failed")

        with val_cols[1]:
            if passed_checks.get("ranking"):
                st.markdown("🟢 **Ranking**\n\n✔ Passed")
            else:
                st.markdown("🔴 **Ranking**\n\n✘ Failed")

        with val_cols[2]:
            if passed_checks.get("graph"):
                st.markdown("🟢 **Graph**\n\n✔ Passed")
            else:
                st.markdown("🔴 **Graph**\n\n✘ Failed")

        with val_cols[3]:
            if passed_checks.get("confidence"):
                st.markdown("🟢 **Confidence**\n\n✔ Passed")
            else:
                st.markdown("🔴 **Confidence**\n\n✘ Failed")

        if issues:
            st.warning("⚠️ **Consistency Concerns Identified:**")
            for issue in issues:
                st.markdown(f"- {issue}")
        else:
            st.success("✔ **No consistency anomalies detected in the reasoning flow.**")
        st.markdown("---")

        # ------------------------------------------------------------
        # CARD 6: AI Explanation
        # ------------------------------------------------------------
        st.markdown("### 🤖 Card 6: AI Explanation Report")
        meta = result["metadata"]
        if meta["fallback_used"]:
            st.warning("⚠️ **Running in Local Explanation Mode** (Gemini API unavailable)")
        else:
            st.success("✨ **Report Generated via Gemini API (gemini-2.5-flash)**")

        st.markdown(result["answer"])
        st.markdown("---")

        # ------------------------------------------------------------
        # PIPELINE SUMMARY CARD (Bottom)
        # ------------------------------------------------------------
        top_tech_id = top_ranked.get("id") or top_ranked.get("entry_id", "N/A")
        top_tech_title = top_ranked.get("title", "N/A")
        st.markdown(
            f"""
            <div class='summary-card'>
                <h4 style='margin-top: 0; color: #FF4B4B;'>📋 AttackChain Advisor Summary Card</h4>
                <table style='width: 100%; border-collapse: collapse; font-size: 0.95rem;'>
                    <tr>
                        <td style='padding: 6px 0; border-bottom: 1px solid #172A45;'><b>Observation:</b></td>
                        <td style='padding: 6px 0; border-bottom: 1px solid #172A45;'>{observation}</td>
                    </tr>
                    <tr>
                        <td style='padding: 6px 0; border-bottom: 1px solid #172A45;'><b>Extracted Intent:</b></td>
                        <td style='padding: 6px 0; border-bottom: 1px solid #172A45;'>{result['intent']}</td>
                    </tr>
                    <tr>
                        <td style='padding: 6px 0; border-bottom: 1px solid #172A45;'><b>Top Technique:</b></td>
                        <td style='padding: 6px 0; border-bottom: 1px solid #172A45;'><code>{top_tech_id}</code> — {top_tech_title}</td>
                    </tr>
                    <tr>
                        <td style='padding: 6px 0; border-bottom: 1px solid #172A45;'><b>Attack Chain Length:</b></td>
                        <td style='padding: 6px 0; border-bottom: 1px solid #172A45;'><code>{result['graph']['chain_length']} nodes</code></td>
                    </tr>
                    <tr>
                        <td style='padding: 6px 0; border-bottom: 1px solid #172A45;'><b>Confidence Tier:</b></td>
                        <td style='padding: 6px 0; border-bottom: 1px solid #172A45;'><code>{top_ranked.get('confidence_tier', 'N/A')}</code></td>
                    </tr>
                    <tr>
                        <td style='padding: 6px 0;'><b>Execution Time:</b></td>
                        <td style='padding: 6px 0;'><code>{result['metadata']['execution_time_ms']} ms</code></td>
                    </tr>
                </table>
            </div>
            """,
            unsafe_allow_html=True
        )

        # ------------------------------------------------------------
        # SIDEBAR METADATA
        # ------------------------------------------------------------
        st.sidebar.title("Advisor Panel")
        st.sidebar.markdown("### ⚙️ System Metadata")
        st.sidebar.write(f"**Model Used:** `{result['metadata']['model_used'] or 'Local Fallback'}`")
        st.sidebar.write(f"**LLM Active:** `{result['metadata']['llm_used']}`")
        st.sidebar.write(f"**Fallback Mode:** `{result['metadata']['fallback_used']}`")
        st.sidebar.write(f"**Execution Time:** `{result['metadata']['execution_time_ms']} ms`")
        st.sidebar.write(f"**Pipeline Version:** `v2.1.0-neuro-symbolic`")
        st.sidebar.write(f"**Timestamp:** `{datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`")
