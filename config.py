from dotenv import load_dotenv
import os

load_dotenv()

# Neo4j
NEO4J_URI = os.getenv("NEO4J_URI", "bolt://localhost:7687")
NEO4J_USER = os.getenv("NEO4J_USER", "neo4j")
NEO4J_PASSWORD = os.getenv("NEO4J_PASSWORD", "bde_password")

# Redis / Celery
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379/0")
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL

# Ollama
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
ROUTING_MODEL = "mistral"
ANALYSIS_MODEL = "gemma2:9b"
EMBEDDING_MODEL = "nomic-embed-text"

# Entity resolution thresholds
SIMILARITY_HIGH = 0.80   # auto-route
SIMILARITY_LOW  = 0.55   # below this → Orphan Queue

# Paths
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TAXONOMY_PATH = os.path.join(BASE_DIR, "taxonomy", "taxonomy.json")
DATA_DIR = os.path.join(BASE_DIR, "data")
