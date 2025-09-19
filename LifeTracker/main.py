# -*- coding: utf-8 -*-
import os
import sys
import csv
import shutil
import hashlib
import sqlite3
import uuid
from datetime import datetime, timedelta, date

from PyQt5 import QtWidgets, QtGui, QtCore
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure

APP_NAME = "LifeTracker"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
ATTACH_DIR = os.path.join(DATA_DIR, "attachments")
os.makedirs(DATA_DIR, exist_ok=True)
os.makedirs(ATTACH_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "data.db")
STYLE_PATH = os.path.join(APP_DIR, "style.qss")
EUR = "€"

IMG_EXT = {".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp"}
TXT_EXT = {".txt", ".md", ".csv", ".json", ".log", ".ini", ".yaml", ".yml"}

# ---- Timezone (Europe/Berlin) ----
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
    BERLIN_TZ = ZoneInfo("Europe/Berlin")
except Exception:
    BERLIN_TZ = None  # fallback later if needed

def now_berlin() -> datetime:
    if BERLIN_TZ:
        return datetime.now(BERLIN_TZ)
    # fallback: naive local time
    return datetime.now()

def as_berlin_local(dt: datetime) -> datetime:
    """Assume naive dt is Berlin local; make it TZ-aware."""
    if dt.tzinfo is None and BERLIN_TZ:
        return dt.replace(tzinfo=BERLIN_TZ)
    return dt

# ---------- DB Layer ----------
class DB:
    def __init__(self, path: str):
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.migrate()

    def _columns(self, table: str):
        cur = self.conn.execute(f"PRAGMA table_info({table})")
        return {row[1] for row in cur.fetchall()}

    def migrate(self):
        c = self.conn.cursor()

        # Expenses
        c.execute("""CREATE TABLE IF NOT EXISTS expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dt TEXT NOT NULL,
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            note TEXT,
            created_at TEXT NOT NULL
        )""")

        # Events
        c.execute("""CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            start_ts TEXT NOT NULL,
            end_ts TEXT,
            location TEXT,
            description TEXT,
            remind_minutes INTEGER,
            status TEXT DEFAULT 'planned',
            created_at TEXT NOT NULL
        )""")
        if "recur" not in self._columns("events"):
            c.execute("ALTER TABLE events ADD COLUMN recur TEXT DEFAULT 'none'")

        # Tasks
        c.execute("""CREATE TABLE IF NOT EXISTS tasks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            due_dt TEXT,
            category TEXT,
            priority INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )""")
        cols = self._columns("tasks")
        if "status" not in cols:
            c.execute("ALTER TABLE tasks ADD COLUMN status TEXT DEFAULT 'todo'")
        if "done" in cols:
            c.execute("UPDATE tasks SET status='done' WHERE done=1")

        # Notes
        c.execute("""CREATE TABLE IF NOT EXISTS notes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            content TEXT NOT NULL,
            pinned INTEGER DEFAULT 0,
            created_at TEXT NOT NULL
        )""")

        # Settings
        c.execute("""CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )""")
        if not c.execute("SELECT 1 FROM settings WHERE key='theme'").fetchone():
            c.execute("INSERT INTO settings(key,value) VALUES('theme','dark')")

        # Notifications log
        c.execute("""CREATE TABLE IF NOT EXISTS notifications_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id INTEGER NOT NULL,
            fired_at TEXT NOT NULL
        )""")

        # Categories
        c.execute("""CREATE TABLE IF NOT EXISTS categories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            color TEXT
        )""")
        if c.execute("SELECT COUNT(*) FROM categories").fetchone()[0] == 0:
            defaults = [
                ("Food", "#ef4444"),
                ("Transport", "#22d3ee"),
                ("Entertainment", "#f59e0b"),
                ("Education", "#7c3aed"),
                ("Health", "#22c55e"),
                ("Clothes", "#06b6d4"),
                ("Other", "#a78bfa"),
            ]
            c.executemany("INSERT OR IGNORE INTO categories(name,color) VALUES(?,?)", defaults)

        # Budgets
        c.execute("""CREATE TABLE IF NOT EXISTS budgets (
            category TEXT PRIMARY KEY,
            monthly_limit REAL NOT NULL
        )""")

        # Recurring expenses
        c.execute("""CREATE TABLE IF NOT EXISTS recurring_expenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            start_dt TEXT NOT NULL,
            period TEXT NOT NULL,               -- daily|weekly|monthly
            category TEXT NOT NULL,
            amount REAL NOT NULL,
            note TEXT,
            last_posted TEXT
        )""")

        # Attachments
        c.execute("""CREATE TABLE IF NOT EXISTS attachments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            entity TEXT NOT NULL,           -- 'expense','event','task','note'
            entity_id INTEGER NOT NULL,
            kind TEXT NOT NULL,             -- 'file' | 'link'
            original_name TEXT,
            stored_path TEXT,               -- filename under data/attachments
            url TEXT,
            added_at TEXT NOT NULL
        )""")
        c.execute("CREATE INDEX IF NOT EXISTS idx_attach_entity ON attachments(entity, entity_id)")

        self.conn.commit()

    def execute(self, q, args=()):
        cur = self.conn.cursor()
        cur.execute(q, args)
        self.conn.commit()
        return cur

db = DB(DB_PATH)

# ---------- Utils ----------
def format_money(amount: float) -> str:
    s = f"{amount:,.2f}".replace(",", " ").replace(".", ",")
    return f"{s} {EUR}"

def today_str() -> str:
    return date.today().isoformat()

def get_setting(key: str, default: str = "") -> str:
    cur = db.execute("SELECT value FROM settings WHERE key=?", (key,))
    row = cur.fetchone()
    return row["value"] if row else default

