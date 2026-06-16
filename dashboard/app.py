"""
BDE Dashboard — Streamlit interface for supply chain bottleneck intelligence.

Pages:
  1. Overview   — KPI cards, severity chart, network graph, evidence table, risk trend
  2. Hypothesis — Drill into one hypothesis: evidence, ACH matrix, score breakdown
  3. Knowledge Graph — Top-SRS table + explanations
  4. Orphan Queue — Manual review of unresolved documents
  5. System Status — Ingest queue, entity queue, Celery beat health
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# ──────────────────────────────────────────────
# Page config
# ──────────────────────────────────────────────

st.set_page_config(
    page_title="BDE — Bottleneck Discovery Engine",
    page_icon="🔬",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ──────────────────────────────────────────────
# Navigation
# ──────────────────────────────────────────────

PAGES = ["Overview", "Hypothesis Detail", "Knowledge Graph", "Orphan Queue", "System Status"]
page = st.sidebar.selectbox("Navigate", PAGES)
st.sidebar.markdown("---")
st.sidebar.caption("BDE v0.8 · Phase 7")

# ──────────────────────────────────────────────
# Cached data loaders
# ──────────────────────────────────────────────

@st.cache_data(ttl=300)
def get_opportunities():
    from scoring.opportunity_scorer import ranked_opportunities
    return ranked_opportunities()


@st.cache_data(ttl=300)
def get_top_nodes():
    from analysis.structural_analyzer import top_bottlenecks
    return top_bottlenecks(20)


@st.cache_data(ttl=60)
def get_system_stats():
    from ingestion.base import IngestStore
    from processing.document_processor import stats as doc_stats
    from hypotheses.hypothesis_manager import HypothesisManager
    from contrarian.ach_engine import list_pending_human_review
    return {
        "ingest": IngestStore().counts(),
        "processor": doc_stats(),
        "hypotheses": HypothesisManager().counts(),
        "pending_ach": len(list_pending_human_review()),
    }


@st.cache_data(ttl=300)
def get_network_data():
    """Load top-50 SRS nodes + edges between them for vis.js."""
    try:
        from neo4j import GraphDatabase
        from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session() as s:
            node_rows = s.run("""
                MATCH (n)
                WHERE n.srs_score IS NOT NULL AND n.id IS NOT NULL
                RETURN n.id AS id, n.name AS name,
                       labels(n)[0] AS label,
                       coalesce(n.srs_score, 0.0) AS srs_score,
                       coalesce(n.is_articulation_point, false) AS is_ap
                ORDER BY n.srs_score DESC LIMIT 50
            """).data()
            if not node_rows:
                driver.close()
                return {"nodes": [], "edges": []}
            node_ids = [r["id"] for r in node_rows]
            edge_rows = s.run("""
                MATCH (a)-[r]->(b)
                WHERE a.id IN $ids AND b.id IN $ids
                  AND a.id IS NOT NULL AND b.id IS NOT NULL
                RETURN a.id AS src, b.id AS tgt, type(r) AS rel_type
                LIMIT 300
            """, ids=node_ids).data()
        driver.close()
        return {"nodes": node_rows, "edges": edge_rows}
    except Exception as e:
        return {"nodes": [], "edges": [], "error": str(e)}


@st.cache_data(ttl=300)
def get_evidence_rows():
    """Flatten hypothesis evidence into table rows for the evidence table."""
    from hypotheses.hypothesis_manager import HypothesisManager
    from scoring.opportunity_scorer import score_hypothesis
    mgr = HypothesisManager()
    all_hyps = mgr.list_all(100)
    rows = []
    for h in all_hyps:
        scored = score_hypothesis(h)
        node_id = h.get("node_id", "")
        btype = node_id.split("-")[0] if "-" in node_id else (node_id[:3] if node_id else "—")
        date_str = (h.get("created_at") or "")[:10]
        ef = json.loads(h.get("evidence_for") or "[]")
        ea = json.loads(h.get("evidence_against") or "[]")
        for e in ef:
            rows.append({
                "Entity": h.get("node_name", ""),
                "Type": btype,
                "Severity": round(scored["ops_final"], 3),
                "Source": _infer_source(e),
                "Direction": "✅ supports",
                "Detected At": date_str,
                "_snippet": e,
            })
        for e in ea:
            rows.append({
                "Entity": h.get("node_name", ""),
                "Type": btype,
                "Severity": round(scored["ops_final"], 3),
                "Source": _infer_source(e),
                "Direction": "❌ against",
                "Detected At": date_str,
                "_snippet": e,
            })
    rows.sort(key=lambda r: r["Severity"], reverse=True)
    return rows


@st.cache_data(ttl=300)
def get_risk_trend():
    """Build 30-day time series of active bottleneck discovery."""
    from hypotheses.hypothesis_manager import HypothesisManager
    hyps = HypothesisManager().list_all(500)
    now = datetime.now(timezone.utc)
    daily_new: dict[str, int] = defaultdict(int)
    baseline = 0
    for h in hyps:
        try:
            dt = datetime.fromisoformat(h["created_at"].replace("Z", "+00:00"))
            days_ago = (now - dt).days
            if days_ago <= 30:
                daily_new[dt.date().isoformat()] += 1
            else:
                baseline += 1
        except Exception:
            pass
    dates = [(now - timedelta(days=i)).date().isoformat() for i in range(30, -1, -1)]
    new_daily = [daily_new.get(d, 0) for d in dates]
    cumulative, running = [], baseline
    for c in new_daily:
        running += c
        cumulative.append(running)
    return {"dates": dates, "new_daily": new_daily, "cumulative": cumulative}


# ──────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────

def tier_badge(tier: int) -> str:
    colors = {1: "🔴", 2: "🟠", 3: "🟡"}
    return f"{colors.get(tier, '⚪')} T{tier}"


def _infer_source(text: str) -> str:
    """Parse source type from evidence uid prefix: '[github:abc12] title'."""
    if text.startswith("[") and "]" in text:
        uid = text[1:text.index("]")]
        if uid.startswith("github:"): return "GitHub"
        if uid.startswith("arxiv:"): return "arXiv"
        if uid.startswith("hn:"): return "Hacker News"
        if uid.startswith("edgar:"): return "SEC EDGAR"
        if uid.startswith("rss_nyt"): return "NYT"
        if uid.startswith("rss_reuters"): return "Reuters"
        if uid.startswith("rss_ap"): return "AP"
        if uid.startswith("rss_washpost"): return "WashPost"
        if uid.startswith("rss_wsj"): return "WSJ"
        if uid.startswith("rss_"): return "RSS"
        if uid.startswith("jobs"): return "Job Posting"
        if uid.startswith("uspto:"): return "USPTO"
        if uid.startswith("reddit:"): return "Reddit"
    return "Unknown"


def _days_since(ts: str) -> float:
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - dt).days
    except Exception:
        return 999.0


def _explain_node(n: dict) -> str:
    """Markdown explanation of why a node is a bottleneck."""
    name = n.get("name", "Unknown")
    label = n.get("label", "")
    srs = float(n.get("srs_score") or 0)
    betweenness = float(n.get("betweenness") or 0)
    concentration = float(n.get("concentration") or 0)
    is_ap = n.get("is_articulation_point", False)
    parts = []
    if is_ap:
        parts.append(
            f"**{name}** is an articulation point — removing it from the supply chain "
            "graph would disconnect other nodes, making it structurally irreplaceable in the short term."
        )
    if betweenness > 0.5:
        parts.append(
            f"It sits on a disproportionate share of the shortest paths between all supply "
            f"chain nodes (betweenness={betweenness:.3f}), meaning most routes depend on it as an intermediary."
        )
    elif betweenness > 0.15:
        parts.append(f"It acts as a significant intermediary in the supply chain (betweenness={betweenness:.3f}).")
    if concentration > 0.80:
        parts.append(
            f"Supplier concentration is critically high ({concentration:.2f}/1.0) — there are very few "
            "qualified alternatives, and requalification typically takes 2–5 years."
        )
    elif concentration > 0.50:
        parts.append(f"Supplier concentration is elevated ({concentration:.2f}/1.0), indicating limited alternatives.")
    label_context = {
        "Geography": "Geographic concentration adds geopolitical and natural disaster risk that cannot be diversified through supplier selection alone — all suppliers in the same country share the same tail risk.",
        "Company": "Single-company dependency means any disruption to this firm's operations propagates immediately across its entire customer base.",
        "Material": "Material constraints are particularly sticky — new sources require geological prospecting, extraction infrastructure, and process qualification, each taking years.",
        "Process": "Process know-how is tacit and hard to transfer — loss of this capability typically requires multi-year reconstruction and significant capital investment.",
        "Equipment": "Capital equipment has 1–3 year lead times and highly proprietary specifications, making rapid substitution nearly impossible even with unlimited capital.",
        "Technology": "Proprietary technology creates deep lock-in; competitors require years of R&D to replicate equivalent capability.",
        "Regulation": "Regulatory chokepoints can shift rapidly with policy changes, creating both downside risk and asymmetric information advantage.",
    }
    if label in label_context:
        parts.append(label_context[label])
    if not parts:
        parts.append(f"{name} has a high structural risk score (SRS={srs:.3f}) based on its position in the dependency graph.")
    return "\n\n".join(parts)


def _explain_node_text(n: dict) -> str:
    """Plain-text explanation for vis.js tooltip (no markdown)."""
    name = n.get("name", "Unknown")
    srs = float(n.get("srs_score") or 0)
    betweenness = float(n.get("betweenness") or 0)
    concentration = float(n.get("concentration") or 0)
    is_ap = n.get("is_articulation_point", False)
    lines = [f"{name}  |  SRS: {srs:.3f}  |  {n.get('label', '')}"]
    if is_ap:
        lines.append("★ Articulation point — removal disconnects graph")
    lines.append(f"Betweenness: {betweenness:.3f}   Concentration: {concentration:.2f}")
    return "\n".join(lines)


def _vis_network_html(nodes: list[dict], edges: list[dict]) -> str:
    """Build a self-contained vis.js HTML network graph."""
    label_colors = {
        "Geography":  "#4e79a7",
        "Company":    "#f28e2b",
        "Material":   "#e15759",
        "Process":    "#76b7b2",
        "Technology": "#59a14f",
        "Regulation": "#edc948",
        "Equipment":  "#b07aa1",
    }
    vis_nodes = []
    for n in nodes:
        srs = float(n.get("srs_score") or 0)
        is_critical = srs > 0.60
        is_ap = n.get("is_ap", False)
        color = "#c0392b" if is_critical else label_colors.get(n.get("label", ""), "#7f8c8d")
        border = "#ff4444" if is_critical else "#444"
        size = 12 + srs * 28
        tooltip = _explain_node_text(n).replace("\n", "<br>").replace("'", "\\'")
        vis_nodes.append({
            "id": n["id"],
            "label": n.get("name", n["id"]),
            "title": tooltip,
            "color": {"background": color, "border": border,
                      "highlight": {"background": "#e74c3c", "border": "#ff6666"}},
            "size": round(size, 1),
            "borderWidth": 3 if is_critical else 1,
            "shadow": {"enabled": is_ap, "color": "rgba(255,0,0,0.6)", "size": 12},
            "font": {"color": "#ffffff", "size": 11},
            "is_critical": is_critical,
        })
    vis_edges = [
        {"id": i, "from": e["src"], "to": e["tgt"],
         "label": e.get("rel_type", ""),
         "color": {"color": "#555555", "opacity": 0.7},
         "arrows": {"to": {"enabled": True, "scaleFactor": 0.4}},
         "font": {"color": "#888", "size": 9},
         "width": 1}
        for i, e in enumerate(edges)
    ]
    nodes_json = json.dumps(vis_nodes)
    edges_json = json.dumps(vis_edges)
    critical_ids_json = json.dumps([n["id"] for n in nodes if float(n.get("srs_score") or 0) > 0.60])

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<script src="https://unpkg.com/vis-network@9.1.2/standalone/umd/vis-network.min.js"></script>
<style>
  body {{ margin:0; background:#0e1117; }}
  #graph {{ width:100%; height:540px; }}
  #legend {{ position:absolute; top:8px; right:12px; background:rgba(0,0,0,0.6);
             border-radius:6px; padding:8px 12px; font-family:sans-serif; font-size:11px; color:#ccc; }}
  #legend div {{ margin:3px 0; }}
  #legend span {{ display:inline-block; width:12px; height:12px;
                 border-radius:50%; margin-right:6px; vertical-align:middle; }}
</style>
</head>
<body>
<div style="position:relative">
  <div id="graph"></div>
  <div id="legend">
    <div><span style="background:#c0392b;border:2px solid #ff4444"></span>Critical bottleneck (SRS&gt;0.6)</div>
    <div><span style="background:#4e79a7"></span>Geography</div>
    <div><span style="background:#f28e2b"></span>Company</div>
    <div><span style="background:#e15759"></span>Material</div>
    <div><span style="background:#76b7b2"></span>Process</div>
    <div><span style="background:#59a14f"></span>Technology</div>
    <div><span style="background:#edc948"></span>Regulation</div>
    <div><span style="background:#b07aa1"></span>Equipment</div>
    <div style="margin-top:6px;font-size:10px;color:#888">Node size ∝ SRS score<br>★ = articulation point (shadow)</div>
  </div>
</div>
<script>
const NODES_DATA = {nodes_json};
const EDGES_DATA = {edges_json};
const CRITICAL_IDS = {critical_ids_json};

const nodesDS = new vis.DataSet(NODES_DATA);
const edgesDS = new vis.DataSet(EDGES_DATA);

const options = {{
  physics: {{
    enabled: true,
    barnesHut: {{ gravitationalConstant: -9000, springLength: 130, damping: 0.18 }},
    stabilization: {{ iterations: 200, fit: true }},
  }},
  interaction: {{ hover: true, tooltipDelay: 80, navigationButtons: true, keyboard: true }},
  nodes: {{ shape: "dot" }},
  edges: {{ smooth: {{ type: "continuous" }} }},
}};

const network = new vis.Network(
  document.getElementById("graph"),
  {{ nodes: nodesDS, edges: edgesDS }},
  options
);

// Pulsing border for critical nodes
let bright = true;
if (CRITICAL_IDS.length > 0) {{
  setInterval(() => {{
    nodesDS.update(CRITICAL_IDS.map(id => ({{
      id,
      color: {{
        background: bright ? "#e74c3c" : "#8e1a0e",
        border:     bright ? "#ff6644" : "#aa2200",
      }},
    }})));
    bright = !bright;
  }}, 850);
}}
</script>
</body>
</html>"""


