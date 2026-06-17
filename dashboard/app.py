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

PAGES = [
    "Overview", "Hypothesis Detail", "Knowledge Graph",
    "Orphan Queue", "System Status", "Geo Risk Map",
    "Scenario Simulator", "Commodity Intelligence",
]
page = st.sidebar.selectbox("Navigate", PAGES)
st.sidebar.markdown("---")
st.sidebar.caption("BDE v0.9 · Phase 7")

COUNTRY_ISO3: dict[str, str] = {
    "Taiwan": "TWN", "Japan": "JPN", "United States": "USA",
    "South Korea": "KOR", "Netherlands": "NLD", "China": "CHN",
    "Germany": "DEU", "Switzerland": "CHE", "Ireland": "IRL",
    "Singapore": "SGP", "Malaysia": "MYS", "Israel": "ISR",
    "Australia": "AUS", "India": "IND", "Vietnam": "VNM",
    "Thailand": "THA", "Philippines": "PHL", "United Kingdom": "GBR",
    "France": "FRA", "Belgium": "BEL", "Finland": "FIN",
}

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
def get_geo_risk():
    """Aggregate SRS by country from Geography nodes + Company LOCATED_IN edges."""
    try:
        from neo4j import GraphDatabase
        from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
        from hypotheses.hypothesis_manager import HypothesisManager

        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        with driver.session() as s:
            geo = s.run("""
                MATCH (g:Geography)
                RETURN g.id AS node_id, g.name AS name,
                       coalesce(g.srs_score, 0.0) AS srs_score,
                       coalesce(g.is_articulation_point, false) AS is_ap,
                       coalesce(g.betweenness, 0.0) AS betweenness,
                       coalesce(g.concentration, 0.0) AS concentration
                ORDER BY g.srs_score DESC
            """).data()
            companies = s.run("""
                MATCH (c:Company)-[:LOCATED_IN]->(g:Geography)
                RETURN g.name AS country, g.id AS geo_id,
                       c.name AS company_name, c.id AS company_id,
                       coalesce(c.srs_score, 0.0) AS company_srs
                ORDER BY c.srs_score DESC
            """).data()
        driver.close()

        mgr = HypothesisManager()
        all_hyps = mgr.list_all(200)
        geo_ids = {g["node_id"] for g in geo}
        geo_hyps: dict[str, list] = defaultdict(list)
        for h in all_hyps:
            if h.get("node_id") in geo_ids:
                geo_hyps[h["node_id"]].append(h)

        return {"geo": geo, "companies": companies,
                "hypotheses": dict(geo_hyps), "error": None}
    except Exception as e:
        return {"geo": [], "companies": [], "hypotheses": {}, "error": str(e)}


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


@st.cache_data(ttl=300)
def get_commodity_ranking() -> list[dict]:
    try:
        from commodities.store import CommodityStore
        return CommodityStore().get_latest_ranking()
    except Exception:
        return []


@st.cache_data(ttl=300)
def get_commodity_history(commodity_name: str) -> list[dict]:
    try:
        from commodities.store import CommodityStore
        return CommodityStore().get_commodity_history(commodity_name, days=30)
    except Exception:
        return []


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

    st.subheader("Telegram Alerts")
    try:
        from alerts.telegram import is_configured
        tg_ok = is_configured()
    except Exception:
        tg_ok = False
    if tg_ok:
        st.success("Telegram configured — alerts active")
        st.markdown(
            "- IAS window closing — when Tier 1-2 hypothesis appears in mainstream media\n"
            "- New Tier-1 signal — when OPS crosses 0.60 for the first time\n"
            "- ACH review needed — when confidence crosses 0.80\n"
            "- Daily digest — 08:00 UTC"
        )
    else:
        st.warning(
            "Telegram not configured — add `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to `.env`. "
            "See `.env.example` for setup instructions."
        )

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
        "Telegram Daily Digest": "Daily 08:00 UTC",
        "Telegram New Tier-1 Check": "Every 6h",
        "Telegram ACH Needed Check": "Every 4h",
    }
    for task, freq in schedule.items():
        st.markdown(f"- **{task}**: {freq}")


# ──────────────────────────────────────────────
# PAGE 6: Geo Risk Map
# ──────────────────────────────────────────────

