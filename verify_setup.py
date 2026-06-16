"""Run this after Phase 0 to confirm all services are connected."""
import sys

REQUIRED_MODELS = {"mistral", "nomic-embed-text"}


def check_neo4j():
    try:
        from neo4j import GraphDatabase
        from config import NEO4J_URI, NEO4J_USER, NEO4J_PASSWORD
        driver = GraphDatabase.driver(NEO4J_URI, auth=(NEO4J_USER, NEO4J_PASSWORD))
        driver.verify_connectivity()
        driver.close()
        print("  Neo4j        OK")
        return True
    except Exception as e:
        print(f"  Neo4j        FAIL — {e}")
        return False


def check_redis():
    try:
        import redis
        from config import REDIS_URL
        r = redis.from_url(REDIS_URL)
        r.ping()
        print("  Redis        OK")
        return True
    except Exception as e:
        print(f"  Redis        FAIL — {e}")
        return False


def check_ollama():
    try:
        import httpx
        from config import OLLAMA_BASE_URL
        r = httpx.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        pulled = {m["name"].split(":")[0] for m in r.json().get("models", [])}
        missing = REQUIRED_MODELS - pulled
        if missing:
            print(f"  Ollama       FAIL — missing models: {missing}")
            print(f"               Run: ollama pull {' && ollama pull '.join(missing)}")
            return False
        print(f"  Ollama       OK — models present: {pulled}")
        return True
    except Exception as e:
        print(f"  Ollama       FAIL — {e}")
        return False


def check_taxonomy():
    import os
    from config import TAXONOMY_PATH
    if os.path.exists(TAXONOMY_PATH):
        import json
        with open(TAXONOMY_PATH, encoding="utf-8") as f:
            data = json.load(f)
        count = len(data.get("concepts", []))
        print(f"  Taxonomy     OK — {count} concepts loaded")
    else:
        print("  Taxonomy     MISSING — Phase 1 not started yet (expected)")
    return True  # not a blocker for Phase 0


if __name__ == "__main__":
    print("\nBDE Phase 0 — Service Verification\n" + "="*40)
    results = [check_neo4j(), check_redis(), check_ollama(), check_taxonomy()]
    print("="*40)
    if all(results):
        print("All systems OK. Phase 0 complete.\n")
    else:
        print("Some services failed. Check output above.\n")
        sys.exit(1)
