import sqlite3
import os

DB_PATH = os.path.join("data", "data.db")

def ensure_columns():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # отримуємо список колонок
    cur.execute("PRAGMA table_info(tasks)")
    cols = [c[1] for c in cur.fetchall()]

    if "due_date" not in cols:
        print("[+] Adding column: due_date")
        cur.execute("ALTER TABLE tasks ADD COLUMN due_date TEXT")

    if "priority" not in cols:
        print("[+] Adding column: priority")
        cur.execute("ALTER TABLE tasks ADD COLUMN priority TEXT DEFAULT 'середній'")

    conn.commit()
    conn.close()
    print("[✓] Database structure fixed!")

if __name__ == "__main__":
    ensure_columns()