elif page == "Geo Risk Map":
    st.title("Geographic Supply Chain Risk")
    st.markdown(
        "Countries colored by aggregate SRS score from taxonomy nodes. "
        "Click a country on the map or use the selector to drill down."
    )

    with st.spinner("Loading geographic risk data…"):
        geo_data = get_geo_risk()

    if geo_data.get("error"):
        st.warning(f"Neo4j unavailable — start Neo4j Desktop to load this page. ({geo_data['error'][:100]})")
    elif not geo_data["geo"]:
        st.info("No Geography nodes with SRS scores found. Run structural analysis first.")
    else:
        # ── Build country aggregation ────────────────────────────────────
        ISO3_TO_NAME = {v: k for k, v in COUNTRY_ISO3.items()}
        country_data: dict[str, dict] = {}

        for g in geo_data["geo"]:
            iso3 = COUNTRY_ISO3.get(g["name"])
            if not iso3:
                continue
            country_data[g["name"]] = {
                "iso3":     iso3,
                "node_id":  g["node_id"],
                "srs":      float(g.get("srs_score") or 0),
                "is_ap":    bool(g.get("is_ap", False)),
                "betweenness": float(g.get("betweenness") or 0),
                "concentration": float(g.get("concentration") or 0),
                "companies": [],
            }

        # Attach companies; boost country SRS if a company is riskier
        for c in geo_data["companies"]:
            cname = c["country"]
            if cname in country_data:
                country_data[cname]["companies"].append(c)
                company_srs = float(c.get("company_srs") or 0)
                if company_srs > country_data[cname]["srs"]:
                    country_data[cname]["srs"] = company_srs

        locs  = [d["iso3"] for d in country_data.values()]
        z     = [d["srs"]  for d in country_data.values()]
        names = list(country_data.keys())

        hover_text = []
        for name, d in country_data.items():
            companies = [c["company_name"] for c in d["companies"][:3]]
            comp_str = ", ".join(companies) if companies else "—"
            ap_str = " · Articulation Point" if d["is_ap"] else ""
            hover_text.append(
                f"<b>{name}</b>{ap_str}<br>SRS: {d['srs']:.3f}<br>"
                f"Key suppliers: {comp_str}"
            )

        # ── Choropleth ───────────────────────────────────────────────────
        fig = go.Figure(go.Choropleth(
            locations=locs,
            z=z,
            locationmode="ISO-3",
            colorscale=[[0, "#27ae60"], [0.45, "#f39c12"], [1.0, "#c0392b"]],
            zmin=0, zmax=1,
            colorbar=dict(title="SRS", thickness=14, len=0.85,
                          tickfont=dict(color="#fff"), title_font=dict(color="#fff")),
            hovertemplate="%{text}<extra></extra>",
            text=hover_text,
            marker_line_color="#333",
            marker_line_width=0.5,
            selectedpoints=[],
        ))
        fig.update_layout(
            geo=dict(
                showframe=False, showcoastlines=True,
                coastlinecolor="#555", bgcolor="#0e1117",
                landcolor="#1a1d24", oceancolor="#0e1117",
                showocean=True, lakecolor="#0e1117",
                showlakes=True,
            ),
            paper_bgcolor="#0e1117",
            margin=dict(l=0, r=0, t=0, b=0),
            height=460,
            font=dict(color="#ffffff"),
        )

        # Render map — capture click events
        event = st.plotly_chart(fig, use_container_width=True, on_select="rerun")

        # Determine selected country from click or manual selectbox
        clicked_iso3: str | None = None
        if event and hasattr(event, "selection") and event.selection:
            pts = getattr(event.selection, "points", [])
            if pts:
                clicked_iso3 = pts[0].get("location")

        available = sorted(country_data.keys(), key=lambda n: -country_data[n]["srs"])
        sel_country = st.selectbox(
            "Select country (or click map above)",
            ["— select —"] + available,
            index=0,
            key="geo_select",
        )
        if sel_country != "— select —":
            clicked_iso3 = COUNTRY_ISO3.get(sel_country)

        # ── Drill-down panel ─────────────────────────────────────────────
        if clicked_iso3:
            sel_name = ISO3_TO_NAME.get(clicked_iso3) or clicked_iso3
            cd = country_data.get(sel_name)
            if cd:
                st.markdown("---")
                st.subheader(f"Drill-down: {sel_name}")
                m1, m2, m3 = st.columns(3)
                m1.metric("SRS Score", f"{cd['srs']:.3f}")
                m2.metric("Articulation Point", "Yes" if cd["is_ap"] else "No")
                m3.metric("Companies in KG", len(cd["companies"]))

                # Companies table
                if cd["companies"]:
                    st.markdown("**Companies located in this region:**")
                    st.dataframe(
                        [{"Company": c["company_name"],
                          "Company ID": c["company_id"],
                          "SRS": f"{float(c.get('company_srs') or 0):.3f}"}
                         for c in sorted(cd["companies"], key=lambda x: -float(x.get("company_srs") or 0))],
                        use_container_width=True, hide_index=True,
                    )

                # Hypotheses linked to this geography node
                hyps_for_node = geo_data["hypotheses"].get(cd["node_id"], [])
                if hyps_for_node:
                    st.markdown("**Active hypotheses for this region:**")
                    for h in hyps_for_node:
                        conf = float(h.get("confidence") or 0)
                        badge = "🔴" if conf >= 0.7 else ("🟠" if conf >= 0.5 else "🟡")
                        with st.expander(f"{badge} {(h.get('statement') or '')[:80]}"):
                            st.markdown(f"**Confidence:** {conf:.0%}")
                            st.markdown(f"**Falsification criteria:**")
                            fc = json.loads(h.get("falsification_criteria") or "[]")
                            for i, c in enumerate(fc, 1):
                                st.markdown(f"{i}. {c}")
                else:
                    st.info("No active hypotheses linked to this geography node.")

                # Recent evidence from Neo4j
                try:
                    from hypotheses.evidence_updater import recent_evidence_for_node
                    docs = recent_evidence_for_node(cd["node_id"], limit=5)
                    if docs:
                        st.markdown("**Recent evidence documents:**")
                        for d in docs:
                            src = d.get("d.source", "")
                            title = d.get("d.title", "")
                            pub = (d.get("d.published_at") or "")[:10]
                            st.markdown(f"- [{src}] {title} *({pub})*")
                except Exception:
                    pass


