import sqlite3
db_path = "C:/new project/New folder/backend_fastapi/factory_brain_fastapi.db"
conn = sqlite3.connect(db_path)
cursor = conn.cursor()
try:
    cursor.execute("SELECT c.machine_id, c.cycle_id, c.timestamp, p.scrap_probability FROM cycles c JOIN predictions p ON c.id = p.cycle_id LIMIT 10")
    for row in cursor.fetchall():
        print(row)
except Exception as e:
    print(e)
finally:
    conn.close()