def set_setting(key: str, value: str):
    db.execute(
        "INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )

def sha256(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()

def unique_copy_to_attachments(src_path: str) -> str:
    """Copy file into ATTACH_DIR with unique name; return stored filename."""
    ext = os.path.splitext(src_path)[1].lower()
    name = f"{uuid.uuid4().hex}{ext}"
    dst = os.path.join(ATTACH_DIR, name)
    shutil.copy2(src_path, dst)
    return name

def delete_physical_file(stored_name: str):
    if not stored_name:
        return
    path = os.path.join(ATTACH_DIR, stored_name)
    try:
        if os.path.exists(path):
            os.remove(path)
    except Exception:
        pass

def open_path_or_url(path_or_url: str):
    QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(path_or_url) if os.path.exists(path_or_url)
                                   else QtCore.QUrl(path_or_url))

def delete_attachments_for(entity: str, ids):
    if not ids:
        return
    # remove physical files then rows
    q_marks = ",".join("?" * len(ids))
    rows = db.execute(f"SELECT * FROM attachments WHERE entity=? AND entity_id IN ({q_marks})",
                      (entity, *ids)).fetchall()
    for r in rows:
        if r["kind"] == "file" and r["stored_path"]:
            delete_physical_file(r["stored_path"])
    db.execute(f"DELETE FROM attachments WHERE entity=? AND entity_id IN ({q_marks})", (entity, *ids))

# ---------- Attachment Dialog ----------
class AttachmentsDialog(QtWidgets.QDialog):
    def __init__(self, entity: str, entity_id: int, parent=None, title_suffix=""):
        super().__init__(parent)
        self.entity = entity
        self.entity_id = entity_id
        self.setWindowTitle(f"Attachments — {entity}#{entity_id} {title_suffix}".strip())
        v = QtWidgets.QVBoxLayout(self)

        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Type", "Name / URL", "Added"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        v.addWidget(self.table, 1)

        btns = QtWidgets.QHBoxLayout()
        self.add_file = QtWidgets.QPushButton("Add File…"); self.add_file.setObjectName("Primary"); self.add_file.clicked.connect(self.on_add_file)
        self.add_link = QtWidgets.QPushButton("Add Link…"); self.add_link.clicked.connect(self.on_add_link)
        self.open_btn = QtWidgets.QPushButton("Open"); self.open_btn.clicked.connect(self.on_open)
        self.preview_btn = QtWidgets.QPushButton("Preview"); self.preview_btn.clicked.connect(self.on_preview)
        self.folder_btn = QtWidgets.QPushButton("Open Folder"); self.folder_btn.clicked.connect(self.on_open_folder)
        self.del_btn = QtWidgets.QPushButton("Delete"); self.del_btn.setObjectName("Danger"); self.del_btn.clicked.connect(self.on_delete)
        for w in [self.add_file, self.add_link, self.open_btn, self.preview_btn, self.folder_btn, self.del_btn]:
            btns.addWidget(w)
        btns.addStretch(1)
        v.addLayout(btns)

        self.reload()

    def reload(self):
        rows = db.execute("SELECT * FROM attachments WHERE entity=? AND entity_id=? ORDER BY id DESC",
                          (self.entity, self.entity_id)).fetchall()
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            t = QtWidgets.QTableWidgetItem("file" if row["kind"] == "file" else "link")
            name = row["original_name"] if row["kind"] == "file" else (row["url"] or "")
            n = QtWidgets.QTableWidgetItem(name)
            a = QtWidgets.QTableWidgetItem(row["added_at"])
            self.table.setItem(r, 0, t); self.table.setItem(r, 1, n); self.table.setItem(r, 2, a)
            for c in range(3):
                self.table.item(r, c).setData(QtCore.Qt.UserRole, row["id"])

    def _selected_id(self):
        it = self.table.currentItem()
        if not it: return None
        return it.data(QtCore.Qt.UserRole)

    def on_add_file(self):
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Add file(s)")
        if not paths: return
        for p in paths:
            try:
                stored = unique_copy_to_attachments(p)
                db.execute("""INSERT INTO attachments(entity,entity_id,kind,original_name,stored_path,url,added_at)
                              VALUES(?,?,?,?,?,?,?)""",
                           (self.entity, self.entity_id, "file", os.path.basename(p), stored, None,
                            now_berlin().replace(tzinfo=None).isoformat(timespec="seconds")))
            except Exception as e:
                QtWidgets.QMessageBox.warning(self, "Copy error", f"{p}\n{e}")
        self.reload()

    def on_add_link(self):
        url, ok = QtWidgets.QInputDialog.getText(self, "Add link", "URL (https://…):")
        if not ok: return
        url = url.strip()
        if not url: return
        if not (url.startswith("http://") or url.startswith("https://")):
            QtWidgets.QMessageBox.warning(self, "URL", "Link must start with http:// or https://")
            return
        db.execute("""INSERT INTO attachments(entity,entity_id,kind,original_name,stored_path,url,added_at)
                      VALUES(?,?,?,?,?,?,?)""",
                   (self.entity, self.entity_id, "link", None, None, url,
                    now_berlin().replace(tzinfo=None).isoformat(timespec="seconds")))
        self.reload()

    def on_open(self):
        aid = self._selected_id()
        if not aid: return
        r = db.execute("SELECT * FROM attachments WHERE id=?", (aid,)).fetchone()
        if not r: return
        if r["kind"] == "file":
            path = os.path.join(ATTACH_DIR, r["stored_path"])
            open_path_or_url(path)
        else:
            open_path_or_url(r["url"])

    def on_open_folder(self):
        aid = self._selected_id()
        if not aid: return
        r = db.execute("SELECT * FROM attachments WHERE id=?", (aid,)).fetchone()
        if not r or r["kind"] != "file": return
        path = os.path.join(ATTACH_DIR, r["stored_path"])
        folder = os.path.dirname(path)
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(folder))

    def on_preview(self):
        aid = self._selected_id()
        if not aid: return
        r = db.execute("SELECT * FROM attachments WHERE id=?", (aid,)).fetchone()
        if not r: return
        if r["kind"] == "link":
            open_path_or_url(r["url"])
            return
        path = os.path.join(ATTACH_DIR, r["stored_path"])
        ext = os.path.splitext(path)[1].lower()
        if ext in IMG_EXT:
            self._preview_image(path)
        elif ext in TXT_EXT:
            self._preview_text(path)
        else:
            QtWidgets.QMessageBox.information(self, "Preview", "No inline preview for this file type. Use Open.")

    def _preview_image(self, path: str):
        dlg = QtWidgets.QDialog(self); dlg.setWindowTitle(os.path.basename(path)); dlg.resize(900, 700)
        lay = QtWidgets.QVBoxLayout(dlg)
        scroll = QtWidgets.QScrollArea(); scroll.setWidgetResizable(True)
        lbl = QtWidgets.QLabel(); lbl.setAlignment(QtCore.Qt.AlignCenter)
        pix = QtGui.QPixmap(path)
        lbl.setPixmap(pix)
        scroll.setWidget(lbl)
        lay.addWidget(scroll)
        dlg.exec_()

    def _preview_text(self, path: str):
        dlg = QtWidgets.QDialog(self); dlg.setWindowTitle(os.path.basename(path)); dlg.resize(900, 700)
        lay = QtWidgets.QVBoxLayout(dlg)
        txt = QtWidgets.QPlainTextEdit(); txt.setReadOnly(True)
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                txt.setPlainText(f.read())
        except Exception as e:
            txt.setPlainText(str(e))
        lay.addWidget(txt)
        dlg.exec_()

    def on_delete(self):
        aid = self._selected_id()
        if not aid: return
        if QtWidgets.QMessageBox.question(self, "Confirm", "Delete attachment?") != QtWidgets.QMessageBox.Yes:
            return
        r = db.execute("SELECT * FROM attachments WHERE id=?", (aid,)).fetchone()
        if r and r["kind"] == "file" and r["stored_path"]:
            delete_physical_file(r["stored_path"])
        db.execute("DELETE FROM attachments WHERE id=?", (aid,))
        self.reload()

# ---------- UI helpers ----------
def H1(text: str) -> QtWidgets.QLabel:
    lab = QtWidgets.QLabel(text); lab.setObjectName("H1"); return lab
def H2(text: str) -> QtWidgets.QLabel:
    lab = QtWidgets.QLabel(text); lab.setObjectName("H2"); return lab
def Muted(text: str) -> QtWidgets.QLabel:
    lab = QtWidgets.QLabel(text); lab.setObjectName("Muted"); return lab
def CardLayout(widget: QtWidgets.QWidget) -> QtWidgets.QWidget:
    widget.setObjectName("Card"); return widget
def Separator() -> QtWidgets.QFrame:
    f = QtWidgets.QFrame(); f.setObjectName("Separator"); f.setFrameShape(QtWidgets.QFrame.HLine); return f

