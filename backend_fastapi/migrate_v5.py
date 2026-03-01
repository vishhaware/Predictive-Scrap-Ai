import sqlite3
import os

db_path = os.path.join(os.path.dirname(__file__), "factory_brain_fastapi.db")

def migrate_v5():
    print(f"🛠️ Migrating to DB Schema v5 at {db_path}...")
    if not os.path.exists(db_path): return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        cursor.execute("PRAGMA table_info(machine_stats)")
        columns = [row[1] for row in cursor.fetchall()]
        
        if "maintenance_urgency" not in columns:
            print("➕ Adding column maintenance_urgency...")
            cursor.execute("ALTER TABLE machine_stats ADD COLUMN maintenance_urgency VARCHAR DEFAULT 'LOW'")
        
        conn.commit()
    finally:
        conn.close()

if __name__ == "__main__":
    migrate_v5()
