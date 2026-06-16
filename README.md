# Bottleneck Discovery Engine (BDE)

A local-AI-powered system to identify structural chokepoints in the AI supply chain
before financial markets recognize them.

**Goal:** Find the next ASML, the next CoWoS packaging constraint, the next ABF substrate
bottleneck — 2–3 layers below where market attention is focused, before analysts price it in.

---

## What This Is NOT

This is not a news monitor or a sentiment scraper. Most systems that claim to track "AI supply chain risk" are just keyword-matching news feeds. This system:

- Builds a **Dependency Knowledge Graph** (DKG) in Neo4j as its primary data model
- Generates **explicit, falsifiable hypotheses** — not vague signals
- **Stress-tests every hypothesis** using Analysis of Competing Hypotheses (ACH) before surfacing it
- Tracks an **Information Asymmetry Score** to estimate how far ahead of the market a signal is
- Maintains a **Calibration Loop** (Brier scoring) so confidence scores mean something over time

---

## Architecture

```
[Sources] → [Ingestion] → [Entity Resolution] → [Neo4j DKG]
                                                      ↓
                                          [Structural Analysis Engine]
                                            (articulation points,
                                             betweenness centrality,
                                             supplier concentration)
                                                      ↓
                                          [Hypothesis Engine]
                                            (Gemma 2 9B generates
                                             falsifiable hypotheses
                                             from structural candidates)
                                                      ↓
                                          [ACH Contrarian Engine]
                                            (stress-tests hypotheses,
                                             generates competing theories,
                                             classifies evidence C/I/N/A)
                                                      ↓
                                     [Scoring + Dashboard + Alerts]
                                       (Streamlit, ranked opportunities,
                                        calibration charts, Orphan Queue)
```

---

## Key Components

### 1. Dependency Knowledge Graph (DKG)
Neo4j graph database as the primary data model.

**Node types:** Company | Material | Process | Technology | Geography | Regulation | Equipment

**Edge types:** PRODUCES | DEPENDS_ON | COMPETES_WITH | REGULATES | SUBSTITUTES_FOR | ENABLES | CONTROLS

**Edge properties:**
- `confidence` (0–1): how certain is this relationship
- `criticality` (0–1): how critical is this dependency
- `requalification_years`: how long to qualify an alternative supplier
- `source`: where this edge comes from
- `date_verified`: when last confirmed

### 2. Entity Resolution Layer
Documents route to DKG nodes via embedding similarity thresholds:

| Similarity | Action |
|---|---|
| > 0.80 | Auto-route to matched node |
| 0.55 – 0.80 | Mistral 7B disambiguates |
| < 0.55 | Orphan Evidence Queue |

The Orphan Queue is a **first-class component** — frame-breaking signals always arrive as orphans first. It is reviewed weekly for clusters that might represent new nodes or hypotheses.

### 3. Structural Analysis Engine (Weekly Batch)
Runs graph algorithms on the DKG every Monday at 2am:
- **Articulation point detection** — nodes whose removal disconnects the supply chain graph
- **Betweenness centrality** — most critical intermediaries
- **Supplier concentration score** — `1 - (1 / qualified_supplier_count)`
- **Structural Risk Score (SRS)** — `centrality × concentration × criticality_weight`

Top-N SRS nodes become candidates for hypothesis generation.

### 4. Hypothesis Engine
Gemma 2 9B generates falsifiable hypotheses from structural candidates:

Each hypothesis stores:
- `statement`: the explicit claim
- `structural_basis`: which DKG nodes triggered it
- `order`: 1st, 2nd, or 3rd order dependency
- `confidence`: 0–1, updated by evidence (weighted, not raw count)
- `falsification_criteria`: what evidence would kill this hypothesis
- `awareness_layer`: where in the 6-layer IAS model this sits

**Critical design principle:** Falsification criteria are set AT CREATION TIME, before any evidence is collected. This prevents goalpost-moving.

### 5. ACH Contrarian Engine
Every hypothesis above 0.60 confidence is stress-tested before surfacing:

