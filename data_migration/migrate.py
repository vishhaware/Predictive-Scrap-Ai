import sqlite3
import psycopg2
import json
import os
from datetime import datetime

# Configuration
SQLITE_DB = r"c:\new project\New folder\backend\factory_brain.db"
POSTGRES_URL = "postgresql://postgres:password@localhost:5432/factory_brain"

def migrate():
    print("🚀 Starting Data Migration: SQLite -> TimescaleDB")
    
    # 1. Connect to SQLite
    if not os.path.exists(SQLITE_DB):
        print(f"❌ SQLite file not found at {SQLITE_DB}")
        return
        
    s_conn = sqlite3.connect(SQLITE_DB)
    s_cur = s_conn.cursor()
    
    # 2. Connect to Postgres
    try:
        p_conn = psycopg2.connect(POSTGRES_URL)
        p_cur = p_conn.cursor()
    except Exception as e:
        print(f"❌ Failed to connect to Postgres: {e}")
        print("💡 Make sure Docker is running with TimescaleDB!")
        return

    # --- Migrate machine_stats ---
    print("📊 Migrating machine_stats...")
    s_cur.execute("SELECT machine_id, baselines, last_loaded_timestamp FROM machine_stats")
    rows = s_cur.fetchall()
    for row in rows:
        p_cur.execute(
            "INSERT INTO machine_stats (machine_id, baselines, last_loaded_timestamp) VALUES (%s, %s, %s) ON CONFLICT (machine_id) DO UPDATE SET baselines = EXCLUDED.baselines, last_loaded_timestamp = EXCLUDED.last_loaded_timestamp",
            row
        )
    p_conn.commit()

    # --- Migrate cycles & predictions ---
    print("⚙️ Migrating cycles & predictions (this may take a while)...")
    s_cur.execute("""
        SELECT c.machine_id, c.cycle_id, c.timestamp, c.data, 
               p.scrap_probability, p.confidence, p.risk_level, p.primary_defect_risk, p.attributions
        FROM cycles c
        LEFT JOIN predictions p ON c.id = p.cycle_id
    """)
    
    batch_size = 1000
    while True:
        rows = s_cur.fetchmany(batch_size)
        if not rows:
            break
            
        for row in rows:
            m_id, c_id, ts, data, s_prob, conf, r_level, d_risk, attr = row
            
            # Convert ISO timestamp to datetime if possible
            try:
                dt = datetime.fromisoformat(ts.replace('Z', '+00:00'))
            except:
                dt = datetime.now()

            p_cur.execute(
                "INSERT INTO cycles (machine_id, cycle_id, timestamp, data) VALUES (%s, %s, %s, %s) RETURNING id",
                (m_id, c_id, dt, data)
            )
            new_id = p_cur.fetchone()[0]
            
            p_cur.execute(
                "INSERT INTO predictions (cycle_id, scrap_probability, confidence, risk_level, primary_defect_risk, attributions) VALUES (%s, %s, %s, %s, %s, %s)",
                (new_id, s_prob, conf, r_level, d_risk, attr)
            )
            
        p_conn.commit()
        print(f"  ✅ Batched 1000 rows...")

    print("🎉 Migration Complete!")
    s_conn.close()
    p_conn.close()

if __name__ == "__main__":
    migrate()