# ---------- Dashboard ----------
class Dashboard(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        root = QtWidgets.QVBoxLayout(self)
        head = QtWidgets.QHBoxLayout()
        head.addWidget(H1("Dashboard")); head.addStretch(1)
        root.addLayout(head); root.addWidget(Separator())

        row = QtWidgets.QHBoxLayout()

        self.card_today = CardLayout(QtWidgets.QFrame())
        v1 = QtWidgets.QVBoxLayout(self.card_today)
        v1.addWidget(H2("Today spending"))
        self.today_value = Muted("0,00 €"); self.today_value.setStyleSheet("font-size: 18pt;")
        v1.addWidget(self.today_value); v1.addWidget(Muted("Sum of expenses for today"))

        self.card_month = CardLayout(QtWidgets.QFrame())
        v2 = QtWidgets.QVBoxLayout(self.card_month)
        v2.addWidget(H2("This month"))
        self.month_value = Muted("0,00 €"); self.month_value.setStyleSheet("font-size: 18pt;")
        v2.addWidget(self.month_value); v2.addWidget(Muted("All expenses in current month"))

        self.card_budget = CardLayout(QtWidgets.QFrame())
        v3 = QtWidgets.QVBoxLayout(self.card_budget)
        v3.addWidget(H2("Budgets status"))
        self.budget_value = Muted("—"); self.budget_value.setStyleSheet("font-size: 18pt;")
        v3.addWidget(self.budget_value); v3.addWidget(Muted("Over/under monthly limits"))

        row.addWidget(self.card_today, 1); row.addWidget(self.card_month, 1); row.addWidget(self.card_budget, 1)
        root.addLayout(row); root.addSpacing(14); root.addWidget(Separator())

        tail = QtWidgets.QHBoxLayout()

        self.upcoming = CardLayout(QtWidgets.QFrame())
        v4 = QtWidgets.QVBoxLayout(self.upcoming)
        v4.addWidget(H2("Upcoming events (next 7 days)"))
        self.upcoming_list = QtWidgets.QListWidget()
        v4.addWidget(self.upcoming_list, 1)

        self.overdue = CardLayout(QtWidgets.QFrame())
        v5 = QtWidgets.QVBoxLayout(self.overdue)
        v5.addWidget(H2("Overdue tasks"))
        self.overdue_list = QtWidgets.QListWidget()
        v5.addWidget(self.overdue_list, 1)

        tail.addWidget(self.upcoming, 1); tail.addWidget(self.overdue, 1)
        root.addLayout(tail)

        self.reload()

    def reload(self):
        cur = db.execute("SELECT COALESCE(SUM(amount),0) s FROM expenses WHERE dt=?", (today_str(),))
        self.today_value.setText(format_money(cur.fetchone()["s"]))

        ym = date.today().strftime("%Y-%m")
        cur = db.execute("SELECT COALESCE(SUM(amount),0) s FROM expenses WHERE substr(dt,1,7)=?", (ym,))
        self.month_value.setText(format_money(cur.fetchone()["s"]))

        cur = db.execute("SELECT category, monthly_limit FROM budgets")
        budgets = cur.fetchall()
        if budgets:
            lines = []
            for b in budgets:
                cur2 = db.execute(
                    "SELECT COALESCE(SUM(amount),0) s FROM expenses WHERE substr(dt,1,7)=? AND category=?",
                    (ym, b["category"]),
                )
                spent = cur2.fetchone()["s"]
                diff = b["monthly_limit"] - spent
                emoji = "✅" if diff >= 0 else "⚠️"
                lines.append(f"{emoji} {b['category']}: {format_money(spent)} / {format_money(b['monthly_limit'])}")
            self.budget_value.setText("\n".join(lines))
        else:
            self.budget_value.setText("No budgets configured")

        self.upcoming_list.clear()
        now = now_berlin(); until = now + timedelta(days=7)
        cur = db.execute(
            "SELECT * FROM events WHERE start_ts BETWEEN ? AND ? ORDER BY start_ts ASC",
            (now.replace(tzinfo=None).isoformat(timespec="seconds"), until.replace(tzinfo=None).isoformat(timespec="seconds")),
        )
        for r in cur.fetchall():
            when = as_berlin_local(datetime.fromisoformat(r["start_ts"])).strftime("%d.%m %H:%M")
            self.upcoming_list.addItem(f"{when} — {r['title']}")

        self.overdue_list.clear()
        cur = db.execute(
            "SELECT title, due_dt FROM tasks WHERE status!='done' AND due_dt IS NOT NULL AND due_dt < ? ORDER BY due_dt ASC",
            (today_str(),),
        )
        for r in cur.fetchall():
            self.overdue_list.addItem(f"{r['due_dt']} — {r['title']}")

# ---------- Stats (charts) ----------
class StatsPage(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        v = QtWidgets.QVBoxLayout(self)
        hdr = QtWidgets.QHBoxLayout()
        hdr.addWidget(H1("Statistics")); hdr.addStretch(1)

        self.month_edit = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        self.month_edit.setDisplayFormat("yyyy-MM")
        self.month_edit.setCalendarPopup(True)
        self.month_edit.setDate(QtCore.QDate.currentDate())
        self.refresh_btn = QtWidgets.QPushButton("Refresh"); self.refresh_btn.setObjectName("Primary")
        self.refresh_btn.clicked.connect(self.reload)

        hdr.addWidget(self.month_edit); hdr.addWidget(self.refresh_btn)
        v.addLayout(hdr); v.addWidget(Separator())

        # summary
        self.summary = QtWidgets.QLabel(""); self.summary.setObjectName("Badge")
        v.addWidget(self.summary)

        # charts
        self.fig = Figure(figsize=(5, 4), dpi=100)
        self.canvas = FigureCanvas(self.fig)
        v.addWidget(self.canvas, 1)

        self.reload()

    def reload(self):
        y = self.month_edit.date().year(); m = self.month_edit.date().month()
        ym = f"{y:04d}-{m:02d}"

        # summary
        cur = db.execute("SELECT COALESCE(SUM(amount),0) s FROM expenses WHERE substr(dt,1,7)=?", (ym,))
        s = cur.fetchone()["s"]
        self.summary.setText(f"Total {ym}: {format_money(s)}")

        # charts: clear figure
        self.fig.clear()

        # 1) Bar by category
        ax1 = self.fig.add_subplot(211)
        cur = db.execute("""
            SELECT category, SUM(amount) s FROM expenses
            WHERE substr(dt,1,7)=?
            GROUP BY category ORDER BY s DESC
        """, (ym,))
        data = cur.fetchall()
        cats = [r["category"] for r in data]
        vals = [r["s"] for r in data]
        ax1.bar(cats, vals)
        ax1.set_title("By category")
        ax1.tick_params(axis='x', rotation=30, labelsize=8)

        # 2) Line by day
        ax2 = self.fig.add_subplot(212)
        cur = db.execute("""
            SELECT dt as d, SUM(amount) s FROM expenses
            WHERE substr(dt,1,7)=?
            GROUP BY dt ORDER BY dt
        """, (ym,))
        rows = cur.fetchall()
        days = [int(r["d"][-2:]) for r in rows]
        sums = [r["s"] for r in rows]
        ax2.plot(days, sums, marker='o')
        ax2.set_title("Daily spending")
        ax2.set_xlabel("Day")
        ax2.set_ylabel("€")

        self.fig.tight_layout()
        self.canvas.draw_idle()

# ---------- Recurring expenses helpers ----------
def _advance_period(d: date, period: str) -> date:
    if period == "daily":   return d + timedelta(days=1)
    if period == "weekly":  return d + timedelta(weeks=1)
    if period == "monthly":
        m = d.month + 1; y = d.year + (m - 1) // 12; m = 1 + (m - 1) % 12
        import calendar
        day = min(d.day, calendar.monthrange(y, m)[1])
        return date(y, m, day)
    return d

def process_recurring_expenses():
    rows = db.execute("SELECT * FROM recurring_expenses").fetchall()
    today = date.today()
    for r in rows:
        last = datetime.strptime(r["last_posted"], "%Y-%m-%d").date() if r["last_posted"] else None
        nxt = last or datetime.strptime(r["start_dt"], "%Y-%m-%d").date()
        if last:
            nxt = _advance_period(nxt, r["period"])
        posted_any = False
        while nxt <= today:
            db.execute("""INSERT INTO expenses(dt, category, amount, note, created_at)
                          VALUES(?,?,?,?,?)""",
                       (nxt.isoformat(), r["category"], float(r["amount"]), (r["note"] or "") + " (recurring)", now_berlin().replace(tzinfo=None).isoformat(timespec="seconds")))
            posted_any = True
            nxt = _advance_period(nxt, r["period"])
        if posted_any:
            db.execute("UPDATE recurring_expenses SET last_posted=? WHERE id=?", (today.isoformat(), r["id"]))

# ---------- Expenses Page (filters, import/export, recurring) ----------
class RecurringDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Recurring expenses")
        v = QtWidgets.QVBoxLayout(self)

        self.table = QtWidgets.QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Start", "Period", "Category", "Amount", "Note", "Last posted"])
        self.table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.table, 1)

        btns = QtWidgets.QHBoxLayout()
        add = QtWidgets.QPushButton("Add"); add.setObjectName("Primary"); add.clicked.connect(self.add_rec)
        edit = QtWidgets.QPushButton("Edit"); edit.clicked.connect(self.edit_rec)
        delete = QtWidgets.QPushButton("Delete"); delete.setObjectName("Danger"); delete.clicked.connect(self.del_rec)
        btns.addWidget(add); btns.addWidget(edit); btns.addWidget(delete); btns.addStretch(1)
        v.addLayout(btns)

        self.reload()

    def reload(self):
        cur = db.execute("SELECT * FROM recurring_expenses ORDER BY id DESC")
        rows = cur.fetchall()
        self.table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(row["start_dt"]))
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(row["period"]))
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(row["category"]))
            self.table.setItem(r, 3, QtWidgets.QTableWidgetItem(format_money(row["amount"])))
            self.table.setItem(r, 4, QtWidgets.QTableWidgetItem(row["note"] or ""))
            self.table.setItem(r, 5, QtWidgets.QTableWidgetItem(row["last_posted"] or "—"))
            for c in range(6):
                self.table.item(r, c).setData(QtCore.Qt.UserRole, row["id"])

    def _selected_id(self):
        it = self.table.currentItem()
        if not it: return None
        return it.data(QtCore.Qt.UserRole)

    def add_rec(self):
        self._open_editor()

    def edit_rec(self):
        rid = self._selected_id()
        if not rid: return
        self._open_editor(rid)

    def del_rec(self):
        rid = self._selected_id()
        if not rid: return
        if QtWidgets.QMessageBox.question(self, "Confirm", "Delete recurring entry?") == QtWidgets.QMessageBox.Yes:
            db.execute("DELETE FROM recurring_expenses WHERE id=?", (rid,))
            self.reload()

    def _open_editor(self, rid=None):
        dlg = QtWidgets.QDialog(self); dlg.setWindowTitle("Edit recurring")
        form = QtWidgets.QFormLayout(dlg)
        start = QtWidgets.QDateEdit(QtCore.QDate.currentDate()); start.setCalendarPopup(True)
        period = QtWidgets.QComboBox(); period.addItems(["daily", "weekly", "monthly"])
        cat = QtWidgets.QLineEdit()
        amt = QtWidgets.QDoubleSpinBox(); amt.setMaximum(1_000_000); amt.setDecimals(2); amt.setSuffix(" " + EUR)
        note = QtWidgets.QLineEdit()
        if rid:
            row = db.execute("SELECT * FROM recurring_expenses WHERE id=?", (rid,)).fetchone()
            start.setDate(QtCore.QDate.fromString(row["start_dt"], "yyyy-MM-dd"))
            period.setCurrentText(row["period"])
            cat.setText(row["category"]); amt.setValue(float(row["amount"]))
            note.setText(row["note"] or "")
        form.addRow("Start date", start); form.addRow("Period", period)
        form.addRow("Category", cat); form.addRow("Amount", amt); form.addRow("Note", note)
        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        form.addRow(btns)
        btns.accepted.connect(dlg.accept); btns.rejected.connect(dlg.reject)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            vals = (start.date().toString("yyyy-MM-dd"), period.currentText(), cat.text().strip(),
                    float(amt.value()), note.text().strip())
            if rid:
                db.execute("""UPDATE recurring_expenses
                              SET start_dt=?, period=?, category=?, amount=?, note=?
                              WHERE id=?""", (*vals, rid))
            else:
                db.execute("""INSERT INTO recurring_expenses(start_dt,period,category,amount,note,last_posted)
                              VALUES(?,?,?,?,?,NULL)""", vals)
            self.reload()

