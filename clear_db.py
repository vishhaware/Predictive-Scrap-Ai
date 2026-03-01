import sqlite3
import os

db_path = "backend_fastapi/factory_brain_fastapi.db"
if os.path.exists(db_path):
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    print("Clearing cycles and predictions...")
    cursor.execute("DELETE FROM predictions")
    cursor.execute("DELETE FROM cycles")
    cursor.execute("UPDATE machine_stats SET last_loaded_timestamp = NULL")
    
    conn.commit()
    conn.close()
    print("Database cleared. Ready for fresh ingestion.")
else:
    print(f"Database not found at {db_path}")
