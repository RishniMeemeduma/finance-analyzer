"""Verify the project setup is correct. Run this before moving to Phase 1."""
import sys
from pathlib import Path

# Add project root to Python path so we can import from src
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.config import settings
import psycopg
import anthropic


def check_config():
    print("Checking config...")
    assert settings.database_url, "DATABASE_URL not set"
    assert settings.anthropic_api_key, "ANTHROPIC_API_KEY not set"
    print(f"  Database URL: {settings.database_url}")
    print(f"  Anthropic key: {settings.anthropic_api_key[:12]}...")
    print("  OK")


def check_database():
    print("Checking database connection...")
    raw_url = settings.database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(raw_url) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT version()")
            version = cur.fetchone()[0]
            print(f"  Connected: {version[:60]}...")
            cur.execute("CREATE EXTENSION IF NOT EXISTS vector")
            print("  pgvector extension ready")
    print("  OK")


def check_anthropic():
    print("Checking Anthropic API...")
    client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
    response = client.messages.create(
        model="claude-haiku-4-5-20251001",
        max_tokens=20,
        messages=[{"role": "user", "content": "Say 'setup works' in 3 words."}],
    )
    print(f"  Claude says: {response.content[0].text}")
    print("  OK")


if __name__ == "__main__":
    check_config()
    check_database()
    check_anthropic()
    print("\nSetup verified. Ready for Phase 1.")