# ──────────────────────────────────────────────
# PAGE 1: Overview
# ──────────────────────────────────────────────

if page == "Overview":
    st.title("Bottleneck Discovery Engine")
    st.markdown("AI semiconductor supply chain — structural risk intelligence")

    with st.spinner("Loading dashboard data…"):
        opps   = get_opportunities()
        nodes  = get_top_nodes()
        net    = get_network_data()
        ev_rows = get_evidence_rows()
        trend  = get_risk_trend()

    # ── KPI cards ──────────────────────────────
    from hypotheses.hypothesis_manager import HypothesisManager
    all_hyps = HypothesisManager().list_all(500)
    now_utc = datetime.now(timezone.utc)

    total_bn   = len(nodes)
    critical   = sum(1 for n in nodes if float(n.get("srs_score") or 0) > 0.8)
    new_week   = sum(1 for h in all_hyps if _days_since(h.get("created_at", "")) <= 7)
    active_hyps = [h for h in all_hyps if h.get("status") == "active"]
    avg_days   = (
        sum(_days_since(h.get("created_at", "")) for h in active_hyps) / len(active_hyps)
        if active_hyps else 0
    )

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Total Bottlenecks", total_bn)
    c2.metric("Critical  (SRS > 0.8)", critical)
    c3.metric("New This Week", new_week)
    c4.metric("Avg Days Active", f"{avg_days:.0f} d")

    st.markdown("---")

    # ── Severity bar chart ─────────────────────
    if nodes:
        st.subheader("Bottleneck Severity")
        ordered = list(reversed(nodes))          # lowest first so highest is at top
        names  = [n.get("name", n.get("node_id", "?")) for n in ordered]
        scores = [float(n.get("srs_score") or 0) for n in ordered]
        aps    = [n.get("is_articulation_point", False) for n in ordered]
        labels = [("★ " if ap else "") + name for name, ap in zip(names, aps)]

        fig = go.Figure(go.Bar(
            x=scores,
            y=labels,
            orientation="h",
            marker=dict(
                color=scores,
                colorscale=[[0, "#27ae60"], [0.5, "#f39c12"], [1.0, "#c0392b"]],
                cmin=0, cmax=1,
                showscale=True,
                colorbar=dict(title="SRS", thickness=14, len=0.9),
            ),
            hovertemplate="<b>%{y}</b><br>SRS: %{x:.3f}<extra></extra>",
        ))
        fig.update_layout(
            height=460,
            margin=dict(l=10, r=80, t=10, b=30),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(range=[0, 1], gridcolor="#2a2a2a", title="SRS Score", color="#aaa"),
            yaxis=dict(tickfont=dict(size=11, color="#ddd")),
            font=dict(color="#ffffff"),
        )
        st.plotly_chart(fig, use_container_width=True)

    st.markdown("---")

    # ── Supply chain network graph ─────────────
    st.subheader("Supply Chain Network")
    st.caption("Node size ∝ SRS score · Red nodes = critical bottlenecks (pulsing) · Hover for details")
    if net.get("error"):
        st.warning(f"Neo4j unavailable — start Neo4j Desktop to load the network. ({net['error'][:80]})")
    elif not net.get("nodes"):
        st.info("Run structural analysis first to populate SRS scores in Neo4j.")
    else:
        components.html(_vis_network_html(net["nodes"], net["edges"]), height=560, scrolling=False)

    st.markdown("---")

    # ── Ranked opportunities table ─────────────
    st.subheader("Ranked Opportunities")
    if not opps:
        st.info("No active hypotheses yet. Run the hypothesis generator first.")
    else:
        table_rows = []
        for o in opps:
            table_rows.append({
                "Tier": tier_badge(o["tier"]),
                "OPS": f"{o['ops_final']:.3f}",
                "Node": o.get("node_name", ""),
                "Statement": (o.get("statement") or "")[:100] + "…",
                "Conf": f"{o['confidence']:.2f}",
                "IAS": f"{o['ias']:.2f}",
                "ACH": "✓" if o["ach_reviewed"] else "—",
                "Evid +/-": f"{o['evidence_for_count']}/{o['evidence_against_count']}",
            })
        st.dataframe(table_rows, use_container_width=True, hide_index=True)

    st.markdown("---")

    # ── Evidence table ─────────────────────────
    st.subheader("Bottleneck Evidence")
    st.caption("All evidence collected — sortable, filterable. Expand below for raw snippets.")
    if not ev_rows:
        st.info("No evidence collected yet — run the entity resolver and evidence updater.")
    else:
        entities = ["All"] + sorted(set(r["Entity"] for r in ev_rows))
        sources  = sorted(set(r["Source"] for r in ev_rows))
        fc1, fc2, fc3 = st.columns([2, 3, 1])
        sel_entity = fc1.selectbox("Entity", entities, key="ev_entity")
        sel_source = fc2.multiselect("Source", sources, default=sources, key="ev_source")
        sel_dir    = fc3.selectbox("Direction", ["All", "supports", "against"], key="ev_dir")

        filtered = ev_rows
        if sel_entity != "All":
            filtered = [r for r in filtered if r["Entity"] == sel_entity]
        if sel_source:
            filtered = [r for r in filtered if r["Source"] in sel_source]
        if sel_dir != "All":
            filtered = [r for r in filtered if sel_dir in r["Direction"]]

        st.dataframe(
            [{
                "Entity":      r["Entity"],
                "Type":        r["Type"],
                "Severity":    r["Severity"],
                "Source":      r["Source"],
                "Direction":   r["Direction"],
                "Detected At": r["Detected At"],
                "Evidence":    r["_snippet"][:90] + "…" if len(r["_snippet"]) > 90 else r["_snippet"],
            } for r in filtered],
            use_container_width=True,
            hide_index=True,
        )

        if filtered:
            with st.expander(f"Raw evidence snippets — {len(filtered)} items"):
                for r in filtered[:40]:
                    st.markdown(
                        f"**{r['Entity']}** · {r['Direction']} · *{r['Source']}* · {r['Detected At']}"
                    )
                    st.code(r["_snippet"], language=None)
                    st.markdown("---")

    st.markdown("---")

    # ── Time-series risk trend ─────────────────
    st.subheader("Risk Trend — Active Bottlenecks (30 days)")
    if trend and any(c > 0 for c in trend["cumulative"]):
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=trend["dates"], y=trend["cumulative"],
            mode="lines+markers", name="Cumulative active",
            line=dict(color="#e74c3c", width=2.5),
            fill="tozeroy", fillcolor="rgba(231,76,60,0.12)",
            marker=dict(size=5),
        ))
        fig2.add_trace(go.Bar(
            x=trend["dates"], y=trend["new_daily"],
            name="New per day",
            marker_color="rgba(52,152,219,0.65)",
            yaxis="y2",
        ))
        fig2.update_layout(
            height=260,
            margin=dict(l=10, r=50, t=10, b=30),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            xaxis=dict(gridcolor="#222", color="#aaa"),
            yaxis=dict(title="Cumulative", gridcolor="#222", color="#aaa"),
            yaxis2=dict(title="New", overlaying="y", side="right", color="#5b9bd5", showgrid=False),
            legend=dict(x=0.01, y=0.98, font=dict(size=11)),
            font=dict(color="#ffffff"),
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("Time series will populate as the hypothesis engine runs over multiple days.")

    st.markdown("---")

    # ── Bottleneck Briefing ────────────────────
    if opps:
        st.subheader("Bottleneck Briefing")
        st.caption("Plain-English explanation of each identified opportunity")
        node_map = {n["node_id"]: n for n in nodes}
        for o in opps:
            node = node_map.get(o.get("node_id"), {})
            lbl = f"{tier_badge(o['tier'])} **{o.get('node_name')}** — OPS {o['ops_final']:.3f}"
            with st.expander(lbl):
                st.markdown(f"**Hypothesis:** {o.get('statement', '—')}")
                st.markdown("---")
                if node:
                    st.markdown(_explain_node(node))
                cc1, cc2, cc3 = st.columns(3)
                cc1.metric("Confidence", f"{o['confidence']:.0%}")
                cc2.metric("Evidence For / Against", f"{o['evidence_for_count']} / {o['evidence_against_count']}")
                cc3.metric("ACH Reviewed", "Yes" if o["ach_reviewed"] else "No")

    st.markdown("**OPS = (DR × IAS × 0.40) + (S × 0.20) + (CM × 0.15) + (VA × 0.15) + (RT × 0.10) × ACH_robustness**")


# ──────────────────────────────────────────────
# PAGE 2: Hypothesis Detail
# ──────────────────────────────────────────────

elif page == "Hypothesis Detail":
    st.title("Hypothesis Detail")

    from hypotheses.hypothesis_manager import HypothesisManager
    from contrarian.ach_engine import get_ach_review, approve_hypothesis
    from scoring.opportunity_scorer import score_hypothesis

    mgr = HypothesisManager()
    all_hyps = mgr.list_all(50)
    if not all_hyps:
        st.info("No hypotheses generated yet.")
    else:
        options = {f"{h['node_name']} — {(h['statement'] or '')[:60]}": h["id"] for h in all_hyps}
        selected_label = st.selectbox("Select hypothesis", list(options.keys()))
        hid = options[selected_label]
        h = mgr.get(hid)
        if not h:
            st.error("Hypothesis not found")
        else:
            scored = score_hypothesis(h)
            col1, col2, col3, col4 = st.columns(4)
            col1.metric("OPS Final", f"{scored['ops_final']:.3f}")
            col2.metric("Confidence", f"{scored['confidence']:.2f}")
            col3.metric("Tier", f"T{scored['tier']}")
            col4.metric("ACH Robustness", f"{scored['robustness_ach']:.2f}")

            st.markdown(f"**Statement:** {h['statement']}")
            st.markdown(f"**Node:** {h.get('node_name')} ({h.get('node_id')}) | SRS={h.get('srs_score_at_creation', 0):.3f}")
            st.markdown(f"**Status:** {h.get('status')} | Awareness Layer: {h.get('awareness_layer')}")

            st.subheader("Falsification Criteria")
            fc = json.loads(h.get("falsification_criteria") or "[]")
            for i, c in enumerate(fc, 1):
                st.markdown(f"{i}. {c}")

            col_a, col_b = st.columns(2)
            with col_a:
                st.subheader("Evidence For")
                ef = json.loads(h.get("evidence_for") or "[]")
                for e in ef:
                    st.markdown(f"✅ {e}")
            with col_b:
                st.subheader("Evidence Against")
                ea = json.loads(h.get("evidence_against") or "[]")
                for e in ea:
                    st.markdown(f"❌ {e}")

            ach = get_ach_review(hid)
            if ach:
                st.subheader("ACH Matrix")
                matrix = json.loads(ach["matrix"])
                evidence = ef + ea or ["(structural risk)"]
                rows = []
                for i, ev in enumerate(evidence):
                    row = {"Evidence": ev[:60]}
                    for hyp_key in matrix:
                        row[hyp_key[:30]] = matrix[hyp_key][i] if i < len(matrix[hyp_key]) else "N"
                    rows.append(row)
                st.dataframe(rows, use_container_width=True, hide_index=True)
                st.metric("Robustness", f"{ach['robustness']:.2f}")

                if ach["passed"] and not ach["human_approved"]:
                    if st.button("Approve for Tier 1"):
                        approve_hypothesis(hid)
                        mgr.set_status(hid, "active")
                        st.success("Hypothesis approved for Tier 1")
                        st.cache_data.clear()
            else:
                st.info("ACH review not yet run (requires confidence >= 0.80)")


# ──────────────────────────────────────────────
# PAGE 3: Knowledge Graph
# ──────────────────────────────────────────────

elif page == "Knowledge Graph":
    st.title("Supply Chain Knowledge Graph")
    st.markdown("Top-20 nodes by SRS (Supply Risk Score)")

    with st.spinner("Loading…"):
        nodes = get_top_nodes()

    if not nodes:
        st.info("Run structural analysis first.")
    else:
        rows = []
        for i, n in enumerate(nodes, 1):
            rows.append({
                "Rank": i,
                "Node ID": n.get("node_id"),
                "Name": n.get("name"),
                "Label": n.get("label"),
                "SRS": f"{float(n.get('srs_score') or 0):.3f}",
                "Betweenness": f"{float(n.get('betweenness') or 0):.4f}",
                "Conc.": f"{float(n.get('concentration') or 0):.2f}",
                "AP": "★" if n.get("is_articulation_point") else "",
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)

    if nodes:
        st.markdown("---")
        st.subheader("Bottleneck Explanations")
        st.caption("Why each node is a structural risk — graph topology + supply concentration")
        for i, n in enumerate(nodes[:10], 1):
            srs = float(n.get("srs_score") or 0)
            ap_tag = " ★AP" if n.get("is_articulation_point") else ""
            with st.expander(f"#{i} {n.get('name')}{ap_tag} — SRS {srs:.3f}"):
                st.markdown(_explain_node(n))

    st.markdown("---")
    st.markdown("**AP** = Articulation Point (removal disconnects supply graph)")
    st.markdown("**Conc** = Supplier Concentration (1 = sole source)")
    st.markdown(f"[Open Neo4j Browser](http://localhost:7474/browser/) — explore the full DKG")


# ──────────────────────────────────────────────
# PAGE 4: Orphan Queue
# ──────────────────────────────────────────────

elif page == "Orphan Queue":
    st.title("Orphan Queue — Manual Review")
    st.markdown("Documents that could not be automatically routed to a taxonomy node.")

    from resolution.orphan_queue import OrphanQueue
    oq = OrphanQueue()
    counts = oq.counts()
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Orphans", counts["total"])
    col2.metric("Pending Review", counts["pending"])
    col3.metric("Resolved", counts["resolved"])

    pending = oq.pending(limit=20)
    if not pending:
        st.success("No pending orphans.")
    else:
        for o in pending:
            with st.expander(f"[{o['best_similarity']:.2f}] {o['title'][:80]}"):
                st.markdown(f"**Reason:** {o['reason']}")
                st.markdown(f"**Best match:** {o['best_match_node']} (sim={o['best_similarity']:.3f})")
                st.markdown(f"**Candidate entities:** {', '.join(o['candidate_entities'][:10])}")
                st.markdown(f"**Excerpt:** {o['text_excerpt'][:300]}")
                node_id_input = st.text_input("Resolve to node ID", key=f"node_{o['uid']}")
                col_a, col_b = st.columns(2)
                if col_a.button("Resolve", key=f"res_{o['uid']}"):
                    if node_id_input:
                        oq.resolve(o["uid"], node_id_input)
                        st.success(f"Resolved to {node_id_input}")
                        st.rerun()
                if col_b.button("Dismiss", key=f"dis_{o['uid']}"):
                    oq.dismiss(o["uid"])
                    st.rerun()


# ──────────────────────────────────────────────
# PAGE 5: System Status
# ──────────────────────────────────────────────

elif page == "System Status":
    st.title("System Status")

    if st.button("Refresh"):
        st.cache_data.clear()

    with st.spinner("Loading…"):
        stats = get_system_stats()

    st.subheader("Ingest Queue (SQLite)")
    ingest = stats["ingest"]
    col1, col2 = st.columns(2)
    col1.metric("Total Documents", ingest.get("total", 0))
    col2.metric("Pending Processing", ingest.get("pending", 0))
    by_source = ingest.get("by_source", {})
    if by_source:
        st.dataframe(
            [{"Source": k, "Count": v} for k, v in sorted(by_source.items(), key=lambda x: -x[1])],
            use_container_width=True, hide_index=True,
        )

    st.subheader("Entity Resolution Queue (Redis)")
    proc = stats["processor"]
    col1, col2 = st.columns(2)
    col1.metric("Entity Queue Depth", proc.get("entity_queue_depth", 0))
    col2.metric("Pending in SQLite", proc.get("pending", 0))

    st.subheader("Hypothesis Engine")
    hyp = stats["hypotheses"]
    col1, col2, col3 = st.columns(3)
    col1.metric("Total Hypotheses", hyp.get("total", 0))
    col2.metric("Active", hyp.get("by_status", {}).get("active", 0))
    col3.metric("Needs ACH Review", hyp.get("needs_ach_review", 0))

    st.metric("Hypotheses Awaiting Human Approval", stats["pending_ach"])

    st.subheader("Schedule (Celery Beat)")
    schedule = {
        "GitHub + HN": "Every 4h",
        "RSS (Tier 1-2 specialist)": "Every 6h",
        "RSS (Tier 3 newspapers)": "Every 6h",
        "EDGAR + arXiv": "Daily 06:00",
        "Reddit": "Every 6h",
        "USPTO patents": "Weekly Mon 05:00",
        "Job postings": "Daily 07:00",
        "Document Processor": "Every 2h",
        "Entity Resolver": "Every 1h",
        "Structural Analysis": "Weekly Mon 02:00",
        "Hypothesis Generator": "Weekly Mon 02:30",
        "ACH Review": "Weekly Mon 04:00",
        "IAS Window Check": "Every 6h",
    }
    for task, freq in schedule.items():
        st.markdown(f"- **{task}**: {freq}")
