import sqlite3
db_path = "C:/new project/New folder/backend_fastapi/factory_brain_fastapi.db"
conn = sqlite3.connect(db_path)
try:
    conn.execute("DELETE FROM predictions")
    conn.execute("DELETE FROM cycles")
    conn.execute("UPDATE machine_stats SET last_loaded_timestamp = NULL, last_status = 'ok', last_oee = 0, last_cycles_count = 0")
    conn.commit()
    print("Database cleared for fresh ingestion.")
except Exception as e:
    print(f"Error: {e}")
finally:
    conn.close()
