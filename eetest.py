import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()  # carica .env

DATABASE_URL = os.getenv("DATABASE_URL")

try:
    conn = psycopg2.connect(DATABASE_URL, connect_timeout=10)
    cur = conn.cursor()
    cur.execute("SELECT 1;")
    print("✅ Connection successful:", cur.fetchone())
    conn.close()
except Exception as e:
    print("❌ Connection failed:", e)