class ExpensesPage(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        root = QtWidgets.QVBoxLayout(self)

        # Header
        top = QtWidgets.QHBoxLayout()
        top.addWidget(H1("Expenses (€)")); top.addStretch(1)
        self.month_label = Muted(""); top.addWidget(self.month_label)
        root.addLayout(top); root.addWidget(Separator())

        # Filters
        filt = QtWidgets.QHBoxLayout()
        self.from_dt = QtWidgets.QDateEdit(QtCore.QDate.currentDate().addMonths(-1)); self.from_dt.setCalendarPopup(True)
        self.to_dt = QtWidgets.QDateEdit(QtCore.QDate.currentDate()); self.to_dt.setCalendarPopup(True)
        self.cat_f = QtWidgets.QComboBox(); self.cat_f.setEditable(True); self.cat_f.addItem("All"); self.reload_categories_combo(self.cat_f)
        self.search = QtWidgets.QLineEdit(); self.search.setPlaceholderText("Search note...")
        self.apply_btn = QtWidgets.QPushButton("Filter"); self.apply_btn.clicked.connect(self.reload_table)
        self.reset_btn = QtWidgets.QPushButton("Reset"); self.reset_btn.clicked.connect(self.reset_filters)
        for w in [QtWidgets.QLabel("From"), self.from_dt, QtWidgets.QLabel("To"), self.to_dt,
                  QtWidgets.QLabel("Category"), self.cat_f, self.search, self.apply_btn, self.reset_btn]:
            filt.addWidget(w)
        filt_card = CardLayout(QtWidgets.QFrame()); filt_card.setLayout(filt); root.addWidget(filt_card)

        # Add form
        form = QtWidgets.QHBoxLayout()
        self.date_edit = QtWidgets.QDateEdit(QtCore.QDate.currentDate()); self.date_edit.setCalendarPopup(True)
        self.category = QtWidgets.QComboBox(); self.category.setEditable(True); self.reload_categories_combo(self.category)
        self.amount = QtWidgets.QDoubleSpinBox(); self.amount.setSuffix(" " + EUR); self.amount.setMaximum(1_000_000); self.amount.setDecimals(2); self.amount.setSingleStep(1.0)
        self.note = QtWidgets.QLineEdit(); self.note.setPlaceholderText("Description (optional)")
        self.add_btn = QtWidgets.QPushButton("Add expense"); self.add_btn.setObjectName("Primary"); self.add_btn.clicked.connect(self.add_expense)
        self.add_cat_btn = QtWidgets.QPushButton("➕ Category"); self.add_cat_btn.clicked.connect(self.add_category)
        self.rec_btn = QtWidgets.QPushButton("Recurring…"); self.rec_btn.clicked.connect(self.open_recurring)
        for w in [self.date_edit, self.category, self.amount, self.note, self.add_btn, self.add_cat_btn, self.rec_btn]:
            form.addWidget(w)
        form_card = CardLayout(QtWidgets.QFrame()); form_card.setLayout(form); root.addWidget(form_card)

        # Table
        self.table = QtWidgets.QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Date", "Category", "Amount", "Note"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        root.addWidget(self.table, 1)

        # Footer actions
        foot = QtWidgets.QHBoxLayout()
        self.summary = QtWidgets.QLabel(""); self.summary.setObjectName("Badge"); foot.addWidget(self.summary)
        foot.addStretch(1)
        self.imp_btn = QtWidgets.QPushButton("Import CSV")
        self.exp_btn = QtWidgets.QPushButton("Export CSV (filtered)")
        self.attach_btn = QtWidgets.QPushButton("Attachments…")
        self.del_btn = QtWidgets.QPushButton("Delete selected"); self.del_btn.setObjectName("Danger")
        self.imp_btn.clicked.connect(self.import_csv); self.exp_btn.clicked.connect(self.export_csv)
        self.attach_btn.clicked.connect(self.open_attachments)
        self.del_btn.clicked.connect(self.delete_selected)
        for w in [self.imp_btn, self.exp_btn, self.attach_btn, self.del_btn]:
            foot.addWidget(w)
        root.addLayout(foot)

        self.reset_filters()  # also loads table

    # ----- helpers -----
    def reload_categories_combo(self, combo: QtWidgets.QComboBox):
        cats = [r["name"] for r in db.execute("SELECT name FROM categories ORDER BY name").fetchall()]
        keep = combo.count() and combo.itemText(0).lower() == "all"
        combo.clear()
        if keep: combo.addItem("All")
        combo.addItems(cats)

    def reset_filters(self):
        self.from_dt.setDate(QtCore.QDate.currentDate().addMonths(-1))
        self.to_dt.setDate(QtCore.QDate.currentDate())
        if self.cat_f.count(): self.cat_f.setCurrentIndex(0)
        self.search.clear()
        self.reload_table()

    def add_category(self):
        name, ok = QtWidgets.QInputDialog.getText(self, "New category", "Name:")
        if not ok or not name.strip(): return
        color, ok2 = QtWidgets.QInputDialog.getText(self, "New category", "Color (hex, optional):", text="#7c3aed")
        try:
            db.execute("INSERT INTO categories(name,color) VALUES(?,?)", (name.strip(), color.strip()))
            QtWidgets.QMessageBox.information(self, "OK", f"Category '{name}' added")
            self.reload_categories_combo(self.category)
            self.reload_categories_combo(self.cat_f)
        except Exception as e:
            QtWidgets.QMessageBox.warning(self, "Error", str(e))

    def open_recurring(self):
        RecurringDialog(self).exec_()

    # ----- core -----
    def add_expense(self):
        dt = self.date_edit.date().toPyDate().isoformat()
        cat = self.category.currentText().strip() or "Other"
        amt = float(self.amount.value())
        note = self.note.text().strip()
        if amt <= 0:
            QtWidgets.QMessageBox.warning(self, "Error", "Amount must be > 0")
            return
        db.execute("INSERT INTO expenses (dt, category, amount, note, created_at) VALUES (?,?,?,?,?)",
                   (dt, cat, amt, note, now_berlin().replace(tzinfo=None).isoformat(timespec="seconds")))
        self.note.clear(); self.amount.setValue(0.0); self.reload_table()

    def _apply_filters_query(self):
        q = "SELECT id, dt, category, amount, note FROM expenses WHERE 1=1"
        args = []
        if self.from_dt.date() <= self.to_dt.date():
            q += " AND dt BETWEEN ? AND ?"
            args += [self.from_dt.date().toPyDate().isoformat(), self.to_dt.date().toPyDate().isoformat()]
        if self.cat_f.currentText() and self.cat_f.currentText().lower() != "all":
            q += " AND category = ?"; args.append(self.cat_f.currentText())
        if self.search.text().strip():
            q += " AND note LIKE ?"; args.append("%" + self.search.text().strip() + "%")
        q += " ORDER BY dt DESC, id DESC LIMIT 1000"
        return q, tuple(args)

    def reload_table(self):
        q, a = self._apply_filters_query()
        rows = db.execute(q, a).fetchall()
        self.table.setRowCount(len(rows))
        colors = {r["name"]: (r["color"] or "#1b2029") for r in db.execute("SELECT name,color FROM categories").fetchall()}
        for r, row in enumerate(rows):
            it0 = QtWidgets.QTableWidgetItem(row["dt"])
            it1 = QtWidgets.QTableWidgetItem(row["category"])
            bg = QtGui.QColor(colors.get(row["category"], "#1b2029")); it1.setBackground(QtGui.QBrush(bg))
            it2 = QtWidgets.QTableWidgetItem(format_money(row["amount"]))
            it3 = QtWidgets.QTableWidgetItem(row["note"] or "")
            self.table.setItem(r, 0, it0); self.table.setItem(r, 1, it1); self.table.setItem(r, 2, it2); self.table.setItem(r, 3, it3)
            for c in range(4):
                self.table.item(r, c).setData(QtCore.Qt.UserRole, row["id"])

        ym = date.today().strftime("%Y-%m")
        s = db.execute("SELECT COALESCE(SUM(amount),0) s FROM expenses WHERE substr(dt,1,7)=?", (ym,)).fetchone()["s"]
        self.summary.setText(f"Total {ym}: {format_money(s)}"); self.month_label.setText(f"{ym}")

    def _selected_ids(self):
        ids = []
        for idx in self.table.selectionModel().selectedRows():
            it = self.table.item(idx.row(), 0)
            if it: ids.append(self.table.item(idx.row(), 0).data(QtCore.Qt.UserRole))
        return ids

    def _selected_one_id(self):
        ids = self._selected_ids()
        return ids[0] if ids else None

    def open_attachments(self):
        eid = self._selected_one_id()
        if not eid:
            QtWidgets.QMessageBox.information(self, "Attachments", "Select one expense row.")
            return
        dlg = AttachmentsDialog("expense", int(eid), self, title_suffix="(expense)")
        dlg.exec_()

    def delete_selected(self):
        ids = self._selected_ids()
        if not ids: return
        if QtWidgets.QMessageBox.question(self, "Confirm", f"Delete {len(ids)} record(s)?") == QtWidgets.QMessageBox.Yes:
            delete_attachments_for("expense", ids)
            for i in ids: db.execute("DELETE FROM expenses WHERE id=?", (i,))
            self.reload_table()

    # ----- import/export -----
    def import_csv(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Import CSV", "", "CSV files (*.csv)")
        if not path: return
        cnt = 0; bad = 0
        with open(path, "r", encoding="utf-8-sig") as f:
            rd = csv.DictReader(f)
            for row in rd:
                try:
                    dt = row.get("date") or row.get("dt")
                    cat = row.get("category") or "Other"
                    amt = float(row.get("amount"))
                    note = row.get("note") or ""
                    datetime.strptime(dt, "%Y-%m-%d")
                    db.execute("""INSERT INTO expenses(dt,category,amount,note,created_at)
                                  VALUES(?,?,?,?,?)""", (dt, cat, amt, note, now_berlin().replace(tzinfo=None).isoformat(timespec="seconds")))
                    cnt += 1
                except Exception:
                    bad += 1
        QtWidgets.QMessageBox.information(self, "Import", f"Imported: {cnt}\nSkipped: {bad}")
        self.reload_table()

    def export_csv(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Export CSV (filtered)", f"expenses_{today_str()}.csv", "CSV files (*.csv)")
        if not path: return
        q, a = self._apply_filters_query()
        rows = db.execute(q, a).fetchall()
        with open(path, "w", newline="", encoding="utf-8") as f:
            wr = csv.writer(f)
            wr.writerow(["date","category","amount","note"])
            for r in rows:
                wr.writerow([r["dt"], r["category"], f"{r['amount']:.2f}", r["note"] or ""])
        QtWidgets.QMessageBox.information(self, "Export", f"Saved to:\n{path}")

# ---------- Calendar with clean month-only view ----------
class CleanCalendar(QtWidgets.QCalendarWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setGridVisible(True)
        self.setVerticalHeaderFormat(QtWidgets.QCalendarWidget.NoVerticalHeader)
        self.currentPageChanged.connect(self._update_range)
        self._update_range(self.yearShown(), self.monthShown())

    def _update_range(self, y: int, m: int):
        import calendar
        last_day = calendar.monthrange(y, m)[1]
        first = QtCore.QDate(y, m, 1)
        last = QtCore.QDate(y, m, last_day)
        self.setDateRange(first, last)
        if self.selectedDate().month() != m or self.selectedDate().year() != y:
            self.setSelectedDate(first)
        self.updateCells()

    def paintCell(self, painter: QtGui.QPainter, rect: QtCore.QRect, qdate: QtCore.QDate):
        if qdate.month() != self.monthShown() or qdate.year() != self.yearShown():
            painter.save()
            painter.fillRect(rect, self.palette().base())
            painter.restore()
            return
        super().paintCell(painter, rect, qdate)

class EventDialog(QtWidgets.QDialog):
    def __init__(self, parent=None, event=None):
        super().__init__(parent)
        self.setWindowTitle("Event")
        form = QtWidgets.QFormLayout(self)

        self.title = QtWidgets.QLineEdit()
        self.start_dt = QtWidgets.QDateTimeEdit(QtCore.QDateTime.currentDateTime()); self.start_dt.setCalendarPopup(True)
        self.end_dt = QtWidgets.QDateTimeEdit(QtCore.QDateTime.currentDateTime().addSecs(3600)); self.end_dt.setCalendarPopup(True)
        self.location = QtWidgets.QLineEdit()
        self.description = QtWidgets.QPlainTextEdit()
        self.remind = QtWidgets.QSpinBox(); self.remind.setRange(0, 10080); self.remind.setSuffix(" min"); self.remind.setValue(0)
        self.recur = QtWidgets.QComboBox(); self.recur.addItems(["none", "daily", "weekly", "monthly"])

        if event:
            self.title.setText(event["title"])
            self.start_dt.setDateTime(QtCore.QDateTime.fromString(event["start_ts"], QtCore.Qt.ISODate))
            if event["end_ts"]:
                self.end_dt.setDateTime(QtCore.QDateTime.fromString(event["end_ts"], QtCore.Qt.ISODate))
            self.location.setText(event["location"] or "")
            self.description.setPlainText(event["description"] or "")
            self.remind.setValue(event["remind_minutes"] or 0)
            self.recur.setCurrentText(event["recur"] or "none")

        form.addRow("Title", self.title); form.addRow("Start", self.start_dt); form.addRow("End", self.end_dt)
        form.addRow("Location", self.location); form.addRow("Description", self.description)
        form.addRow("Reminder", self.remind); form.addRow("Repeat", self.recur)

        btns = QtWidgets.QDialogButtonBox(QtWidgets.QDialogButtonBox.Ok | QtWidgets.QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept); btns.rejected.connect(self.reject); form.addRow(btns)

    def get_data(self):
        return {
            "title": self.title.text().strip(),
            "start_ts": self.start_dt.dateTime().toString(QtCore.Qt.ISODate),
            "end_ts": self.end_dt.dateTime().toString(QtCore.Qt.ISODate),
            "location": self.location.text().strip(),
            "description": self.description.toPlainText().strip(),
            "remind_minutes": int(self.remind.value()),
            "recur": self.recur.currentText(),
        }

class CalendarPage(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        root = QtWidgets.QHBoxLayout(self)

        leftv = QtWidgets.QVBoxLayout()
        header = QtWidgets.QHBoxLayout(); header.addWidget(H1("Calendar")); header.addStretch(1); leftv.addLayout(header)
        leftv.addWidget(Separator())

        self.calendar = CleanCalendar()
        self.calendar.selectionChanged.connect(self.reload_list)
        leftv.addWidget(self.calendar)

        btns = QtWidgets.QHBoxLayout()
        self.add_btn = QtWidgets.QPushButton("Add"); self.add_btn.setObjectName("Primary")
        self.edit_btn = QtWidgets.QPushButton("Edit")
        self.attach_btn = QtWidgets.QPushButton("Attachments…")
        self.del_btn = QtWidgets.QPushButton("Delete")
        self.add_btn.clicked.connect(self.add_event)
        self.edit_btn.clicked.connect(self.edit_event)
        self.attach_btn.clicked.connect(self.open_attachments)
        self.del_btn.clicked.connect(self.delete_event)
        btns.addWidget(self.add_btn); btns.addWidget(self.edit_btn); btns.addWidget(self.attach_btn); btns.addWidget(self.del_btn); leftv.addLayout(btns)

        rightv = QtWidgets.QVBoxLayout()
        rightv.addWidget(H2("Events for selected date"))
        self.events_list = QtWidgets.QListWidget(); self.events_list.itemDoubleClicked.connect(self.edit_event)
        rightv.addWidget(self.events_list, 1)

        left_card = CardLayout(QtWidgets.QFrame()); left_card.setLayout(leftv)
        right_card = CardLayout(QtWidgets.QFrame()); right_card.setLayout(rightv)
        root.addWidget(left_card, 2); root.addWidget(right_card, 3)

        self.reload_list()

    def current_date_str(self):
        return self.calendar.selectedDate().toString("yyyy-MM-dd")

    def _selected_event_id(self):
        it = self.events_list.currentItem()
        if not it: return None
        return it.data(QtCore.Qt.UserRole)

    def reload_list(self):
        self.events_list.clear()
        d = self.current_date_str()
        cur = db.execute("SELECT * FROM events WHERE substr(start_ts,1,10)=? ORDER BY start_ts ASC", (d,))
        rows = list(cur.fetchall())

        # naive recurrence projection
        sel_date = datetime.strptime(d, "%Y-%m-%d").date()
        cur2 = db.execute("SELECT * FROM events WHERE recur!='none'")
        for r in cur2.fetchall():
            st = datetime.fromisoformat(r["start_ts"]).date()
            if r["recur"] == "daily" and sel_date >= st: rows.append(r)
            elif r["recur"] == "weekly" and sel_date >= st and sel_date.weekday() == st.weekday(): rows.append(r)
            elif r["recur"] == "monthly" and sel_date >= st and sel_date.day == st.day: rows.append(r)

        for row in sorted(rows, key=lambda x: x["start_ts"]):
            start = row["start_ts"][11:16]
            where = f" @ {row['location']}" if row["location"] else ""
            recur = f" 🔁{row['recur']}" if row["recur"] and row["recur"] != "none" else ""
            remind = f" ⏰{row['remind_minutes']}m" if row["remind_minutes"] else ""
            item = QtWidgets.QListWidgetItem(f"{start}  {row['title']}{where}{recur}{remind}")
            item.setData(QtCore.Qt.UserRole, row["id"])
            self.events_list.addItem(item)

    def add_event(self):
        dlg = EventDialog(self)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            d = dlg.get_data()
            if not d["title"]:
                QtWidgets.QMessageBox.warning(self, "Error", "Title is required"); return
            db.execute("""INSERT INTO events(title,start_ts,end_ts,location,description,remind_minutes,recur,created_at)
                          VALUES(?,?,?,?,?,?,?,?)""",
                       (d["title"], d["start_ts"], d["end_ts"], d["location"], d["description"],
                        d["remind_minutes"], d["recur"], now_berlin().replace(tzinfo=None).isoformat(timespec="seconds")))
            self.reload_list()

    def edit_event(self):
        eid = self._selected_event_id()
        if not eid: return
        row = db.execute("SELECT * FROM events WHERE id=?", (eid,)).fetchone()
        if not row: return
        dlg = EventDialog(self, row)
        if dlg.exec_() == QtWidgets.QDialog.Accepted:
            d = dlg.get_data()
            db.execute("""UPDATE events SET title=?, start_ts=?, end_ts=?, location=?, description=?,
                          remind_minutes=?, recur=? WHERE id=?""",
                       (d["title"], d["start_ts"], d["end_ts"], d["location"], d["description"],
                        d["remind_minutes"], d["recur"], eid))
            self.reload_list()

    def open_attachments(self):
        eid = self._selected_event_id()
        if not eid:
            QtWidgets.QMessageBox.information(self, "Attachments", "Select an event from the list.")
            return
        dlg = AttachmentsDialog("event", int(eid), self, title_suffix="(event)")
        dlg.exec_()

    def delete_event(self):
        eid = self._selected_event_id()
        if not eid: return
        if QtWidgets.QMessageBox.question(self, "Confirm", "Delete event?") == QtWidgets.QMessageBox.Yes:
            delete_attachments_for("event", [eid])
            db.execute("DELETE FROM events WHERE id=?", (eid,))
            self.reload_list()

# ---------- Tasks ----------
class TasksPage(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(H1("Tasks")); root.addWidget(Separator())

        form = QtWidgets.QHBoxLayout()
        self.title = QtWidgets.QLineEdit(); self.title.setPlaceholderText("New task...")
        self.due = QtWidgets.QDateEdit(QtCore.QDate.currentDate()); self.due.setCalendarPopup(True)
        self.category = QtWidgets.QComboBox(); self.category.setEditable(True); self.category.addItems(["Study","Work","Personal","Home","Other"])
        self.priority = QtWidgets.QSpinBox(); self.priority.setRange(0, 10)
        add = QtWidgets.QPushButton("Add"); add.setObjectName("Primary"); add.clicked.connect(self.add_task)
        for w in [self.title, self.due, self.category, self.priority, add]: form.addWidget(w)
        root.addWidget(CardLayout(QtWidgets.QFrame()), 0); root.itemAt(root.count()-1).widget().setLayout(form)

        cols = QtWidgets.QHBoxLayout()
        self.todo = self._make_list("To Do", "todo")
        self.doing = self._make_list("Doing", "doing")
        self.done = self._make_list("Done", "done")
        cols.addWidget(self.todo, 1); cols.addWidget(self.doing, 1); cols.addWidget(self.done, 1)
        root.addLayout(cols, 1)

        actions = QtWidgets.QHBoxLayout()
        self.mark_doing = QtWidgets.QPushButton("→ Doing")
        self.mark_done = QtWidgets.QPushButton("✓ Done")
        self.mark_todo = QtWidgets.QPushButton("↺ To Do")
        self.attach_btn = QtWidgets.QPushButton("Attachments…")
        self.delete_btn = QtWidgets.QPushButton("Delete"); self.delete_btn.setObjectName("Danger")
        self.mark_doing.clicked.connect(lambda: self._move_selected("doing"))
        self.mark_done.clicked.connect(lambda: self._move_selected("done"))
        self.mark_todo.clicked.connect(lambda: self._move_selected("todo"))
        self.attach_btn.clicked.connect(self.open_attachments)
        self.delete_btn.clicked.connect(self._delete_selected)
        for w in [self.mark_doing, self.mark_done, self.mark_todo, self.attach_btn]: actions.addWidget(w)
        actions.addStretch(1); actions.addWidget(self.delete_btn)
        root.addLayout(actions)

        self.reload()

    def _make_list(self, title: str, status: str) -> QtWidgets.QWidget:
        card = CardLayout(QtWidgets.QFrame())
        v = QtWidgets.QVBoxLayout(card)
        v.addWidget(H2(title))
        lw = QtWidgets.QListWidget(); lw.setProperty("status", status)
        v.addWidget(lw, 1)
        return card

    def _lw(self, card: QtWidgets.QWidget) -> QtWidgets.QListWidget:
        return card.layout().itemAt(1).widget()

    def add_task(self):
        title = self.title.text().strip()
        if not title: return
        due = self.due.date().toPyDate().isoformat()
        cat = self.category.currentText().strip() or "Other"
        pr = int(self.priority.value())
        db.execute("""INSERT INTO tasks(title,due_dt,category,priority,status,created_at)
                      VALUES(?,?,?,?, 'todo', ?)""",
                   (title, due, cat, pr, now_berlin().replace(tzinfo=None).isoformat(timespec="seconds")))
        self.title.clear(); self.reload()

    def reload(self):
        for col in [self.todo, self.doing, self.done]: self._lw(col).clear()
        cur = db.execute("SELECT * FROM tasks ORDER BY status!='done', priority DESC, due_dt ASC")
        for r in cur.fetchall():
            item = QtWidgets.QListWidgetItem(f"{r['title']}  [{r['category']}]  pr:{r['priority']}  due:{r['due_dt'] or '-'}")
            item.setData(QtCore.Qt.UserRole, r["id"])
            {"todo": self._lw(self.todo), "doing": self._lw(self.doing), "done": self._lw(self.done)}[r["status"]].addItem(item)

    def _selected(self):
        for col in [self.todo, self.doing, self.done]:
            it = self._lw(col).currentItem()
            if it: return it.data(QtCore.Qt.UserRole)
        return None

    def _move_selected(self, status: str):
        tid = self._selected()
        if not tid: return
        db.execute("UPDATE tasks SET status=? WHERE id=?", (status, tid))
        self.reload()

    def open_attachments(self):
        tid = self._selected()
        if not tid:
            QtWidgets.QMessageBox.information(self, "Attachments", "Select a task.")
            return
        dlg = AttachmentsDialog("task", int(tid), self, title_suffix="(task)")
        dlg.exec_()

    def _delete_selected(self):
        tid = self._selected()
        if not tid: return
        if QtWidgets.QMessageBox.question(self, "Confirm", "Delete task?") == QtWidgets.QMessageBox.Yes:
            delete_attachments_for("task", [tid])
            db.execute("DELETE FROM tasks WHERE id=?", (tid,))
            self.reload()

# ---------- Notes ----------
class NotesPage(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(H1("Notes")); root.addWidget(Separator())

        form = QtWidgets.QHBoxLayout()
        self.input = QtWidgets.QLineEdit(); self.input.setPlaceholderText("Quick note...")
        add = QtWidgets.QPushButton("Add"); add.setObjectName("Primary"); add.clicked.connect(self.add_note)
        form.addWidget(self.input, 1); form.addWidget(add)
        card = CardLayout(QtWidgets.QFrame()); card.setLayout(form); root.addWidget(card)

        self.list = QtWidgets.QListWidget()
        root.addWidget(self.list, 1)

        btns = QtWidgets.QHBoxLayout()
        self.attach_btn = QtWidgets.QPushButton("Attachments…")
        self.del_btn = QtWidgets.QPushButton("Delete selected"); self.del_btn.setObjectName("Danger")
        self.attach_btn.clicked.connect(self.open_attachments)
        self.del_btn.clicked.connect(self.delete_note)
        btns.addWidget(self.attach_btn); btns.addStretch(1); btns.addWidget(self.del_btn)
        root.addLayout(btns)

        self.reload()

    def add_note(self):
        txt = self.input.text().strip()
        if not txt: return
        db.execute("INSERT INTO notes(content, created_at) VALUES(?,?)", (txt, now_berlin().replace(tzinfo=None).isoformat(timespec="seconds")))
        self.input.clear(); self.reload()

    def reload(self):
        self.list.clear()
        for r in db.execute("SELECT * FROM notes ORDER BY id DESC LIMIT 500").fetchall():
            item = QtWidgets.QListWidgetItem(r["content"])
            item.setData(QtCore.Qt.UserRole, r["id"])
            self.list.addItem(item)

    def _selected_id(self):
        it = self.list.currentItem()
        if not it: return None
        return it.data(QtCore.Qt.UserRole)

    def open_attachments(self):
        nid = self._selected_id()
        if not nid:
            QtWidgets.QMessageBox.information(self, "Attachments", "Select a note.")
            return
        dlg = AttachmentsDialog("note", int(nid), self, title_suffix="(note)")
        dlg.exec_()

    def delete_note(self):
        nid = self._selected_id()
        if not nid: return
        if QtWidgets.QMessageBox.question(self, "Confirm", "Delete note?") == QtWidgets.QMessageBox.Yes:
            delete_attachments_for("note", [nid])
            db.execute("DELETE FROM notes WHERE id=?", (nid,))
            self.reload()

# ---------- Settings (theme, budgets, PIN, backup/restore) ----------
class SettingsPage(QtWidgets.QWidget):
    def __init__(self, on_theme_change):
        super().__init__()
        self.on_theme_change = on_theme_change
        root = QtWidgets.QVBoxLayout(self)
        root.addWidget(H1("Settings")); root.addWidget(Separator())

        # Appearance
        theme_card = CardLayout(QtWidgets.QFrame()); v = QtWidgets.QVBoxLayout(theme_card)
        v.addWidget(H2("Appearance"))
        row = QtWidgets.QHBoxLayout()
        row.addWidget(QtWidgets.QLabel("Theme:"))
        self.theme_combo = QtWidgets.QComboBox(); self.theme_combo.addItems(["dark", "light"]); self.theme_combo.setCurrentText(get_setting("theme","dark"))
        apply_btn = QtWidgets.QPushButton("Apply"); apply_btn.setObjectName("Primary"); apply_btn.clicked.connect(self.apply_theme)
        row.addWidget(self.theme_combo); row.addWidget(apply_btn); row.addStretch(1)
        v.addLayout(row)
        root.addWidget(theme_card)

        # PIN
        pin_card = CardLayout(QtWidgets.QFrame()); vp = QtWidgets.QVBoxLayout(pin_card)
        vp.addWidget(H2("Security (PIN)"))
        pin_row = QtWidgets.QHBoxLayout()
        self.pin_inp = QtWidgets.QLineEdit(); self.pin_inp.setEchoMode(QtWidgets.QLineEdit.Password); self.pin_inp.setPlaceholderText("New PIN (4–12 chars)")
        set_btn = QtWidgets.QPushButton("Set / Change PIN"); set_btn.clicked.connect(self.set_pin)
        clear_btn = QtWidgets.QPushButton("Remove PIN"); clear_btn.setObjectName("Danger"); clear_btn.clicked.connect(self.clear_pin)
        pin_row.addWidget(self.pin_inp); pin_row.addWidget(set_btn); pin_row.addWidget(clear_btn); pin_row.addStretch(1)
        vp.addLayout(pin_row)
        root.addWidget(pin_card)

        # Budgets
        budget_card = CardLayout(QtWidgets.QFrame()); vb = QtWidgets.QVBoxLayout(budget_card)
        vb.addWidget(H2("Budgets (monthly by category)"))
        self.bud_table = QtWidgets.QTableWidget(0, 2); self.bud_table.setHorizontalHeaderLabels(["Category", "Monthly limit (€)"]); self.bud_table.horizontalHeader().setStretchLastSection(True)
        hb = QtWidgets.QHBoxLayout()
        add_bud = QtWidgets.QPushButton("Add/Update"); add_bud.setObjectName("Primary"); add_bud.clicked.connect(self.add_or_update_budget)
        del_bud = QtWidgets.QPushButton("Delete"); del_bud.setObjectName("Danger"); del_bud.clicked.connect(self.delete_budget)
        hb.addWidget(add_bud); hb.addWidget(del_bud); hb.addStretch(1)
        vb.addWidget(self.bud_table, 1); vb.addLayout(hb)
        root.addWidget(budget_card, 1)

        # Backup / Restore
        br_card = CardLayout(QtWidgets.QFrame()); vr = QtWidgets.QVBoxLayout(br_card)
        vr.addWidget(H2("Data"))
        r = QtWidgets.QHBoxLayout()
        backup = QtWidgets.QPushButton("Backup database…"); backup.clicked.connect(self.backup_db)
        restore = QtWidgets.QPushButton("Restore database…"); restore.setObjectName("Danger"); restore.clicked.connect(self.restore_db)
        r.addWidget(backup); r.addWidget(restore); r.addStretch(1)
        vr.addLayout(r)
        root.addWidget(br_card)

        self.reload_budgets()

    # Appearance
    def apply_theme(self):
        set_setting("theme", self.theme_combo.currentText())
        self.on_theme_change()

    # PIN
    def set_pin(self):
        pin = self.pin_inp.text().strip()
        if len(pin) < 4:
            QtWidgets.QMessageBox.warning(self, "PIN", "PIN must be at least 4 characters")
            return
        set_setting("pin_hash", sha256(pin))
        self.pin_inp.clear()
        QtWidgets.QMessageBox.information(self, "PIN", "PIN set")

    def clear_pin(self):
        db.execute("DELETE FROM settings WHERE key='pin_hash'")
        QtWidgets.QMessageBox.information(self, "PIN", "PIN removed")

    # Budgets
    def reload_budgets(self):
        self.bud_table.setRowCount(0)
        for r in db.execute("SELECT category, monthly_limit FROM budgets ORDER BY category").fetchall():
            row = self.bud_table.rowCount(); self.bud_table.insertRow(row)
            self.bud_table.setItem(row, 0, QtWidgets.QTableWidgetItem(r["category"]))
            self.bud_table.setItem(row, 1, QtWidgets.QTableWidgetItem(f"{r['monthly_limit']:.2f}"))

    def add_or_update_budget(self):
        cat, ok = QtWidgets.QInputDialog.getText(self, "Budget", "Category name:")
        if not ok or not cat.strip(): return
        limit, ok2 = QtWidgets.QInputDialog.getDouble(self, "Budget", "Monthly limit (€):", 100.0, 0.0, 1_000_000.0, 2)
        if not ok2: return
        db.execute("""INSERT INTO budgets(category, monthly_limit) VALUES(?,?)
                      ON CONFLICT(category) DO UPDATE SET monthly_limit=excluded.monthly_limit""",
                   (cat.strip(), float(limit)))
        self.reload_budgets()

    def delete_budget(self):
        it = self.bud_table.currentItem()
        if not it: return
        cat = self.bud_table.item(it.row(), 0).text()
        if QtWidgets.QMessageBox.question(self, "Confirm", f"Delete budget for '{cat}'?") == QtWidgets.QMessageBox.Yes:
            db.execute("DELETE FROM budgets WHERE category=?", (cat,))
            self.reload_budgets()

    # Backup / Restore
    def backup_db(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Backup database", f"LifeTracker_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db", "SQLite DB (*.db)")
        if not path: return
        shutil.copyfile(DB_PATH, path)
        QtWidgets.QMessageBox.information(self, "Backup", f"Saved to:\n{path}")

    def restore_db(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Restore database", "", "SQLite DB (*.db)")
        if not path: return
        if QtWidgets.QMessageBox.question(self, "Confirm", "Replace current data.db with selected file?\nThe app will need a restart.") == QtWidgets.QMessageBox.Yes:
            shutil.copyfile(path, DB_PATH)
            QtWidgets.QMessageBox.information(self, "Restore", "Restored. Please restart the app.")

# ---------- Theming ----------
def apply_theme(app: QtWidgets.QApplication):
    qss = ""
    if os.path.exists(STYLE_PATH):
        try:
            with open(STYLE_PATH, "r", encoding="utf-8") as f: qss = f.read()
        except Exception: qss = ""
    if get_setting("theme","dark") == "light":
        qss += """
        QWidget{background:#f6f7fb;color:#0f1115;}
        QFrame#Card, QWidget#Card, QTextEdit#Card{background:#ffffff;border:1px solid #e5e7eb;border-radius:14px;}
        QListWidget#Sidebar{background:#ffffff;border:1px solid #e5e7eb;}
        """
    app.setStyleSheet(qss)

# ---------- OS notifications (Windows toast) ----------
try:
    from win10toast import ToastNotifier
    WIN_TOAST = ToastNotifier()
except Exception:
    WIN_TOAST = None  # fallback to tray balloons

def show_os_notification(title: str, msg: str):
    """Prefer native toast; fallback to tray balloon."""
    if WIN_TOAST:
        try:
            WIN_TOAST.show_toast(title, msg, duration=5, threaded=True)
            return
        except Exception:
            pass
    # Fallback handled by _notify

# ---------- Main Window ----------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1220, 820)

        # Recurrings on startup
        process_recurring_expenses()

        # Central: sidebar + pages
        central = QtWidgets.QWidget()
        grid = QtWidgets.QHBoxLayout(central); grid.setContentsMargins(16, 12, 16, 12); grid.setSpacing(12)

        self.sidebar = QtWidgets.QListWidget(); self.sidebar.setObjectName("Sidebar")
        for t in ["🏠  Dashboard","💶  Expenses","📅  Calendar","✅  Tasks","📝  Notes","📊  Stats","⚙️  Settings"]:
            self.sidebar.addItem(t)
        self.sidebar.setFixedWidth(220); self.sidebar.currentRowChanged.connect(self._on_nav)
        grid.addWidget(self.sidebar, 0)

        self.pages = QtWidgets.QStackedWidget()
        self.page_dashboard = Dashboard()
        self.page_expenses = ExpensesPage()
        self.page_calendar = CalendarPage()
        self.page_tasks = TasksPage()
        self.page_notes = NotesPage()
        self.page_stats = StatsPage()
        self.page_settings = SettingsPage(on_theme_change=lambda: apply_theme(QtWidgets.QApplication.instance()))
        for p in [self.page_dashboard,self.page_expenses,self.page_calendar,self.page_tasks,self.page_notes,self.page_stats,self.page_settings]:
            self.pages.addWidget(p)
        grid.addWidget(self.pages, 1)
        self.setCentralWidget(central)

        # Menu
        bar = self.menuBar()
        filem = bar.addMenu("File")
        open_data = filem.addAction("Open data folder"); open_data.triggered.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(DATA_DIR)))
        open_attach = filem.addAction("Open attachments folder"); open_attach.triggered.connect(lambda: QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(ATTACH_DIR)))
        filem.addSeparator()
        quit_action = filem.addAction("Quit"); quit_action.triggered.connect(QtWidgets.qApp.quit)

        # Tray + notifications
        self.tray = QtWidgets.QSystemTrayIcon(self); self.tray.setIcon(self.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon))
        tmenu = QtWidgets.QMenu(); tmenu.addAction("Show/Hide", self.toggle_visibility); tmenu.addAction("Exit", QtWidgets.qApp.quit)
        self.tray.setContextMenu(tmenu); self.tray.show()

        # Timers
        self.notif_timer = QtCore.QTimer(self); self.notif_timer.timeout.connect(self.check_notifications)
        self.notif_timer.start(30 * 1000)  # check every 30s

        self.clock_label = QtWidgets.QLabel()
        self.statusBar().addPermanentWidget(self.clock_label)
        self.clock_timer = QtCore.QTimer(self); self.clock_timer.timeout.connect(self.update_clock)
        self.clock_timer.start(1000)  # every second
        self.update_clock()

        self.sidebar.setCurrentRow(0)
        self.statusBar().showMessage("Ready")

    def update_clock(self):
        self.clock_label.setText("Berlin time: " + now_berlin().strftime("%Y-%m-%d %H:%M:%S"))

    def _on_nav(self, idx: int):
        self.pages.setCurrentIndex(idx)
        if idx == 0: self.page_dashboard.reload()
        if idx == 1: self.page_expenses.reload_table()
        if idx == 2: self.page_calendar.reload_list()
        if idx == 3: self.page_tasks.reload()
        if idx == 4: self.page_notes.reload()
        if idx == 5: self.page_stats.reload()

    def toggle_visibility(self):
        if self.isVisible(): self.hide()
        else: self.showNormal(); self.activateWindow()

    def _notify(self, title, msg):
        # Fallback tray balloon
        self.tray.showMessage(title, msg, QtWidgets.QSystemTrayIcon.Information, 5000)

    def check_notifications(self):
        """
        Fire exactly at (start - remind_minutes) in Berlin time.
        Timestamps in DB are treated as Berlin local.
        """
        now_local = now_berlin()
        rows = db.execute("""SELECT e.id, e.title, e.start_ts, e.remind_minutes
                             FROM events e
                             WHERE e.remind_minutes IS NOT NULL AND e.remind_minutes > 0""").fetchall()
        for r in rows:
            try:
                start_naive = datetime.fromisoformat(r["start_ts"])
            except Exception:
                continue
            start_local = as_berlin_local(start_naive)
            target = start_local - timedelta(minutes=int(r["remind_minutes"]))
            if now_local >= target:
                recently = db.execute(
                    "SELECT COUNT(*) c FROM notifications_log WHERE event_id=? AND fired_at>=?",
                    (r["id"], (now_local - timedelta(minutes=5)).replace(tzinfo=None).isoformat(timespec="seconds")),
                ).fetchone()["c"]
                if recently == 0:
                    show_os_notification(f"Reminder: {r['title']}", f"Starts at {start_local.strftime('%H:%M')} (Berlin)")
                    self._notify(f"Reminder: {r['title']}", f"Starts at {start_local.strftime('%H:%M')} (Berlin)")
                    db.execute("INSERT INTO notifications_log(event_id,fired_at) VALUES(?,?)",
                               (r["id"], now_local.replace(tzinfo=None).isoformat(timespec="seconds")))

# ---------- PIN gate ----------
def pin_gate_or_ok(parent=None) -> bool:
    pin_hash = get_setting("pin_hash", "")
    if not pin_hash: return True
    for _ in range(3):
        pin, ok = QtWidgets.QInputDialog.getText(parent, "Enter PIN", "PIN:", QtWidgets.QLineEdit.Password)
        if not ok: return False
        if sha256(pin) == pin_hash: return True
        QtWidgets.QMessageBox.warning(parent, "PIN", "Wrong PIN")
    return False

# ---------- Entry ----------
def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    apply_theme(app)

    if not pin_gate_or_ok():
        return

    win = MainWindow()
    win.show()
    sys.exit(app.exec_())

if __name__ == "__main__":
    main()
