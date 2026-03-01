import sqlite3, json
db_path = "C:/new project/New folder/backend_fastapi/factory_brain_fastapi.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
try:
    cursor.execute("SELECT machine_id, last_status, last_oee, last_cycles_count, maintenance_urgency FROM machine_stats")
    for row in cursor.fetchall():
        print(row)
except Exception as e:
    print(e)
finally:
    conn.close()
