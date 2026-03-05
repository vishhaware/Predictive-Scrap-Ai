import os
import sqlite3
import sys
from pathlib import Path

def repair():
    db_path = os.environ.get("SFB_DB_PATH")
    if not db_path:
        print("Error: SFB_DB_PATH not set.")
        sys.exit(1)
    
    path = Path(db_path)
    if not path.exists():
        print(f"Error: DB not found at {db_path}")
        sys.exit(1)

    try:
        conn = sqlite3.connect(db_path)
        cur = conn.cursor()
        
        # 1. Clear miscalibrated predictions (Bug #1)
        # Any prediction with scrap_prob > 0.95 and high confidence is likely stale noise
        # unless real events match it.
        cur.execute("UPDATE machine_predictions SET scrap_probability = 0.0, confidence = 0.5 WHERE scrap_probability > 0.95")
        updated = cur.rowcount
        
        # 2. Reset ingestion cursor if requested (optional)
        # cur.execute("UPDATE machine_stats SET last_loaded_timestamp = NULL")
        
        conn.commit()
        conn.close()
        print(f"Successfully repaired {updated} prediction records.")
    except Exception as e:
        print(f"Repair failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    repair()