1. Gemma generates 3–5 competing alternative hypotheses (adversarial framing)
2. Build ACH matrix: rows = evidence, columns = hypotheses
3. Classify each cell: C (consistent), I (inconsistent), N/A
4. **Only diagnostic evidence updates confidence** — evidence consistent with ALL hypotheses has near-zero diagnostic value
5. Hypotheses above 0.80 confidence → flagged for human Red Team review

### 6. Information Asymmetry Score (IAS)
6-layer awareness model:

| Layer | Who knows |
|---|---|
| 0 | Company insiders |
| 1 | Equipment engineers / procurement |
| 2 | Industry specialists |
| 3 | Financial analysts |
| 4 | General financial media |
| 5 | Priced in |

**Alpha window = Layer 1 signal not yet at Layer 3**

**WARNING:** IAS ≠ alpha for Asian equities — many bottlenecks are priced via domestic institutional channels that bypass the analyst intermediation layer. Always check Vehicle Accessibility (VA) before sizing a position.

### 7. Opportunity Scoring Formula
```
Alpha_core = DR × IAS            # interaction term, not additive
OPS = (Alpha_core × 0.40) + (Scarcity × 0.20) + (CatalyticMoment × 0.15)
      + (VehicleAccessibility × 0.15) + (ResolutionTimeline × 0.10)
OPS_final = OPS × Robustness_from_ACH
```

**Tiers:**
- ≥ 8.5 → Act now
- 7.0 – 8.4 → Deep research
- 5.0 – 6.9 → Monitor
- < 5.0 → Noise

### 8. Calibration Loop (Brier Scoring)
Every promoted hypothesis logs:
- `confidence_at_log`
- `predicted_recognition_date`
- `actual_recognition_date`
- `brier_score` (calculated monthly)

Without this, confidence scores are decorative. This is what makes the system self-improving.

---

## Correlated Evidence Deduplication
When one event (e.g., "TSMC CoWoS capacity news") routes to multiple DKG nodes, it is NOT counted independently at each node:

```
hash(source_domain + event_date) → 1/n weight discount across all n affected nodes
```

This prevents a single news cycle from inflating confidence across an entire sector.

---

## Practitioner Source Weighting
A GPU engineer's GitHub issue is high weight for inference bottlenecks, near-zero for packaging/materials.

Weights are domain-scoped, not flat. A source that is authoritative in one domain is not assumed authoritative in another.

---

## 4-Lens Bottleneck Filter
Every structural candidate passes through:

1. **Physical irreproducibility** — is this constraint geologically or physically hard to replicate?
2. **Concentration ratio** — CR3 > 70% = warning; CR3 > 90% = chokepoint
3. **Lead time** — how long to spin up alternative capacity?
4. **Substitutability** — is there a drop-in replacement, or is requalification measured in years?

---

## Data Sources

### Phase 1 (Implemented)
- GitHub Issues/PRs (20 monitored repos: vllm, pytorch, NVIDIA/nccl, HuggingFace, DeepSpeed, etc.)
- Hacker News (Algolia API)
- SEC EDGAR (8-K, 10-Q, 10-K filings — full text search API, free)
- arXiv (cs.AR + cs.DC + cs.LG papers)
- RSS feeds (SemiAnalysis, IEEE Spectrum, EE Times)

### Phase 2 (Planned)
- Reddit: r/chipdesign, r/MachineLearning, r/hardware, r/semiconductors
- Telegram public channels
- USPTO patent bulk data API
- Job posting velocity (LinkedIn/Indeed as leading indicator)
- Conference video transcripts (YouTube + Whisper)

---

## Local AI Stack (No API costs)

| Task | Model | VRAM |
|---|---|---|
| Document routing | Mistral 7B | ~4.5GB |
| Entity disambiguation | Mistral 7B | ~4.5GB |
| Hypothesis generation | Gemma 2 9B | ~5.5GB |
| ACH analysis | Gemma 2 9B | ~5.5GB |
| Embeddings | nomic-embed-text | ~0.5GB |

Models run one at a time via Ollama. Mistral and Gemma are never loaded simultaneously.

**Hardware requirements:** 8–16GB VRAM GPU + 16GB+ RAM

---

## Project Structure

