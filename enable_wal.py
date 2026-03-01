import sqlite3
db_path = "C:/new project/New folder/backend_fastapi/factory_brain_fastapi.db"
conn = sqlite3.connect(db_path)
conn.execute("PRAGMA journal_mode=WAL;")
conn.commit()
conn.close()
print("WAL mode enabled")
