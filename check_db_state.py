import sqlite3
import os

db_path = "backend_fastapi/factory_brain_fastapi.db"
if not os.path.exists(db_path):
    print(f"DB not found at {db_path}")
else:
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    try:
        cur.execute("SELECT machine_id, count(*) FROM cycles GROUP BY machine_id")
        rows = cur.fetchall()
        print("Cycles count by machine:")
        for row in rows:
            print(f"  {row[0]}: {row[1]}")
        
        cur.execute("SELECT machine_id, last_loaded_timestamp FROM machine_stats")
        rows = cur.fetchall()
        print("\nIngestion stats:")
        for row in rows:
            print(f"  {row[0]}: {row[1]}")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        conn.close()