```
BDE/
├── taxonomy/
│   └── taxonomy.json          # 300-500 canonical AI supply chain concepts
├── ingestion/
│   ├── github_ingestor.py
│   ├── hn_ingestor.py
│   ├── edgar_ingestor.py
│   ├── arxiv_ingestor.py
│   └── rss_ingestor.py
├── processing/
│   └── document_processor.py
├── resolution/
│   ├── embedder.py
│   ├── resolver.py
│   ├── mistral_disambiguator.py
│   └── orphan_queue.py
├── analysis/
│   └── structural_analyzer.py
├── hypotheses/
│   ├── hypothesis_generator.py
│   ├── evidence_updater.py
│   └── hypothesis_manager.py
├── contrarian/
│   └── ach_engine.py
├── scoring/
│   ├── opportunity_scorer.py
│   └── calibration_log.py
├── dashboard/
│   └── app.py
├── config.py                  # Service URLs, model names, thresholds
├── celery_app.py              # Task queue + beat schedule
├── verify_setup.py            # Phase 0 health check
└── requirements.txt
```

---

## Setup (Phase 0)

### Prerequisites
- Python 3.11+ (use `py` launcher on Windows, not `python`)
- Ollama installed (ollama.com)
- Neo4j Desktop installed (neo4j.com/download)
- Memurai or Redis for Windows

### Installation
```bash
# Clone
git clone https://github.com/<your-username>/bottleneck-discovery-engine.git
cd bottleneck-discovery-engine

# Virtual environment
py -m venv venv
venv\Scripts\Activate.ps1  # Windows PowerShell

# Install dependencies
pip install --no-cache-dir -r requirements.txt
```

### Services
```bash
# Neo4j Desktop: create a Local DBMS named "BDE", password "bde_password"
# Install APOC + Graph Data Science plugins, then Start

# Redis/Memurai: starts as Windows service automatically

# Ollama models
ollama pull mistral        # ~4.4GB
ollama pull gemma2:9b      # ~5.5GB
ollama pull nomic-embed-text  # ~0.3GB
```

### Verify everything is running
```bash
py verify_setup.py
```

Expected output:
```
Neo4j: OK
Redis: OK
Ollama: OK
All services running. Phase 0 complete.
```

---

## Build Phases

| Phase | Goal | Status |
|---|---|---|
| 0 | Environment setup — all services running | In Progress |
| 1 | Canonical taxonomy (300+ nodes) + DKG schema | Pending |
| 2 | Ingestion pipeline (GitHub, HN, EDGAR, arXiv, RSS) | Pending |
| 3 | Entity Resolution Layer | Pending |
| 4 | Structural Analysis Engine (graph algorithms) | Pending |
| 5 | Hypothesis Engine | Pending |
| 6 | ACH Contrarian Engine | Pending |
| 7 | Scoring + Dashboard (Streamlit) | Pending |
| 8 | Expand sources (Reddit, Telegram, patents, jobs) | Pending |

---

## Key Design Decisions and Why

**Graph-first, not document-first.** News-first systems drown in noise. The graph enforces structure: every piece of evidence must connect to a known node or go to the Orphan Queue. This forces discipline.

**Falsification criteria set at hypothesis creation.** If you write criteria after collecting evidence, you will unconsciously write them to match what you already believe. The system enforces pre-registration.

**ACH, not self-referential review.** The contrarian engine generates independent competing hypotheses, not a checklist review of the primary hypothesis. A hypothesis that survives three independent competing framings is meaningfully more robust.

**Orphan Queue is not a trash bin.** Every frame-breaking discovery in investment research looks like noise at first. The Orphan Queue is where frame-breaking signals queue up. It is reviewed weekly by a human, not discarded.

**Calibration over confidence.** The system tracks every promoted hypothesis against reality. The Brier score is calculated monthly. Without this, confidence scores drift toward whatever feels right to the person running the system.

---

## License

MIT License. Use freely, attribute appreciated.

---

## Acknowledgements

Architecture developed iteratively through adversarial review — tested against critics representing:
1. Academic graph theorist (graph centrality ≠ operational fragility)
2. Veteran semiconductor investor (re-qualification time is unmeasurable from public data)
3. Bayesian epistemologist (correlated evidence inflates confidence systematically)
4. Information asymmetry specialist (IAS ≠ alpha for Asian equities — domestic institutional pricing)
