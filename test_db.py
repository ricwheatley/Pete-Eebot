import os
import psycopg
from urllib.parse import quote_plus

# Build a safe DATABASE_URL using env vars or sensible defaults
USER = os.getenv("POSTGRES_USER", "pete_user")
PASS = os.getenv("POSTGRES_PASSWORD", "pete@69smithyBRIDGE")
HOST = os.getenv("POSTGRES_HOST", "127.0.0.1")
PORT = os.getenv("POSTGRES_PORT", "5432")
DB   = os.getenv("POSTGRES_DB", "pete_db")

DATABASE_URL = f"postgresql://{quote_plus(USER)}:{quote_plus(PASS)}@{HOST}:{PORT}/{DB}"

print("Attempting to connect to the database...")

try:
    with psycopg.connect(DATABASE_URL) as conn:
        print("✅ Success! Connection to the database was successful.")
        with conn.cursor() as cur:
            cur.execute("SELECT version();")
            db_version = cur.fetchone()
            print(f"PostgreSQL version: {db_version[0]}")
except Exception as e:
    print("\n❌ Failure! An error occurred.")
    print(f"Error details: {e}")