# ──────────────────────────────────────────────
# PAGE 7: Scenario Simulator (What-If)
# ──────────────────────────────────────────────

elif page == "Scenario Simulator":
    st.title("Scenario Simulator")
    st.markdown(
        "Select a node and simulate its removal from the supply chain. "
        "The system re-runs the full structural analysis and shows before/after SRS scores "
        "for every affected node — without writing anything to Neo4j."
    )

    with st.spinner("Loading node list…"):
        all_nodes = get_top_nodes()

    if not all_nodes:
        st.info("Run structural analysis first to populate SRS scores.")
    else:
        node_options = {f"{n.get('name')} ({n.get('label')}, SRS {float(n.get('srs_score') or 0):.3f})": n["node_id"]
                       for n in all_nodes}
        sel_label = st.selectbox("Node to remove from the supply chain:", list(node_options.keys()))
        sel_node_id = node_options[sel_label]
        sel_node_name = sel_label.split(" (")[0]

        st.markdown(
            f"> **Simulation:** What happens if **{sel_node_name}** is removed from the supply chain graph? "
            f"All path-based metrics (betweenness, articulation points) are recomputed on the remaining graph."
        )

        run_sim = st.button("Run Simulation", type="primary")

        if run_sim:
            with st.spinner(f"Re-running structural analysis without {sel_node_name}… (10-30 seconds)"):
                from analysis.structural_analyzer import run_whatif
                result = run_whatif(sel_node_id)

            if "error" in result:
                st.error(f"Simulation failed: {result['error']}")
            else:
                st.success(f"Simulation complete — {result['nodes_remaining']} nodes analyzed.")
                st.markdown("---")

                # ── Summary KPIs ─────────────────────────────────────────
                total_delta = result["total_srs_delta"]
                ap_change   = result["new_ap_count"] - result["old_ap_count"]

                k1, k2, k3, k4 = st.columns(4)
                k1.metric("Nodes Remaining", result["nodes_remaining"],
                          delta=f"-1 ({sel_node_name} removed)", delta_color="off")
                k2.metric("Total SRS Change", f"{total_delta:+.3f}",
                          delta_color="inverse")
                k3.metric("Articulation Points Before", result["old_ap_count"])
                k4.metric("Articulation Points After", result["new_ap_count"],
                          delta=f"{ap_change:+d}", delta_color="inverse")

                st.markdown("---")

                comparison = result["comparison"]
                if not comparison:
                    st.info("No score changes detected — this node had minimal structural impact.")
                else:
                    # ── Diverging delta chart ────────────────────────────
                    st.subheader(f"SRS Score Changes After Removing {sel_node_name}")
                    st.caption("Red = risk increased (node was suppressing it) · Green = risk decreased (node was amplifying it)")

                    top_changed = [r for r in comparison if abs(r["delta"]) > 0.001][:20]
                    if top_changed:
                        bar_names   = [r["name"] for r in reversed(top_changed)]
                        bar_deltas  = [r["delta"] for r in reversed(top_changed)]
                        bar_colors  = ["#e74c3c" if d > 0 else "#27ae60" for d in bar_deltas]
                        bar_ap_new  = [r.get("now_ap", False) for r in reversed(top_changed)]
                        bar_labels  = [("★ " if ap else "") + name for name, ap in zip(bar_names, bar_ap_new)]

                        fig_delta = go.Figure(go.Bar(
                            x=bar_deltas,
                            y=bar_labels,
                            orientation="h",
                            marker_color=bar_colors,
                            hovertemplate="<b>%{y}</b><br>ΔSRS: %{x:+.4f}<extra></extra>",
                        ))
                        fig_delta.add_vline(x=0, line_color="#888", line_width=1)
                        fig_delta.update_layout(
                            height=max(300, len(top_changed) * 28),
                            margin=dict(l=10, r=20, t=10, b=10),
                            paper_bgcolor="rgba(0,0,0,0)",
                            plot_bgcolor="rgba(0,0,0,0)",
                            xaxis=dict(title="ΔSRS", gridcolor="#2a2a2a", color="#aaa",
                                       zeroline=True, zerolinecolor="#666"),
                            yaxis=dict(tickfont=dict(size=10, color="#ddd")),
                            font=dict(color="#ffffff"),
                        )
                        st.plotly_chart(fig_delta, use_container_width=True)

                    # ── Before / After top-5 comparison ─────────────────
                    st.subheader("Top-5 Bottlenecks: Before vs After")
                    before_sorted = sorted(comparison, key=lambda r: -r["srs_before"])[:5]
                    after_sorted  = sorted(comparison, key=lambda r: -r["srs_after"])[:5]

                    col_b, col_a = st.columns(2)
                    with col_b:
                        st.markdown("**Before removal**")
                        st.dataframe(
                            [{"#": i + 1, "Node": r["name"], "SRS": f"{r['srs_before']:.4f}",
                              "AP": "★" if r.get("was_ap") else ""}
                             for i, r in enumerate(before_sorted)],
                            use_container_width=True, hide_index=True,
                        )
                    with col_a:
                        st.markdown(f"**After removing {sel_node_name}**")
                        st.dataframe(
                            [{"#": i + 1, "Node": r["name"], "SRS": f"{r['srs_after']:.4f}",
                              "AP": "★" if r.get("now_ap") else "",
                              "ΔSRS": f"{r['delta']:+.4f}"}
                             for i, r in enumerate(after_sorted)],
                            use_container_width=True, hide_index=True,
                        )

                    # ── Full comparison table ────────────────────────────
                    st.markdown("---")
                    with st.expander(f"Full comparison table ({len(comparison)} nodes)"):
                        st.dataframe(
                            [{
                                "Node":       r["name"],
                                "Label":      r["label"],
                                "SRS Before": r["srs_before"],
                                "SRS After":  r["srs_after"],
                                "ΔSRS":       r["delta"],
                                "Was AP":     "★" if r.get("was_ap") else "",
                                "Now AP":     "★" if r.get("now_ap") else "",
                            } for r in comparison],
                            use_container_width=True, hide_index=True,
                        )


