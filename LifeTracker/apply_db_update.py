import sqlite3

DB_PATH = "data/data.db"

def column_exists(cursor, table, column):
    cursor.execute(f"PRAGMA table_info({table});")
    return column in [row[1] for row in cursor.fetchall()]

def apply_update():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    # Tasks table - додаємо тільки відсутні колонки
    if not column_exists(cur, "tasks", "due_date"):
        cur.execute("ALTER TABLE tasks ADD COLUMN due_date TEXT")
    if not column_exists(cur, "tasks", "priority"):
        cur.execute("ALTER TABLE tasks ADD COLUMN priority TEXT DEFAULT 'Low'")
    if not column_exists(cur, "tasks", "category_id"):
        cur.execute("ALTER TABLE tasks ADD COLUMN category_id INTEGER")
    if not column_exists(cur, "tasks", "completed"):
        cur.execute("ALTER TABLE tasks ADD COLUMN completed INTEGER DEFAULT 0")

    # Створюємо нові таблиці
    cur.execute(        "CREATE TABLE IF NOT EXISTS categories (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"    )
    cur.execute(        "CREATE TABLE IF NOT EXISTS tags (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL)"    )
    cur.execute(        "CREATE TABLE IF NOT EXISTS notes (id INTEGER PRIMARY KEY AUTOINCREMENT, text TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP)"    )
    cur.execute(        "CREATE TABLE IF NOT EXISTS attachments (id INTEGER PRIMARY KEY AUTOINCREMENT, note_id INTEGER, file_path TEXT, FOREIGN KEY(note_id) REFERENCES notes(id))"    )

    conn.commit()
    conn.close()
    print("✅ Database update finished successfully!")

if __name__ == "__main__":
    apply_update()
