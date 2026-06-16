"""
load_taxonomy.py — Loads BDE taxonomy into Neo4j with embeddings.

Run from BDE root:
    python taxonomy/load_taxonomy.py

Steps:
  1. Create schema: constraints + vector index
  2. Load concept nodes with nomic-embed-text embeddings
  3. Load relationships from edges list
  4. Print validation summary
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from loguru import logger
from neo4j import GraphDatabase
from ollama import Client as OllamaClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD, OLLAMA_BASE_URL, EMBEDDING_MODEL

TAXONOMY_PATH = Path(__file__).parent / "taxonomy.json"
EMBEDDING_DIM = 768
BATCH_SIZE = 20


def setup_schema(session) -> None:
    labels = ["Company", "Material", "Process", "Technology", "Geography", "Regulation", "Equipment"]
    for label in labels:
        session.run(f"CREATE CONSTRAINT IF NOT EXISTS FOR (n:{label}) REQUIRE n.id IS UNIQUE")

    session.run("""
        CREATE FULLTEXT INDEX concept_search IF NOT EXISTS
        FOR (n:Company|Material|Process|Technology|Geography|Regulation|Equipment)
        ON EACH [n.name, n.description, n.aliases_str]
    """)

    for label in labels:
        try:
            session.run(f"""
                CREATE VECTOR INDEX {label.lower()}_embedding IF NOT EXISTS
                FOR (n:{label}) ON n.embedding
                OPTIONS {{indexConfig: {{`vector.dimensions`: {EMBEDDING_DIM}, `vector.similarity_function`: 'cosine'}}}}
            """)
        except Exception:
            pass

    logger.info("Schema constraints and indexes created.")


def get_embedding(client: OllamaClient, text: str, retries: int = 3) -> list[float]:
    for attempt in range(retries):
        try:
            resp = client.embeddings(model=EMBEDDING_MODEL, prompt=text)
            return resp["embedding"]
        except Exception as e:
            if attempt == retries - 1:
                logger.warning(f"Embedding failed after {retries} attempts: {e}")
                return [0.0] * EMBEDDING_DIM
            time.sleep(1)


def build_embed_text(concept: dict) -> str:
    aliases = ", ".join(concept.get("aliases", []))
    desc = concept.get("description", "")
    return f"{concept['label']}: {concept['name']}. Aliases: {aliases}. {desc}"


def load_nodes(driver, concepts: list[dict]) -> int:
    ollama = OllamaClient(host=OLLAMA_BASE_URL)
    loaded = 0

    for i in range(0, len(concepts), BATCH_SIZE):
        batch = concepts[i : i + BATCH_SIZE]
        logger.info(f"Embedding nodes {i+1}–{min(i+BATCH_SIZE, len(concepts))} of {len(concepts)}...")

        nodes_data = []
        for c in batch:
            embed_text = build_embed_text(c)
            embedding = get_embedding(ollama, embed_text)
            nodes_data.append({
                "id": c["id"],
                "label": c["label"],
                "name": c["name"],
                "description": c.get("description", ""),
                "aliases_str": ", ".join(c.get("aliases", [])),
                "criticality": c.get("criticality", 0.5),
                "embedding": embedding,
                **{k: v for k, v in c.get("properties", {}).items() if isinstance(v, (str, int, float, bool))},
            })

        with driver.session() as session:
            for nd in nodes_data:
                label = nd.pop("label")
                session.run(
                    f"""
                    MERGE (n:{label} {{id: $id}})
                    SET n += $props
                    """,
                    id=nd["id"],
                    props=nd,
                )
                loaded += 1

    return loaded


def load_edges(driver, edges: list[dict], concept_index: dict) -> int:
    rel_map = {
        "PRODUCES": "PRODUCES",
        "DEPENDS_ON": "DEPENDS_ON",
        "COMPETES_WITH": "COMPETES_WITH",
        "REGULATES": "REGULATES",
        "SUBSTITUTES_FOR": "SUBSTITUTES_FOR",
        "ENABLES": "ENABLES",
        "CONTROLS": "CONTROLS",
        "LOCATED_IN": "LOCATED_IN",
        "USES": "USES",
        "MANUFACTURES": "MANUFACTURES",
    }

    loaded = 0
    skipped = 0

    with driver.session() as session:
        for edge in edges:
            src = edge["source"]
            tgt = edge["target"]
            rel = edge["relation"]

            if src not in concept_index or tgt not in concept_index:
                logger.warning(f"Skipping edge {src}→{tgt}: node not found in taxonomy")
                skipped += 1
                continue

            src_label = concept_index[src]["label"]
            tgt_label = concept_index[tgt]["label"]
            props = edge.get("properties", {})
            safe_props = {k: v for k, v in props.items() if isinstance(v, (str, int, float, bool))}

            cypher = f"""
                MATCH (a:{src_label} {{id: $src}})
                MATCH (b:{tgt_label} {{id: $tgt}})
                MERGE (a)-[r:{rel_map.get(rel, rel)}]->(b)
                SET r += $props
            """
            session.run(cypher, src=src, tgt=tgt, props=safe_props)
            loaded += 1

    if skipped:
        logger.warning(f"{skipped} edges skipped (source/target not found)")
    return loaded


def validate(driver) -> dict:
    with driver.session() as session:
        node_count = session.run("MATCH (n) RETURN count(n) as c").single()["c"]
        edge_count = session.run("MATCH ()-[r]->() RETURN count(r) as c").single()["c"]
        orphan_count = session.run(
            "MATCH (n) WHERE NOT (n)--() RETURN count(n) as c"
        ).single()["c"]

        by_label = {}
        for row in session.run(
            "MATCH (n) RETURN labels(n)[0] as label, count(n) as c ORDER BY c DESC"
        ):
            by_label[row["label"]] = row["c"]

        by_rel = {}
        for row in session.run(
            "MATCH ()-[r]->() RETURN type(r) as rel, count(r) as c ORDER BY c DESC"
        ):
            by_rel[row["rel"]] = row["c"]

    return {
        "nodes": node_count,
        "edges": edge_count,
        "orphans": orphan_count,
        "by_label": by_label,
        "by_rel": by_rel,
    }


def main() -> None:
    logger.info(f"Loading taxonomy from {TAXONOMY_PATH}")
    data = json.loads(TAXONOMY_PATH.read_text(encoding="utf-8"))
    concepts = data["concepts"]
    edges = data["edges"]
    concept_index = {c["id"]: c for c in concepts}

    logger.info(f"Taxonomy: {len(concepts)} concepts, {len(edges)} edges")

    driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
    driver.verify_connectivity()
    logger.info("Connected to Neo4j.")

    with driver.session() as session:
        setup_schema(session)

    node_count = load_nodes(driver, concepts)
    logger.info(f"Loaded {node_count} nodes.")

    edge_count = load_edges(driver, edges, concept_index)
    logger.info(f"Loaded {edge_count} edges.")

    stats = validate(driver)
    driver.close()

    print("\n" + "=" * 50)
    print(f"  Nodes loaded : {stats['nodes']}")
    print(f"  Edges loaded : {stats['edges']}")
    print(f"  Orphan nodes : {stats['orphans']}")
    print("\n  By label:")
    for label, count in stats["by_label"].items():
        print(f"    {label:<15} {count}")
    print("\n  By relationship:")
    for rel, count in stats["by_rel"].items():
        print(f"    {rel:<20} {count}")
    print("=" * 50)

    if stats["nodes"] < 300:
        logger.error(f"Only {stats['nodes']} nodes — target is 300+")
        sys.exit(1)
    if stats["edges"] < 200:
        logger.error(f"Only {stats['edges']} edges — target is 200+")
        sys.exit(1)

    print("\nPhase 1 taxonomy load complete.\n")


if __name__ == "__main__":
    main()
