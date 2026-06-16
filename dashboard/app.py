"""
BDE Dashboard — Phase 7: Streamlit interface for supply chain bottleneck intelligence.

Pages:
  1. Overview   — Opportunity table ranked by OPS, tier summary
  2. Hypothesis — Drill into one hypothesis: evidence, ACH matrix, score breakdown
  3. Knowledge Graph — Top-SRS nodes table + Neo4j link
  4. Orphan Queue — Manual review of unresolved documents
  5. System Status — Ingest queue, entity queue, Celery beat health

Run:
  cd news-sentiment/BDE
  .venv/Scripts/activate
  streamlit run dashboard/app.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import streamlit as st

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
st.sidebar.caption("BDE v0.7 · Phase 7")

# ──────────────────────────────────────────────
# Helpers
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


def tier_badge(tier: int) -> str:
    colors = {1: "🔴", 2: "🟠", 3: "🟡"}
    return f"{colors.get(tier, '⚪')} T{tier}"


# ──────────────────────────────────────────────
# PAGE 1: Overview
# ──────────────────────────────────────────────

if page == "Overview":
    st.title("Bottleneck Discovery Engine")
    st.markdown("Ranked supply chain bottleneck opportunities by OPS (Opportunity Score)")

    opps = get_opportunities()

    col1, col2, col3, col4 = st.columns(4)
    tier1 = sum(1 for o in opps if o["tier"] == 1)
    tier2 = sum(1 for o in opps if o["tier"] == 2)
    tier3 = sum(1 for o in opps if o["tier"] == 3)
    col1.metric("Total Opportunities", len(opps))
    col2.metric("Tier 1 (High)", tier1)
    col3.metric("Tier 2 (Medium)", tier2)
    col4.metric("Tier 3 (Monitoring)", tier3)

    if not opps:
        st.info("No active hypotheses yet. Run the hypothesis generator first.")
    else:
        rows = []
        for o in opps:
            rows.append({
                "Tier": tier_badge(o["tier"]),
                "OPS": f"{o['ops_final']:.3f}",
                "Node": o.get("node_name", ""),
                "Statement": (o.get("statement") or "")[:80] + "...",
                "Conf": f"{o['confidence']:.2f}",
                "IAS": f"{o['ias']:.2f}",
                "ACH": "✓" if o["ach_reviewed"] else "—",
                "Evid +/-": f"{o['evidence_for_count']}/{o['evidence_against_count']}",
            })
        st.dataframe(rows, use_container_width=True, hide_index=True)

    st.markdown("---")
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
                alts = json.loads(ach["alternatives"])
                evidence = ef + ea or ["(structural risk)"]
                col_headers = ["Evidence"] + list(matrix.keys())
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

    st.markdown("---")
    st.markdown("**AP** = Articulation Point (removal disconnects supply graph)")
    st.markdown("**Conc** = Supplier Concentration (1 = sole source)")
    neo4j_url = "http://localhost:7474/browser/"
    st.markdown(f"[Open Neo4j Browser]({neo4j_url}) — explore the full DKG")


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
                node_id_input = st.text_input(f"Resolve to node ID", key=f"node_{o['uid']}")
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

    stats = get_system_stats()

    st.subheader("Ingest Queue (SQLite)")
    ingest = stats["ingest"]
    col1, col2 = st.columns(2)
    col1.metric("Total Documents", ingest.get("total", 0))
    col2.metric("Pending Processing", ingest.get("pending", 0))
    by_source = ingest.get("by_source", {})
    if by_source:
        st.dataframe(
            [{"Source": k, "Count": v} for k, v in by_source.items()],
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
        "RSS (Tier 1-2)": "Every 6h",
        "EDGAR + arXiv": "Daily 06:00",
        "Document Processor": "Every 2h",
        "Entity Resolver": "Every 1h",
        "Structural Analysis": "Weekly Mon 02:00",
        "Hypothesis Generator": "Weekly Mon 02:30",
        "ACH Review": "Weekly Mon 04:00",
        "IAS Window Check": "Every 6h",
    }
    for task, freq in schedule.items():
        st.markdown(f"- **{task}**: {freq}")