# ──────────────────────────────────────────────
# PAGE 8: Commodity Intelligence
# ──────────────────────────────────────────────

elif page == "Commodity Intelligence":
    st.title("Commodity Shortage Intelligence")
    st.markdown(
        "Daily 5-agent AI debate across 35 strategic commodities. "
        "Supply Stress Score 0–100 based on supply growth, demand, inventory, "
        "geographic concentration, geopolitical risk, and production lead times."
    )

    def _stress_badge(score) -> str:
        if score is None:
            return "⚠️ —"
        s = float(score)
        if s >= 70:
            return f"🔴 {s:.1f}"
        if s >= 40:
            return f"🟠 {s:.1f}"
        return f"🟢 {s:.1f}"

    def _delta_str(delta) -> str:
        if delta is None:
            return "—"
        d = float(delta)
        if abs(d) < 0.05:
            return "—"
        return f"{d:+.1f} {'▲' if d > 0 else '▼'}"

    def _outlook_badge(val) -> str:
        return {"bearish": "🔻 bearish", "bullish": "🔺 bullish", "neutral": "➡️ neutral"}.get(
            (val or "").lower(), "➡️ neutral"
        )

    def _stars(n) -> str:
        try:
            n = max(1, min(5, int(n)))
        except (TypeError, ValueError):
            return "—"
        return "★" * n + "☆" * (5 - n)

    with st.spinner("Loading commodity rankings…"):
        ranking = get_commodity_ranking()

    if not ranking:
        st.info(
            "No commodity analysis has run yet. "
            "Click **Run Analysis Now** below to generate the first ranking — "
            "takes 20-30 minutes for all 35 commodities."
        )
    else:
        latest_date = ranking[0].get("run_date", "")
        valid = [r for r in ranking if not r.get("parse_error") and r.get("supply_stress_score") is not None]
        avg_score = sum(float(r["supply_stress_score"]) for r in valid) / max(1, len(valid))
        top1 = valid[0] if valid else None

        col1, col2, col3, col4 = st.columns(4)
        col1.metric("Last Analysis", latest_date or "—")
        col2.metric("Commodities Scored", f"{len(valid)} / {len(ranking)}")
        col3.metric("Highest Stress", f"{top1['commodity']} ({top1['supply_stress_score']:.0f})" if top1 else "—")
        col4.metric("Average Score", f"{avg_score:.1f}")

        st.subheader("Top 20 Commodity Shortage Ranking")
        top20 = valid[:20]
        table_rows = []
        for r in top20:
            table_rows.append({
                "#": r.get("rank", ""),
                "Commodity": r["commodity"],
                "Sector": r.get("sector", ""),
                "Score": _stress_badge(r.get("supply_stress_score")),
                "24h Δ": _delta_str(r.get("score_delta")),
                "6M": _outlook_badge(r.get("outlook_6m")),
                "12M": _outlook_badge(r.get("outlook_12m")),
                "3Y": _outlook_badge(r.get("outlook_3y")),
                "5Y": _outlook_badge(r.get("outlook_5y")),
                "Conf": _stars(r.get("confidence")),
            })
        st.dataframe(table_rows, use_container_width=True, hide_index=True)

        # ── Drill-down ──────────────────────────────────────────────────────
        st.markdown("---")
        st.subheader("Commodity Drill-Down")
        all_names = [r["commodity"] for r in valid]
        if all_names:
            sel = st.selectbox("Select commodity", all_names, key="comm_sel")
            row = next((r for r in valid if r["commodity"] == sel), None)
            if row:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Supply Stress Score", f"{row['supply_stress_score']:.1f} / 100")
                c2.metric("24h Change", _delta_str(row.get("score_delta")))
                c3.metric("Confidence", _stars(row.get("confidence")))
                c4.metric("Consensus", str(row.get("consensus") or "—").title())

                oc1, oc2, oc3, oc4 = st.columns(4)
                oc1.metric("6-Month Outlook", _outlook_badge(row.get("outlook_6m")))
                oc2.metric("12-Month Outlook", _outlook_badge(row.get("outlook_12m")))
                oc3.metric("3-Year Outlook", _outlook_badge(row.get("outlook_3y")))
                oc4.metric("5-Year Outlook", _outlook_badge(row.get("outlook_5y")))

                # Sub-score breakdown
                st.subheader("Score Breakdown (9 components)")
                sub_labels = [
                    "Supply Growth (15%)",
                    "Demand Growth (15%)",
                    "Inventory Depletion (15%)",
                    "Geographic Concentration (15%)",
                    "Refining Concentration (10%)",
                    "Geopolitical Risk (10%)",
                    "Export Restrictions (10%)",
                    "Replacement Difficulty (5%)",
                    "Production Lead Time (5%)",
                ]
                sub_keys = [
                    "supply_growth_score", "demand_growth_score", "inventory_depletion_score",
                    "geographic_concentration_score", "refining_concentration_score",
                    "geopolitical_risk_score", "export_restriction_score",
                    "replacement_difficulty_score", "production_lead_time_score",
                ]
                sub_scores = [row.get(k) or 0 for k in sub_keys]
                bar_colors = ["#e74c3c" if s >= 70 else "#e67e22" if s >= 40 else "#27ae60" for s in sub_scores]
                fig_sub = go.Figure(go.Bar(
                    x=sub_scores, y=sub_labels, orientation="h",
                    marker_color=bar_colors,
                    hovertemplate="<b>%{y}</b>: %{x}<extra></extra>",
                ))
                fig_sub.update_layout(
                    height=320, margin=dict(l=10, r=10, t=10, b=10),
                    paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                    xaxis=dict(range=[0, 100], gridcolor="#2a2a2a", color="#aaa"),
                    yaxis=dict(tickfont=dict(size=11, color="#ddd")),
                    font=dict(color="#fff"),
                )
                st.plotly_chart(fig_sub, use_container_width=True)

                # Agent findings
                st.subheader("Agent Findings")
                agent_data = [
                    ("Supply Analyst", row.get("agent1_finding")),
                    ("Geopolitical Risk", row.get("agent2_finding")),
                    ("Mining / Engineering", row.get("agent3_finding")),
                    ("Demand Analyst", row.get("agent4_finding")),
                    ("Skeptic / Portfolio Manager", row.get("agent5_critique")),
                ]
                for agent_name, finding in agent_data:
                    with st.expander(agent_name, expanded=False):
                        st.write(finding or "_No finding recorded._")

                # Catalysts / Risks / Indicators
                cat_col, risk_col, ind_col = st.columns(3)
                with cat_col:
                    st.markdown("**Key Catalysts (worsen shortage)**")
                    cats = json.loads(row.get("key_catalysts") or "[]")
                    for c in cats:
                        st.markdown(f"- {c}")
                with risk_col:
                    st.markdown("**Risks to Thesis (reduce shortage)**")
                    risks = json.loads(row.get("key_risks") or "[]")
                    for r_ in risks:
                        st.markdown(f"- {r_}")
                with ind_col:
                    st.markdown("**Monitoring Indicators**")
                    inds = json.loads(row.get("monitoring_indicators") or "[]")
                    for m in inds:
                        st.markdown(f"- {m}")

                st.caption(f"Articles used in this analysis: {row.get('articles_used', 0)}")

                # Historical trend (appears after day 2+)
                history = get_commodity_history(sel)
                if len(history) > 1:
                    st.subheader(f"{sel} — Supply Stress Score History")
                    hist_dates = [h["run_date"] for h in history]
                    hist_scores = [h["supply_stress_score"] for h in history]
                    fig_hist = go.Figure(go.Scatter(
                        x=hist_dates, y=hist_scores,
                        mode="lines+markers",
                        line=dict(color="#e74c3c", width=2),
                        fill="tozeroy",
                        fillcolor="rgba(231,76,60,0.12)",
                    ))
                    fig_hist.update_layout(
                        height=220, margin=dict(l=10, r=10, t=10, b=20),
                        paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor="rgba(0,0,0,0)",
                        xaxis=dict(gridcolor="#2a2a2a", color="#aaa"),
                        yaxis=dict(range=[0, 100], gridcolor="#2a2a2a", color="#aaa", title="Score"),
                        font=dict(color="#fff"),
                    )
                    st.plotly_chart(fig_hist, use_container_width=True)

    # Manual trigger
    st.markdown("---")
    st.markdown("**Manual Trigger** — runs all 35 commodities immediately via local Mistral (20-30 min)")
    if st.button("Run Analysis Now", type="secondary", key="comm_run"):
        with st.spinner(
            "Running 5-agent Mistral debate on 35 commodities. "
            "You can navigate away and come back — results persist to disk."
        ):
            try:
                from commodities.analyst import run_all
                result = run_all()
                if result.get("status") == "complete":
                    st.success(
                        f"Done: {result['succeeded']}/{result['total']} succeeded "
                        f"in {result['elapsed_seconds']}s"
                    )
                    st.cache_data.clear()
                    st.rerun()
                elif result.get("status") == "skipped":
                    st.info("Analysis already ran today — results above are current.")
                else:
                    st.error(f"Unexpected result: {result}")
            except Exception as e:
                st.error(f"Analysis failed: {e}")
