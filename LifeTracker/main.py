# -*- coding: utf-8 -*-
"""
LifeTracker — full app with:
- Sidebar UI (Dashboard, Expenses, Calendar, Tasks, Notes, Stats, AI, Settings)
- Dark theme (style.qss if present)
- SQLite persistence (tasks, expenses, notes, events)
- Calendar with month/year selectors + add task/event to a specific day & time
- Tasks with priorities, status, filters, progress
- Expenses with table, totals, pie chart, export (Excel/PDF)
- Notes CRUD
- Stats (tasks & expenses charts)
- AI tab (DeepSeek): chat + quick analyses
Launch: python main.py  (you can also make a .bat to activate venv then run main.py)
"""
import os
import sys
import calendar
import sqlite3
from datetime import datetime, date, timedelta
from collections import defaultdict, Counter
from pathlib import Path
from typing import Optional, List, Any, Tuple


# --- Third-party ---
import requests
# --- Attachments (dual-mode import) ---
import os, sys
if __package__ is None or __package__ == "":
    sys.path.append(os.path.dirname(__file__))
    from attachments_qt import AttachmentsPage, AttachmentManager
else:
    from .attachments_qt import AttachmentsPage, AttachmentManager

from pathlib import Path

import pandas as pd
import matplotlib
matplotlib.use("Qt5Agg")
import matplotlib.pyplot as plt
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas as pdfcanvas

from PyQt5 import QtWidgets, QtCore, QtGui
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

# ---- App constants ----
APP_NAME = "LifeTracker"
APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "data.db")
STYLE_PATH = os.path.join(APP_DIR, "style.qss")

EUR = "€"

# DeepSeek (user requested hardcoded key)
DEEPSEEK_API_KEY = "sk-12e5757a37f44dac829d92d4a03f8722"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"


# -------------------- THEME --------------------
def apply_dark(app: QtWidgets.QApplication):
    if os.path.exists(STYLE_PATH):
        with open(STYLE_PATH, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
    pal = app.palette()
    pal.setColor(pal.Window, QtGui.QColor("#0E0F13"))
    pal.setColor(pal.Base, QtGui.QColor("#0E0F13"))
    pal.setColor(pal.Text, QtGui.QColor("#E6E6E6"))
    pal.setColor(pal.ButtonText, QtGui.QColor("#E6E6E6"))
    pal.setColor(pal.Highlight, QtGui.QColor("#365EFF"))
    pal.setColor(pal.HighlightedText, QtGui.QColor("#FFFFFF"))
    app.setPalette(pal)



class DB:
    """
    Просте сховище SQLite для LifeTracker.

    Таблиці
    -------
    tasks(
        id INTEGER PK,
        title TEXT NOT NULL,
        description TEXT,
        due_ts TEXT,                 -- 'YYYY-MM-DD HH:MM:SS'
        priority TEXT NOT NULL DEFAULT 'Low',  -- Low/Medium/High
        status INTEGER NOT NULL DEFAULT 0,     -- 0=open, 1=done
        category TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        completed_at TEXT
    )

    expenses(
        id INTEGER PK,
        dt TEXT NOT NULL,            -- 'YYYY-MM-DD'
        category TEXT,
        amount REAL NOT NULL DEFAULT 0,
        note TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )

    events(
        id INTEGER PK,
        title TEXT,
        start_ts TEXT NOT NULL,      -- 'YYYY-MM-DD HH:MM:SS'
        end_ts   TEXT,               -- optional
        category TEXT,
        note TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    )
    """

    def __init__(self, db_path: Path | str = Path("data") / "lifetracker.sqlite3"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.cur = self.conn.cursor()
        self._pragma()
        self._migrate()

    # ---------- internal ----------
    def _pragma(self) -> None:
        self.cur.execute("PRAGMA journal_mode=WAL;")
        self.cur.execute("PRAGMA foreign_keys=ON;")
        self.cur.execute("PRAGMA synchronous=NORMAL;")
        self.conn.commit()

    def _table_has_column(self, table: str, column: str) -> bool:
        rows = self.cur.execute(f"PRAGMA table_info({table})").fetchall()
        return any(r["name"] == column for r in rows)

    def _ensure_column(self, table: str, column: str, ddl: str) -> None:
        if not self._table_has_column(table, column):
            self.cur.execute(f"ALTER TABLE {table} ADD COLUMN {ddl}")
            self.conn.commit()

    def _migrate(self) -> None:
    # ---- TASKS ----
    self.cur.execute("""
    CREATE TABLE IF NOT EXISTS tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT NOT NULL,
        description TEXT,
        due_ts TEXT,
        priority TEXT NOT NULL DEFAULT 'Low',
        status INTEGER NOT NULL DEFAULT 0,
        category TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now')),
        completed_at TEXT
    );
    """)
    # legacy columns (на випадок дуже старих БД)
    self._ensure_column("tasks", "description", "description TEXT")
    self._ensure_column("tasks", "category",    "category TEXT")
    self._ensure_column("tasks", "completed_at","completed_at TEXT")
    self._ensure_column("tasks", "priority",    "priority TEXT NOT NULL DEFAULT 'Low'")
    # indexes (після ensure)
    self.cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_due     ON tasks(due_ts)")
    self.cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status  ON tasks(status)")
    self.cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at)")
    if self._table_has_column("tasks", "category"):
        self.cur.execute("CREATE INDEX IF NOT EXISTS idx_tasks_cat ON tasks(category)")

    # ---- EXPENSES ----
    self.cur.execute("""
    CREATE TABLE IF NOT EXISTS expenses (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        dt TEXT NOT NULL,
        category TEXT,
        amount REAL NOT NULL DEFAULT 0,
        note TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)
    # на випадок старих БД без category/note
    self._ensure_column("expenses", "category", "category TEXT")
    self._ensure_column("expenses", "note",     "note TEXT")
    # indexes
    self.cur.execute("CREATE INDEX IF NOT EXISTS idx_expenses_dt ON expenses(dt)")
    if self._table_has_column("expenses", "category"):
        self.cur.execute("CREATE INDEX IF NOT EXISTS idx_expenses_cat ON expenses(category)")

    # ---- EVENTS ----
    self.cur.execute("""
    CREATE TABLE IF NOT EXISTS events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        start_ts TEXT NOT NULL,
        end_ts   TEXT,
        category TEXT,
        note TEXT,
        created_at TEXT NOT NULL DEFAULT (datetime('now'))
    );
    """)
    # якщо стара БД — додамо відсутні колонки
    self._ensure_column("events", "category", "category TEXT")
    self._ensure_column("events", "note",     "note TEXT")
    # indexes (після ensure)
    self.cur.execute("CREATE INDEX IF NOT EXISTS idx_events_start ON events(start_ts)")
    if self._table_has_column("events", "category"):
        self.cur.execute("CREATE INDEX IF NOT EXISTS idx_events_cat ON events(category)")

    self.conn.commit()


    def update_task(
        self,
        task_id: int,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        due_ts: Optional[str] = None,
        priority: Optional[str] = None,
        category: Optional[str] = None,
        status: Optional[int] = None,
    ) -> None:
        fields: List[str] = []
        values: List[Any] = []
        if title is not None:
            fields.append("title=?"); values.append(title)
        if description is not None:
            fields.append("description=?"); values.append(description)
        if due_ts is not None:
            fields.append("due_ts=?"); values.append(due_ts)
        if priority is not None:
            fields.append("priority=?"); values.append(priority)
        if category is not None:
            fields.append("category=?"); values.append(category)
        if status is not None:
            fields.append("status=?"); values.append(int(status))
        if not fields:
            return
        values.append(task_id)
        self.cur.execute(f"UPDATE tasks SET {', '.join(fields)} WHERE id=?", values)
        self.conn.commit()

    def get_task(self, task_id: int) -> Optional[sqlite3.Row]:
        return self.cur.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()

    def delete_task(self, task_id: int) -> None:
        self.cur.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        self.conn.commit()

    def toggle_task(self, task_id: int, done: bool) -> None:
        if done:
            self.cur.execute("UPDATE tasks SET status=1, completed_at=datetime('now') WHERE id=?", (task_id,))
        else:
            self.cur.execute("UPDATE tasks SET status=0, completed_at=NULL WHERE id=?", (task_id,))
        self.conn.commit()

    def list_tasks(
        self,
        scope: str = "all",
        *,
        category: Optional[str] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        search: Optional[str] = None,
        order_by: str = "COALESCE(due_ts, created_at)",
        order_dir: str = "ASC",
    ) -> List[sqlite3.Row]:
        """
        scope: "today" | "week" | "overdue" | "open" | "done" | "all"
        """
        where: List[str] = []
        params: List[Any] = []

        if scope == "today":
            where.append("date(COALESCE(due_ts, created_at)) = date('now')")
        elif scope == "week":
            where.append("strftime('%Y-%W', COALESCE(due_ts, created_at)) = strftime('%Y-%W','now')")
        elif scope == "overdue":
            where.append("status=0 AND due_ts IS NOT NULL AND datetime(due_ts) < datetime('now')")
        elif scope == "open":
            where.append("status=0")
        elif scope == "done":
            where.append("status=1")
        # else: "all" — без додаткових умов

        if category:
            where.append("category = ?"); params.append(category)
        if date_from and date_to:
            where.append("date(COALESCE(due_ts, created_at)) BETWEEN ? AND ?")
            params.extend([date_from, date_to])
        if search:
            like = f"%{search.strip()}%"
            where.append("(title LIKE ? OR description LIKE ?)")
            params.extend([like, like])

        sql = "SELECT * FROM tasks"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY {order_by} {order_dir}"
        return self.cur.execute(sql, params).fetchall()

    def counts_open_and_overdue(self) -> Tuple[int, int]:
        row = self.cur.execute("""
            SELECT
              SUM(CASE WHEN status=0 THEN 1 ELSE 0 END) AS open,
              SUM(CASE WHEN status=0 AND due_ts IS NOT NULL AND datetime(due_ts)<datetime('now') THEN 1 ELSE 0 END) AS overdue
            FROM tasks
        """).fetchone()
        return int(row["open"] or 0), int(row["overdue"] or 0)

    # =================
    #   EXPENSES API
    # =================
    def add_expense(self, dt: str, category: Optional[str], amount: float, note: Optional[str]) -> int:
        self.cur.execute("""
            INSERT INTO expenses(dt, category, amount, note, created_at)
            VALUES (?,?,?,?, datetime('now'))
        """, (dt, category, float(amount), note))
        self.conn.commit()
        return int(self.cur.lastrowid)

    def list_expenses(
        self,
        *,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        category: Optional[str] = None,
        search: Optional[str] = None,
        order_by: str = "dt",
        order_dir: str = "DESC",
    ) -> List[sqlite3.Row]:
        where: List[str] = []
        params: List[Any] = []
        if date_from and date_to:
            where.append("date(dt) BETWEEN ? AND ?")
            params.extend([date_from, date_to])
        if category:
            where.append("category = ?")
            params.append(category)
        if search:
            like = f"%{search.strip()}%"
            where.append("(category LIKE ? OR note LIKE ?)")
            params.extend([like, like])
        sql = "SELECT * FROM expenses"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY {order_by} {order_dir}"
        return self.cur.execute(sql, params).fetchall()

    def delete_expense(self, expense_id: int) -> None:
        self.cur.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
        self.conn.commit()

    def expense_categories(self) -> List[str]:
        rows = self.cur.execute("SELECT DISTINCT category FROM expenses WHERE category IS NOT NULL ORDER BY 1").fetchall()
        return [r["category"] for r in rows if r["category"]]

    # ===============
    #   EVENTS API
    # ===============
    def add_event(
        self,
        title: Optional[str],
        start_ts: str,
        end_ts: Optional[str] = None,
        category: Optional[str] = None,
        note: Optional[str] = None,
    ) -> int:
        self.cur.execute("""
            INSERT INTO events(title, start_ts, end_ts, category, note, created_at)
            VALUES (?,?,?,?,?, datetime('now'))
        """, (title, start_ts, end_ts, category, note))
        self.conn.commit()
        return int(self.cur.lastrowid)

    def list_events(
        self,
        *,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
        category: Optional[str] = None,
        search: Optional[str] = None,
        order_by: str = "start_ts",
        order_dir: str = "DESC",
    ) -> List[sqlite3.Row]:
        where: List[str] = []
        params: List[Any] = []
        if date_from and date_to:
            where.append("date(start_ts) BETWEEN ? AND ?")
            params.extend([date_from, date_to])
        if category:
            where.append("category = ?")
            params.append(category)
        if search:
            like = f"%{search.strip()}%"
            where.append("(title LIKE ? OR note LIKE ?)")
            params.extend([like, like])
        sql = "SELECT * FROM events"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY {order_by} {order_dir}"
        return self.cur.execute(sql, params).fetchall()

    def delete_event(self, event_id: int) -> None:
        self.cur.execute("DELETE FROM events WHERE id=?", (event_id,))
        self.conn.commit()
        # ============== NOTES API ==============
    def add_note(self, title: str, body: str) -> int:
        self.cur.execute(
            "INSERT INTO notes(title, body, created_at) VALUES (?, ?, datetime('now'))",
            (title, body),
        )
        self.conn.commit()
        return int(self.cur.lastrowid)

    def list_notes(self):
        return self.cur.execute("SELECT * FROM notes ORDER BY created_at DESC").fetchall()

    def delete_note(self, note_id: int) -> None:
        self.cur.execute("DELETE FROM notes WHERE id=?", (note_id,))
        self.conn.commit()

    # ----------
    def close(self) -> None:
        try:
            self.conn.close()
        except Exception:
            pass



# -------------------- WIDGETS --------------------
class MplCanvas(FigureCanvas):
    def __init__(self, width=5, height=3.5, dpi=100):
        self.fig = plt.Figure(figsize=(width, height), dpi=dpi)
        self.ax = self.fig.add_subplot(111)
        super().__init__(self.fig)


# -------------------- PAGES --------------------
class DashboardPage(QtWidgets.QWidget):
    def __init__(self, db: DB):
        super().__init__()
        self.db = db
        v = QtWidgets.QVBoxLayout(self)

        header = QtWidgets.QLabel("🏠 Dashboard")
        header.setProperty("heading", "h1")
        v.addWidget(header)

        grid = QtWidgets.QGridLayout()
        v.addLayout(grid)

        # Cards
        self.card_tasks = self._card("Завдання сьогодні", "0")
        self.card_exp = self._card("Витрати за тиждень", f"0 {EUR}")
        self.card_notes = self._card("Нотаток", "0")

        grid.addWidget(self.card_tasks, 0, 0)
        grid.addWidget(self.card_exp, 0, 1)
        grid.addWidget(self.card_notes, 0, 2)

        # Progress
        self.prog = QtWidgets.QProgressBar()
        self.prog.setFormat("Виконано завдань: %p%")
        v.addWidget(self.prog)

        # Chart area
        self.canvas = MplCanvas()
        v.addWidget(self.canvas)

        refresh = QtWidgets.QPushButton("Оновити")
        refresh.clicked.connect(self.reload)
        v.addWidget(refresh)

        self.reload()

    def _card(self, title, value):
        frame = QtWidgets.QFrame()
        frame.setObjectName("Card")
        lay = QtWidgets.QVBoxLayout(frame)
        t = QtWidgets.QLabel(title)
        t.setProperty("heading", "h2")
        v = QtWidgets.QLabel(value)
        font = v.font(); font.setPointSize(18); font.setBold(True); v.setFont(font)
        lay.addWidget(t)
        lay.addWidget(v)
        frame._value_label = v
        return frame

    def reload(self):
        # tasks today
        today = date.today().isoformat()
        tasks_today = self.db.cur.execute(
            "SELECT COUNT(*) FROM tasks WHERE date(due_ts)=? AND status=0", (today,)
        ).fetchone()[0]
        self.card_tasks._value_label.setText(str(tasks_today))

        # expenses last 7 days
        start = (date.today() - timedelta(days=6)).isoformat()
        end = date.today().isoformat()
        rows = self.db.list_expenses(date_from=start, date_to=end)

        total = sum(r["amount"] for r in rows)
        self.card_exp._value_label.setText(f"{total:.2f} {EUR}")

        # notes count
        notes = self.db.cur.execute("SELECT COUNT(*) FROM notes").fetchone()[0]
        self.card_notes._value_label.setText(str(notes))

        # progress: completed / all
        all_tasks = self.db.cur.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]
        done_tasks = self.db.cur.execute("SELECT COUNT(*) FROM tasks WHERE status=1").fetchone()[0]
        val = int(round((done_tasks / all_tasks) * 100)) if all_tasks else 0
        self.prog.setValue(val)

        # chart: expenses by category last 7 days
        cats = defaultdict(float)
        for r in rows:
            cats[r["category"]] += r["amount"]
        self.canvas.ax.clear()
        if cats:
            self.canvas.ax.pie(cats.values(), labels=cats.keys(), autopct="%1.1f%%")
            self.canvas.ax.set_title("Витрати останні 7 днів")
        else:
            self.canvas.ax.text(0.5, 0.5, "Немає даних", ha="center", va="center")
        self.canvas.draw()


class ExpensesPage(QtWidgets.QWidget):
    """
    Мінімальна версія: Дата, Категорія, Сума, Опис + Видалити.
    Без графіків, експортів, підсумків тощо.
    """
    def __init__(self, db: DB):
        super().__init__()
        self.db = db
        v = QtWidgets.QVBoxLayout(self)

        header = QtWidgets.QLabel("💰 Витрати")
        header.setProperty("heading", "h1")
        v.addWidget(header)

        # ---- Форма вводу ----
        form = QtWidgets.QGridLayout()
        self.e_date = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        self.e_date.setCalendarPopup(True)
        self.e_date.setDisplayFormat("yyyy-MM-dd")

        self.e_cat = QtWidgets.QLineEdit()
        self.e_amount = QtWidgets.QDoubleSpinBox()
        self.e_amount.setRange(0.00, 1_000_000_000.00)
        self.e_amount.setDecimals(2)
        self.e_amount.setSingleStep(1.00)

        self.e_note = QtWidgets.QLineEdit()
        btn_add = QtWidgets.QPushButton("Додати")
        btn_add.clicked.connect(self.add_expense)

        form.addWidget(QtWidgets.QLabel("Дата"),      0, 0); form.addWidget(self.e_date,   0, 1)
        form.addWidget(QtWidgets.QLabel("Категорія"), 0, 2); form.addWidget(self.e_cat,    0, 3)
        form.addWidget(QtWidgets.QLabel("Сума"),      1, 0); form.addWidget(self.e_amount, 1, 1)
        form.addWidget(QtWidgets.QLabel("Опис"),      1, 2); form.addWidget(self.e_note,   1, 3)
        form.addWidget(btn_add, 0, 4, 2, 1)
        v.addLayout(form)

        # ---- Таблиця ----
        self.table = QtWidgets.QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["Дата","Категорія","Сума","Опис","🗑"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(3, QtWidgets.QHeaderView.Stretch)
        hh.setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        v.addWidget(self.table)

        self.reload()

    # ---- Дії ----
    def add_expense(self):
        dt   = self.e_date.date().toString("yyyy-MM-dd")
        cat  = self.e_cat.text().strip()
        amt  = float(self.e_amount.value())
        note = self.e_note.text().strip()
        if amt <= 0:
            QtWidgets.QMessageBox.warning(self, "Помилка", "Сума має бути > 0.")
            return
        self.db.add_expense(dt, cat or None, amt, note or None)
        self.e_cat.clear(); self.e_amount.setValue(0.0); self.e_note.clear()
        self.reload()

    def delete_expense(self, rid: int):
        if QtWidgets.QMessageBox.question(self, "Підтвердження",
                                          f"Видалити запис #{rid}?") != QtWidgets.QMessageBox.Yes:
            return
        self.db.delete_expense(rid)
        self.reload()

    def reload(self):
        rows = self.db.list_expenses()
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            rid  = r["id"]
            dt   = r["dt"] or ""
            cat  = r["category"] or ""
            amt  = r["amount"] if r["amount"] is not None else 0.0
            note = r["note"] or ""

            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(dt))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(cat))
            self.table.setItem(i, 2, QtWidgets.QTableWidgetItem(f"{amt:.2f}"))
            self.table.setItem(i, 3, QtWidgets.QTableWidgetItem(note))

            btn = QtWidgets.QPushButton("Видалити")
            btn.clicked.connect(lambda _, rid=rid: self.delete_expense(rid))
            self.table.setCellWidget(i, 4, btn)




# --- ДОДАЙ/ЗАМІНИ ЦЕЙ БЛОК У main.py ---

class CleanCalendar(QtWidgets.QCalendarWidget):
    """Ховає «сусідні» дні інших місяців, але не ламає навігацію."""
    currentPageChanged = QtCore.pyqtSignal(int, int)  # прокинемо далі (на деяких збірках PyQt5 сигнал може не експортуватись)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        try:
            # якщо доступний рідний сигнал — підпишемось і ретранслюємо
            super().currentPageChanged.connect(self._relay_page_changed)  # type: ignore
        except Exception:
            pass

    def _relay_page_changed(self, y, m):
        self.currentPageChanged.emit(y, m)

    def paintCell(self, painter, rect, qdate):
        # Малюємо лише якщо день у поточному місяці+році
        if qdate.month() != self.monthShown() or qdate.year() != self.yearShown():
            return  # не малюємо «зайві» клітинки
        super().paintCell(painter, rect, qdate)


class EnhancedCalendar(QtWidgets.QWidget):
    """Календар з можливістю додавати завдання на день"""
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db

        layout = QtWidgets.QVBoxLayout(self)

        # Панель керування
        ctrl = QtWidgets.QHBoxLayout()
        self.month = QtWidgets.QComboBox()
        self.month.addItems(["Січ","Лют","Бер","Кві","Тра","Чер","Лип","Сер","Вер","Жов","Лис","Гру"])
        self.year = QtWidgets.QSpinBox(); self.year.setRange(1900, 2100)
        qd = QtCore.QDate.currentDate()
        self.month.setCurrentIndex(qd.month() - 1); self.year.setValue(qd.year())
        today_btn = QtWidgets.QPushButton("Сьогодні")
        ctrl.addWidget(QtWidgets.QLabel("Місяць:")); ctrl.addWidget(self.month)
        ctrl.addWidget(QtWidgets.QLabel("Рік:"));    ctrl.addWidget(self.year)
        ctrl.addStretch(1); ctrl.addWidget(today_btn)
        layout.addLayout(ctrl)

        # Сам календар
        self.calendar = QtWidgets.QCalendarWidget(); self.calendar.setGridVisible(True)
        layout.addWidget(self.calendar)

        # Список завдань під календарем
        self.task_list = QtWidgets.QListWidget()
        layout.addWidget(self.task_list)

        btn_layout = QtWidgets.QHBoxLayout()
        self.add_task_btn = QtWidgets.QPushButton("Додати завдання")
        self.del_task_btn = QtWidgets.QPushButton("Видалити завдання")
        btn_layout.addWidget(self.add_task_btn); btn_layout.addWidget(self.del_task_btn)
        layout.addLayout(btn_layout)

        # Події
        self.month.currentIndexChanged.connect(self._apply_month_year)
        self.year.valueChanged.connect(self._apply_month_year)
        today_btn.clicked.connect(self._go_today)
        self.calendar.selectionChanged.connect(self.load_tasks_for_day)
        self.add_task_btn.clicked.connect(self.add_task)
        self.del_task_btn.clicked.connect(self.delete_task)

        # Завантажуємо завдання для сьогодні
        self.load_tasks_for_day()

    def _apply_month_year(self):
        y = self.year.value(); m = self.month.currentIndex() + 1
        self.calendar.setCurrentPage(y, m)

    def _go_today(self):
        qd = QtCore.QDate.currentDate()
        self.month.setCurrentIndex(qd.month() - 1); self.year.setValue(qd.year())
        self.calendar.setSelectedDate(qd); self.calendar.showSelectedDate()
        self.load_tasks_for_day()

    def _selected_iso_date(self) -> str:
        return self.calendar.selectedDate().toString("yyyy-MM-dd")

    def load_tasks_for_day(self):
        self.task_list.clear()
        d = self._selected_iso_date()
        rows = self.db.cur.execute(
            "SELECT id, title FROM tasks WHERE date(due_ts)=? ORDER BY due_ts", (d,)
        ).fetchall()
        for r in rows:
            self.task_list.addItem(f"{r['id']} | {r['title']}")

    def add_task(self):
        d = self._selected_iso_date()
        title, ok = QtWidgets.QInputDialog.getText(self, "Нове завдання", "Назва:")
        if ok and title:
            self.db.cur.execute(
                "INSERT INTO tasks (title, due_ts, priority, status, created_at) VALUES (?, ?, ?, 0, datetime('now'))",
                (title, f"{d} 00:00:00", "Medium")
            )
            self.db.conn.commit()
            self.load_tasks_for_day()

    def delete_task(self):
        item = self.task_list.currentItem()
        if not item:
            return
        task_id = item.text().split(" | ")[0]
        self.db.cur.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        self.db.conn.commit()
        self.load_tasks_for_day()







class TasksPage(QtWidgets.QWidget):
    def __init__(self, db: DB):
        super().__init__()
        self.db = db
        v = QtWidgets.QVBoxLayout(self)

        header = QtWidgets.QHBoxLayout()
        for scope, text in [("today","Сьогодні"),("week","Тиждень"),("all","Усі")]:
            btn = QtWidgets.QPushButton(text)
            btn.clicked.connect(lambda _, s=scope: self.load_scope(s))
            header.addWidget(btn)
        header.addStretch(1)
        v.addLayout(header)

        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Назва","Крайній термін","Пріор.","Статус","Категорія","Дія","🗑"]
        )
        self.table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.table)

        form = QtWidgets.QGridLayout()
        self.t_title = QtWidgets.QLineEdit()
        self.t_desc  = QtWidgets.QLineEdit()
        self.t_date  = QtWidgets.QDateEdit(QtCore.QDate.currentDate()); self.t_date.setCalendarPopup(True)
        self.t_time  = QtWidgets.QTimeEdit(QtCore.QTime.currentTime()); self.t_time.setDisplayFormat("HH:mm")
        self.t_prio  = QtWidgets.QComboBox(); self.t_prio.addItems(["Low","Medium","High"])
        self.t_cat   = QtWidgets.QLineEdit()
        add = QtWidgets.QPushButton("Додати"); add.setObjectName("Primary")
        add.clicked.connect(self.add_task)

        form.addWidget(QtWidgets.QLabel("Назва"),0,0); form.addWidget(self.t_title,0,1,1,3)
        form.addWidget(QtWidgets.QLabel("Опис"),1,0); form.addWidget(self.t_desc,1,1,1,3)
        form.addWidget(QtWidgets.QLabel("Дата"),2,0); form.addWidget(self.t_date,2,1)
        form.addWidget(QtWidgets.QLabel("Час"),2,2); form.addWidget(self.t_time,2,3)
        form.addWidget(QtWidgets.QLabel("Пріоритет"),3,0); form.addWidget(self.t_prio,3,1)
        form.addWidget(QtWidgets.QLabel("Категорія"),3,2); form.addWidget(self.t_cat,3,3)
        form.addWidget(add,4,3)
        v.addLayout(form)

        self.scope = "all"
        self.load_scope("all")

    def load_scope(self, scope):
        self.scope = scope
        rows = self.db.list_tasks(scope)
        self.table.setRowCount(len(rows))
        for i, r in enumerate(rows):
            title_item = QtWidgets.QTableWidgetItem(r["title"])
            title_item.setData(QtCore.Qt.UserRole, r["id"])
            self.table.setItem(i, 0, title_item)

            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(r["due_ts"] or ""))

            prio = QtWidgets.QTableWidgetItem(r["priority"] or "Low")
            if r["priority"] == "High":
                prio.setBackground(QtGui.QColor("#3A1820"))
            elif r["priority"] == "Medium":
                prio.setBackground(QtGui.QColor("#2E2A1A"))
            else:
                prio.setBackground(QtGui.QColor("#1B2A1F"))
            self.table.setItem(i, 2, prio)

            status_item = QtWidgets.QTableWidgetItem("✅" if r["status"] else "⬜")
            self.table.setItem(i, 3, status_item)

            self.table.setItem(i, 4, QtWidgets.QTableWidgetItem(r["category"] or ""))

            btn = QtWidgets.QPushButton("Готово" if not r["status"] else "Повернути")
            btn.clicked.connect(lambda _, rid=r["id"], done=bool(r["status"]): self.flip(rid, done))
            self.table.setCellWidget(i, 5, btn)

            del_btn = QtWidgets.QPushButton("Видалити")
            del_btn.clicked.connect(lambda _, rid=r["id"]: self.remove_task(rid))
            self.table.setCellWidget(i, 6, del_btn)

    def flip(self, task_id, done_now: bool):
        self.db.toggle_task(task_id, not done_now)
        self.load_scope(self.scope)

    def remove_task(self, task_id: int):
        if QtWidgets.QMessageBox.question(self, "Підтвердження", f"Видалити завдання #{task_id}?") != QtWidgets.QMessageBox.Yes:
            return
        self.db.delete_task(task_id)
        self.load_scope(self.scope)

    def add_task(self):
        title = self.t_title.text().strip()
        if not title:
            QtWidgets.QMessageBox.warning(self, "Помилка", "Назва обов'язкова.")
            return
        d = self.t_date.date().toString("yyyy-MM-dd")
        t = self.t_time.time().toString("HH:mm")
        due_ts = f"{d} {t}:00"
        self.db.add_task(title, self.t_desc.text().strip(), due_ts, self.t_prio.currentText(), self.t_cat.text().strip() or None)
        self.t_title.clear(); self.t_desc.clear(); self.t_cat.clear()
        self.load_scope(self.scope)



class NotesPage(QtWidgets.QWidget):
    def __init__(self, db: DB):
        super().__init__()
        self.db = db
        v = QtWidgets.QVBoxLayout(self)
        header = QtWidgets.QLabel("📝 Нотатки"); header.setProperty("heading","h1"); v.addWidget(header)

        form = QtWidgets.QHBoxLayout()
        self.n_title = QtWidgets.QLineEdit(); self.n_title.setPlaceholderText("Заголовок")
        self.n_body = QtWidgets.QLineEdit(); self.n_body.setPlaceholderText("Текст нотатки")
        add = QtWidgets.QPushButton("Додати"); add.setObjectName("Primary")
        add.clicked.connect(self.add_note)
        form.addWidget(self.n_title); form.addWidget(self.n_body); form.addWidget(add)
        v.addLayout(form)

        self.list = QtWidgets.QTableWidget(0,3)
        self.list.setHorizontalHeaderLabels(["Заголовок","Текст",""])
        self.list.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.list)
        self.reload()

    def reload(self):
        rows = self.db.list_notes()
        self.list.setRowCount(len(rows))
        for i, r in enumerate(rows):
            self.list.setItem(i,0,QtWidgets.QTableWidgetItem(r["title"] or ""))
            self.list.setItem(i,1,QtWidgets.QTableWidgetItem(r["body"] or ""))
            btn = QtWidgets.QPushButton("🗑"); btn.setObjectName("Danger")
            btn.clicked.connect(lambda _, rid=r["id"]: self.remove(rid))
            self.list.setCellWidget(i,2,btn)

    def add_note(self):
        t = self.n_title.text().strip(); b = self.n_body.text().strip()
        if not t and not b:
            return
        self.db.add_note(t or "Без назви", b)
        self.n_title.clear(); self.n_body.clear()
        self.reload()

    def remove(self, rid):
        self.db.delete_note(rid)
        self.reload()


class StatsPage(QtWidgets.QWidget):
    def __init__(self, db: DB):
        super().__init__()
        self.db = db
        v = QtWidgets.QVBoxLayout(self)
        header = QtWidgets.QLabel("📈 Аналітика"); header.setProperty("heading","h1"); v.addWidget(header)

        self.canvas1 = MplCanvas()
        self.canvas2 = MplCanvas()
        v.addWidget(self.canvas1)
        v.addWidget(self.canvas2)

        btn = QtWidgets.QPushButton("Оновити"); btn.clicked.connect(self.reload)
        v.addWidget(btn)
        self.reload()

    def reload(self):
        # Tasks done per day (last 7 days)
        days = [(date.today()-timedelta(days=i)).isoformat() for i in range(6,-1,-1)]
        counts = []
        for d in days:
            c = self.db.cur.execute("SELECT COUNT(*) FROM tasks WHERE date(due_ts)=? AND status=1", (d,)).fetchone()[0]
            counts.append(c)
        self.canvas1.ax.clear()
        self.canvas1.ax.plot(range(7), counts, marker="o")
        self.canvas1.ax.set_xticks(range(7))
        self.canvas1.ax.set_xticklabels([d[5:] for d in days])
        self.canvas1.ax.set_title("Виконані задачі (ост. 7 днів)")
        self.canvas1.draw()

        # Expenses by category (last 30 days)
        start = (date.today()-timedelta(days=29)).isoformat()
        end = date.today().isoformat()
        rows = self.db.list_expenses(date_from=start, date_to=end)
        cats = defaultdict(float)
        for r in rows:
            cats[r["category"]] += r["amount"]
        self.canvas2.ax.clear()
        if cats:
            self.canvas2.ax.bar(list(cats.keys()), list(cats.values()))
            self.canvas2.ax.set_title("Витрати по категоріях (30 днів)")
            self.canvas2.ax.tick_params(axis='x', labelrotation=30)
        else:
            self.canvas2.ax.text(0.5,0.5,"Немає даних",ha="center",va="center")
        self.canvas2.draw()


class AIAssistantTab(QtWidgets.QWidget):
    def __init__(self, db: DB, parent=None):
        super().__init__(parent)
        self.db = db
        v = QtWidgets.QVBoxLayout(self)

        header = QtWidgets.QLabel("🤖 AI Assistant"); header.setProperty("heading","h1")
        v.addWidget(header)

        h = QtWidgets.QHBoxLayout()
        self.inp = QtWidgets.QLineEdit()
        self.inp.setPlaceholderText("Постав запит або попроси аналіз (напр. 'Аналіз моїх витрат за тиждень')")
        ask = QtWidgets.QPushButton("Надіслати"); ask.setObjectName("Primary")
        ask.clicked.connect(self.ask_ai)
        h.addWidget(self.inp,1); h.addWidget(ask)
        v.addLayout(h)

        self.out = QtWidgets.QPlainTextEdit(); self.out.setReadOnly(True)
        v.addWidget(self.out, 2)

        self.canvas = MplCanvas()
        v.addWidget(self.canvas, 2)

        # quick actions
        qa = QtWidgets.QHBoxLayout()
        btn_exp_analysis = QtWidgets.QPushButton("Аналіз витрат (7 днів)")
        btn_exp_analysis.clicked.connect(self.analyze_expenses)
        btn_task_suggest = QtWidgets.QPushButton("План задач на тиждень")
        btn_task_suggest.clicked.connect(self.plan_tasks)
        qa.addWidget(btn_exp_analysis); qa.addWidget(btn_task_suggest); qa.addStretch(1)
        v.addLayout(qa)

    def _deepseek(self, prompt: str) -> str:
        headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
        payload = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "Ти помічник у додатку LifeTracker. Відповідай коротко і по суті."},
                {"role": "user", "content": prompt}
            ],
            "max_tokens": 700,
            "temperature": 0.7
        }
        r = requests.post(DEEPSEEK_API_URL, json=payload, headers=headers, timeout=30)
        r.raise_for_status()
        data = r.json()
        return data["choices"][0]["message"]["content"].strip()

    def ask_ai(self):
        q = self.inp.text().strip()
        if not q: return
        self.out.appendPlainText(f"👉 {q}")
        try:
            ans = self._deepseek(q)
            self.out.appendPlainText(f"🤖 {ans}\n")
        except Exception as e:
            self.out.appendPlainText(f"❌ Помилка: {e}\n")

    def analyze_expenses(self):
        # build data summary and send to AI
        start = (date.today()-timedelta(days=6)).isoformat()
        end = date.today().isoformat()
        rows = self.db.list_expenses(date_from=start, date_to=end)
        if not rows:
            self.out.appendPlainText("Немає витрат за останній тиждень.\n")
            return
        cats = defaultdict(float)
        per_day = defaultdict(float)
        for r in rows:
            cats[r["category"]] += r["amount"]
            per_day[r["dt"]] += r["amount"]

        # plot per-day
        self.canvas.ax.clear()
        days = [ (date.today()-timedelta(days=i)).isoformat() for i in range(6,-1,-1) ]
        vals = [ per_day.get(d, 0.0) for d in days ]
        self.canvas.ax.plot(range(7), vals, marker="o")
        self.canvas.ax.set_xticks(range(7)); self.canvas.ax.set_xticklabels([d[5:] for d in days])
        self.canvas.ax.set_title("Витрати по днях (7 днів)")
        self.canvas.draw()

        summary = "Витрати за тиждень по категоріях:\n" + "\n".join(f"- {k}: {v:.2f} {EUR}" for k,v in cats.items())
        prompt = f"{summary}\nЗроби короткий висновок і 3 поради як знизити витрати наступного тижня."
        try:
            ans = self._deepseek(prompt)
            self.out.appendPlainText("🤖 " + ans + "\n")
        except Exception as e:
            self.out.appendPlainText(f"❌ Помилка AI: {e}\n")

    def plan_tasks(self):
        # summarize tasks next 7 days
        start = date.today()
        upcoming = self.db.cur.execute(
            "SELECT title, due_ts, priority, status FROM tasks WHERE date(due_ts) BETWEEN ? AND ? ORDER BY due_ts",
            (start.isoformat(), (start+timedelta(days=7)).isoformat())
        ).fetchall()
        if not upcoming:
            self.out.appendPlainText("Немає задач на найближчий тиждень.\n")
            return
        lines = []
        for r in upcoming:
            due = r["due_ts"] or ""
            lines.append(f"- {due} | {r['title']} | prio {r['priority']} | {'done' if r['status'] else 'open'}")
        prompt = "Сформуй стислий план на тиждень із цих задач, пріоритезуй і розпиши порядок:\n" + "\n".join(lines)
        try:
            ans = self._deepseek(prompt)
            self.out.appendPlainText("🤖 " + ans + "\n")
        except Exception as e:
            self.out.appendPlainText(f"❌ Помилка AI: {e}\n")


class SettingsPage(QtWidgets.QWidget):
    def __init__(self, db: DB):
        super().__init__()
        self.db = db
        v = QtWidgets.QVBoxLayout(self)
        header = QtWidgets.QLabel("⚙️ Налаштування"); header.setProperty("heading","h1")
        v.addWidget(header)

        exp = QtWidgets.QPushButton("Експорт всіх таблиць у Excel")
        exp.clicked.connect(self.export_all)
        v.addWidget(exp)

        clear_btn = QtWidgets.QPushButton("Очистити ВСІ дані (необоротно)")
        clear_btn.setObjectName("Danger")
        clear_btn.clicked.connect(self.clear_all)
        v.addWidget(clear_btn)

        v.addStretch(1)

    def export_all(self):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Зберегти Excel", "lifetracker_export.xlsx", "Excel (*.xlsx)")
        if not path: return
        with pd.ExcelWriter(path, engine="xlsxwriter") as writer:
            pd.DataFrame([dict(r) for r in self.db.cur.execute("SELECT * FROM tasks")]).to_excel(writer, index=False, sheet_name="tasks")
            pd.DataFrame([dict(r) for r in self.db.cur.execute("SELECT * FROM expenses")]).to_excel(writer, index=False, sheet_name="expenses")
            pd.DataFrame([dict(r) for r in self.db.cur.execute("SELECT * FROM notes")]).to_excel(writer, index=False, sheet_name="notes")
            pd.DataFrame([dict(r) for r in self.db.cur.execute("SELECT * FROM events")]).to_excel(writer, index=False, sheet_name="events")
        QtWidgets.QMessageBox.information(self, "Готово", f"Експортовано: {path}")

    def clear_all(self):
        if QtWidgets.QMessageBox.question(self, "Увага", "Точно видалити всі дані?") != QtWidgets.QMessageBox.Yes:
            return
        self.db.cur.execute("DELETE FROM tasks")
        self.db.cur.execute("DELETE FROM expenses")
        self.db.cur.execute("DELETE FROM notes")
        self.db.cur.execute("DELETE FROM events")
        self.db.conn.commit()
        QtWidgets.QMessageBox.information(self, "OK", "Видалено всі дані.")


# -------------------- MAIN WINDOW --------------------
class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.resize(1200, 750)
        self.db = DB(DB_PATH)

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        lay = QtWidgets.QHBoxLayout(central)

        self.sidebar = QtWidgets.QListWidget()
        self.sidebar.setObjectName("Sidebar")
        self.sidebar.setFixedWidth(210)
        lay.addWidget(self.sidebar)

        self.pages = QtWidgets.QStackedWidget()
        lay.addWidget(self.pages, 1)

        # Pages
        self.page_dashboard = DashboardPage(self.db)
        self._add_page("🏠 Dashboard", self.page_dashboard)

        self.page_expenses = ExpensesPage(self.db)
        self._add_page("💰 Expenses", self.page_expenses)

        self.page_calendar = EnhancedCalendar(self.db)
        self._add_page("📅 Calendar", self.page_calendar)

        self.page_tasks = TasksPage(self.db)
        self._add_page("✅ Tasks", self.page_tasks)

        self.page_notes = NotesPage(self.db)
        self._add_page("📝 Notes", self.page_notes)

        self.page_stats = StatsPage(self.db)
        self._add_page("📈 Stats", self.page_stats)
        
        self.page_analytics = AnalyticsPage(self.db)
        self._add_page("📊 Analytics", self.page_analytics)


        # Attachments page
        self.attach_manager = AttachmentManager(Path("data"))
        self.page_attachments = AttachmentsPage(self.attach_manager)
        self._add_page("📎 Attachments", self.page_attachments)

        self.page_settings = SettingsPage(self.db)
        self._add_page("⚙️ Settings", self.page_settings)


        # navigation
        self.sidebar.currentRowChanged.connect(self.pages.setCurrentIndex)
        self.sidebar.setCurrentRow(0)

    def _add_page(self, title: str, widget: QtWidgets.QWidget):
        self.sidebar.addItem(title)
        self.pages.addWidget(widget)
class AnalyticsPage(QtWidgets.QWidget):
    """
    Аналітика: Expenses / Tasks / Events / Cross.
    Фільтри: дата-від/дата-до, категорія (для витрат/задач).
    Таблиці: сортуються кліком по заголовку (setSortingEnabled).
    Графіки: через існуючий MplCanvas (як у тебе).
    """
    def __init__(self, db: DB):
        super().__init__()
        self.db = db
        v = QtWidgets.QVBoxLayout(self)

        header = QtWidgets.QLabel("📊 Analytics")
        header.setProperty("heading", "h1")
        v.addWidget(header)

        # -------- Filters --------
        filt = QtWidgets.QHBoxLayout()
        self.d_from = QtWidgets.QDateEdit(QtCore.QDate.currentDate().addMonths(-3))
        self.d_to   = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        for w in (self.d_from, self.d_to):
            w.setCalendarPopup(True); w.setDisplayFormat("yyyy-MM-dd")
        self.cat = QtWidgets.QComboBox(); self.cat.setEditable(False)
        self.cat.addItem("Усі категорії")
        for r in self.db.cur.execute("SELECT DISTINCT category FROM expenses WHERE category IS NOT NULL ORDER BY 1"):
            if r["category"]:
                self.cat.addItem(r["category"])
        self.refresh_btn = QtWidgets.QPushButton("Оновити")
        self.refresh_btn.clicked.connect(self.refresh_all)

        filt.addWidget(QtWidgets.QLabel("Від:")); filt.addWidget(self.d_from)
        filt.addWidget(QtWidgets.QLabel("До:"));  filt.addWidget(self.d_to)
        filt.addWidget(QtWidgets.QLabel("Категорія (₴):")); filt.addWidget(self.cat, 1)
        filt.addStretch(1); filt.addWidget(self.refresh_btn)
        v.addLayout(filt)

        # -------- Tabs --------
        self.tabs = QtWidgets.QTabWidget()
        v.addWidget(self.tabs, 1)

        # Expenses tab
        self.tab_exp = QtWidgets.QWidget(); tl = QtWidgets.QVBoxLayout(self.tab_exp)
        self.exp_canvas = MplCanvas(width=6, height=3, dpi=100)
        tl.addWidget(self.exp_canvas)
        self.tbl_exp = QtWidgets.QTableWidget(0, 5)
        self.tbl_exp.setHorizontalHeaderLabels(["Тип","Ключ","Значення 1","Значення 2","Коментар"])
        self.tbl_exp.setSortingEnabled(True)
        self.tbl_exp.horizontalHeader().setStretchLastSection(True)
        tl.addWidget(self.tbl_exp)
        self.tabs.addTab(self.tab_exp, "💰 Expenses")

        # Tasks tab
        self.tab_tasks = QtWidgets.QWidget(); tl2 = QtWidgets.QVBoxLayout(self.tab_tasks)
        self.tasks_canvas = MplCanvas(width=6, height=3, dpi=100)
        tl2.addWidget(self.tasks_canvas)
        self.tbl_tasks = QtWidgets.QTableWidget(0, 5)
        self.tbl_tasks.setHorizontalHeaderLabels(["Метрика","Ключ","Значення 1","Значення 2","Коментар"])
        self.tbl_tasks.setSortingEnabled(True)
        self.tbl_tasks.horizontalHeader().setStretchLastSection(True)
        tl2.addWidget(self.tbl_tasks)
        self.tabs.addTab(self.tab_tasks, "✅ Tasks")

        # Events tab
        self.tab_events = QtWidgets.QWidget(); tl3 = QtWidgets.QVBoxLayout(self.tab_events)
        self.events_canvas = MplCanvas(width=6, height=3, dpi=100)
        tl3.addWidget(self.events_canvas)
        self.tbl_events = QtWidgets.QTableWidget(0, 5)
        self.tbl_events.setHorizontalHeaderLabels(["Метрика","Ключ","Значення 1","Значення 2","Коментар"])
        self.tbl_events.setSortingEnabled(True)
        self.tbl_events.horizontalHeader().setStretchLastSection(True)
        tl3.addWidget(self.tbl_events)
        self.tabs.addTab(self.tab_events, "📅 Events")

        # Cross tab
        self.tab_cross = QtWidgets.QWidget(); tl4 = QtWidgets.QVBoxLayout(self.tab_cross)
        self.cross_canvas = MplCanvas(width=6, height=3, dpi=100)
        tl4.addWidget(self.cross_canvas)
        self.tbl_cross = QtWidgets.QTableWidget(0, 5)
        self.tbl_cross.setHorizontalHeaderLabels(["Метрика","Ключ","Значення 1","Значення 2","Коментар"])
        self.tbl_cross.setSortingEnabled(True)
        self.tbl_cross.horizontalHeader().setStretchLastSection(True)
        tl4.addWidget(self.tbl_cross)
        self.tabs.addTab(self.tab_cross, "🔗 Cross")

        self.refresh_all()

    # ---------- helpers ----------
    def _dates(self):
        return (self.d_from.date().toString("yyyy-MM-dd"), self.d_to.date().toString("yyyy-MM-dd"))

    def _cat_filter(self):
        c = self.cat.currentText().strip()
        return None if c == "Усі категорії" else c

    def _reset_table(self, tbl):
        tbl.setRowCount(0)

    def _add_row(self, tbl, arr):
        r = tbl.rowCount(); tbl.insertRow(r)
        for j, val in enumerate(arr[:tbl.columnCount()]):
            item = QtWidgets.QTableWidgetItem("" if val is None else str(val))
            tbl.setItem(r, j, item)

    # ---------- refresh ----------
    def refresh_all(self):
        self._exp_refresh()
        self._tasks_refresh()
        self._events_refresh()
        self._cross_refresh()

    # ---------- EXPENSES ----------
    def _exp_refresh(self):
        self._reset_table(self.tbl_exp)
        d1, d2 = self._dates()
        cat = self._cat_filter()

        # 1) Місячний burn-rate
        params = [d1, d2]
        q = "SELECT strftime('%Y-%m', dt) ym, SUM(amount) total FROM expenses WHERE date(dt) BETWEEN ? AND ?"
        if cat: q += " AND category=?"; params.append(cat)
        q += " GROUP BY ym ORDER BY ym"
        rows = self.db.cur.execute(q, params).fetchall()
        xs = [r["ym"] for r in rows]; ys = [float(r["total"] or 0) for r in rows]
        self.exp_canvas.figure.clear(); ax = self.exp_canvas.figure.add_subplot(111)
        ax.plot(xs, ys, marker="o"); ax.set_title("Місячний burn-rate"); ax.set_ylabel("Сума"); ax.set_xlabel("Місяць")
        ax.grid(True, alpha=0.3); self.exp_canvas.draw()
        for r in rows: self._add_row(self.tbl_exp, ["burn", r["ym"], f'{float(r["total"]):.2f}', "", ""])

        # 2) Структура за категоріями (%)
        params = [d1, d2]
        q = "SELECT category, SUM(amount) s FROM expenses WHERE date(dt) BETWEEN ? AND ?"
        if cat: q += " AND category=?"; params.append(cat)
        q += " GROUP BY category ORDER BY s DESC"
        rows = self.db.cur.execute(q, params).fetchall()
        total = sum(float(r["s"] or 0) for r in rows) or 1.0
        for r in rows:
            pct = 100.0 * float(r["s"] or 0) / total
            self._add_row(self.tbl_exp, ["cat_share", r["category"], f'{float(r["s"]):.2f}', f'{pct:.1f}%', ""])

        # 3) Топ-5 днів
        params = [d1, d2]
        q = "SELECT date(dt) d, SUM(amount) s FROM expenses WHERE date(dt) BETWEEN ? AND ?"
        if cat: q += " AND category=?"; params.append(cat)
        q += " GROUP BY d ORDER BY s DESC LIMIT 5"
        for r in self.db.cur.execute(q, params):
            self._add_row(self.tbl_exp, ["top_day", r["d"], f'{float(r["s"]):.2f}', "", ""])

        # 4) Аномалії (> μ+3σ по категоріях)
        q = """
        WITH c AS (
          SELECT category, AVG(amount) m, (AVG(amount*amount)-AVG(amount)*AVG(amount)) AS var
          FROM expenses
          WHERE date(dt) BETWEEN ? AND ?
          GROUP BY category
        )
        SELECT e.id, e.dt, e.category, e.amount, c.m, c.var
        FROM expenses e JOIN c ON e.category=c.category
        WHERE date(e.dt) BETWEEN ? AND ? AND e.amount > c.m + 3*sqrt(COALESCE(c.var,0))
        ORDER BY e.amount DESC
        """
        params = [d1, d2, d1, d2]
        if cat:
            q = q.replace("FROM expenses e JOIN c", "FROM expenses e JOIN c ON e.category=c.category AND e.category=?")
            params = [d1, d2, cat, d1, d2]
        for r in self.db.cur.execute(q, params):
            self._add_row(self.tbl_exp, ["anomaly", f'{r["dt"]} {r["category"]}', f'{float(r["amount"]):.2f}', f'μ={float(r["m"]):.2f}', "amount>μ+3σ"])

        # 5) День тижня (heat/сума)
        params = [d1, d2]
        q = "SELECT strftime('%w', dt) dow, SUM(amount) s FROM expenses WHERE date(dt) BETWEEN ? AND ?"
        if cat: q += " AND category=?"; params.append(cat)
        q += " GROUP BY dow ORDER BY dow"
        for r in self.db.cur.execute(q, params):
            self._add_row(self.tbl_exp, ["weekday", r["dow"], f'{float(r["s"]):.2f}', "", "0=Нд .. 6=Сб"])

        # 6) Повторювані платежі (категорія має >=3 місяці з близькою середньою)
        q = """
        SELECT category, strftime('%Y-%m', dt) ym, ROUND(AVG(amount),2) avg_amt, COUNT(*) n
        FROM expenses
        WHERE date(dt) BETWEEN ? AND ?
        GROUP BY category, ym
        ORDER BY category, ym
        """
        params = [d1, d2]
        if cat:
            q = q.replace("FROM expenses", "FROM expenses WHERE category=? AND date(dt) BETWEEN ? AND ?")
            params = [cat, d1, d2]
        agg = {}
        for r in self.db.cur.execute(q, params):
            agg.setdefault(r["category"], []).append((r["ym"], float(r["avg_amt"])))
        for ccat, seq in agg.items():
            if len(seq) >= 3:
                self._add_row(self.tbl_exp, ["repeat", ccat, f"{len(seq)} міс.", "", "стабільні щомісячні витрати?"])

    # ---------- TASKS ----------
    def _tasks_refresh(self):
        self._reset_table(self.tbl_tasks)
        d1, d2 = self._dates()
        # 1) Done rate by weeks (за created_at)
        q = """
        SELECT strftime('%Y-%W', created_at) wk,
               SUM(CASE WHEN status=1 THEN 1 ELSE 0 END)*1.0/COUNT(*) AS done_rate
        FROM tasks
        WHERE date(created_at) BETWEEN ? AND ?
        GROUP BY wk ORDER BY wk
        """
        rows = self.db.cur.execute(q, [d1, d2]).fetchall()
        xs = [r["wk"] for r in rows]; ys = [float(r["done_rate"] or 0) for r in rows]
        self.tasks_canvas.figure.clear(); ax = self.tasks_canvas.figure.add_subplot(111)
        ax.plot(xs, ys, marker="o"); ax.set_ylim(0,1); ax.set_title("Done rate (тижні)"); ax.grid(True, alpha=0.3)
        self.tasks_canvas.draw()
        for r in rows: self._add_row(self.tbl_tasks, ["done_rate", r["wk"], f'{float(r["done_rate"])*100:.1f}%', "", ""])

        # 2) On-time %
        q = """
        SELECT ROUND(100.0*AVG(CASE WHEN completed_at IS NOT NULL AND datetime(completed_at)<=datetime(COALESCE(due_ts, completed_at)) THEN 1 ELSE 0 END),1) AS pct
        FROM tasks
        WHERE completed_at IS NOT NULL AND date(completed_at) BETWEEN ? AND ?
        """
        pct = self.db.cur.execute(q, [d1, d2]).fetchone()["pct"]
        self._add_row(self.tbl_tasks, ["on_time", "вчасно", f'{pct or 0:.1f}%', "", ""])

        # 3) Avg delay (days)
        q = """
        SELECT AVG(julianday(completed_at)-julianday(due_ts)) AS avg_delay
        FROM tasks
        WHERE completed_at IS NOT NULL AND due_ts IS NOT NULL AND date(completed_at) BETWEEN ? AND ?
        """
        ad = self.db.cur.execute(q, [d1, d2]).fetchone()["avg_delay"]
        self._add_row(self.tbl_tasks, ["delay", "середня затримка", f'{(ad or 0):.2f}', "дні", ""])

        # 4) Backlog/Overdue зараз
        q = """
        SELECT
          SUM(CASE WHEN status=0 THEN 1 ELSE 0 END) AS open,
          SUM(CASE WHEN status=0 AND due_ts IS NOT NULL AND datetime(due_ts)<datetime('now') THEN 1 ELSE 0 END) AS overdue
        FROM tasks
        """
        row = self.db.cur.execute(q).fetchone()
        self._add_row(self.tbl_tasks, ["backlog", "open", row["open"] or 0, "", ""])
        self._add_row(self.tbl_tasks, ["backlog", "overdue", row["overdue"] or 0, "", ""])

        # 5) Priority distribution
        q = """
        SELECT priority,
               SUM(CASE WHEN status=1 THEN 1 ELSE 0 END) AS done,
               SUM(CASE WHEN status=0 THEN 1 ELSE 0 END) AS open
        FROM tasks GROUP BY priority
        """
        for r in self.db.cur.execute(q):
            self._add_row(self.tbl_tasks, ["priority", r["priority"], r["done"] or 0, r["open"] or 0, ""])

    # ---------- EVENTS ----------
    def _events_refresh(self):
        self._reset_table(self.tbl_events)
        d1, d2 = self._dates()
        # 1) Hours by hour
        q = """
        SELECT strftime('%H', start_ts) hour,
               SUM((julianday(COALESCE(end_ts,start_ts))-julianday(start_ts))*24) AS hours
        FROM events
        WHERE date(start_ts) BETWEEN ? AND ?
        GROUP BY hour ORDER BY hour
        """
        rows = self.db.cur.execute(q, [d1, d2]).fetchall()
        xs = [r["hour"] for r in rows]; ys = [float(r["hours"] or 0) for r in rows]
        self.events_canvas.figure.clear(); ax = self.events_canvas.figure.add_subplot(111)
        ax.bar(xs, ys); ax.set_title("Годинне навантаження"); ax.set_xlabel("Година"); ax.set_ylabel("Годин")
        self.events_canvas.draw()
        for r in rows: self._add_row(self.tbl_events, ["hours_by_hour", r["hour"], f'{float(r["hours"]):.2f}', "", ""])

        # 2) Weekly total
        q = """
        SELECT strftime('%Y-%W', start_ts) wk,
               SUM((julianday(COALESCE(end_ts,start_ts))-julianday(start_ts))*24) AS hours
        FROM events
        WHERE date(start_ts) BETWEEN ? AND ?
        GROUP BY wk ORDER BY wk
        """
        for r in self.db.cur.execute(q, [d1, d2]):
            self._add_row(self.tbl_events, ["week_total", r["wk"], f'{float(r["hours"]):.2f}', "", ""])

        # 3) Heavy days > N hours (N=5)
        N = 5
        q = """
        SELECT date(start_ts) d,
               SUM((julianday(COALESCE(end_ts,start_ts))-julianday(start_ts))*24) AS hours
        FROM events
        WHERE date(start_ts) BETWEEN ? AND ?
        GROUP BY d HAVING hours > ?
        ORDER BY hours DESC
        """
        for r in self.db.cur.execute(q, [d1, d2, N]):
            self._add_row(self.tbl_events, ["heavy_day", r["d"], f'{float(r["hours"]):.2f}', "", f'>{N} год/день'])

    # ---------- CROSS ----------
    def _cross_refresh(self):
        self._reset_table(self.tbl_cross)
        d1, d2 = self._dates()
        # hours vs spend (same-day)
        q_hours = """
        SELECT date(start_ts) d,
               SUM((julianday(COALESCE(end_ts,start_ts))-julianday(start_ts))*24) AS h
        FROM events
        WHERE date(start_ts) BETWEEN ? AND ?
        GROUP BY d
        """
        q_spend = """
        SELECT date(dt) d, SUM(amount) spend
        FROM expenses
        WHERE date(dt) BETWEEN ? AND ?
        GROUP BY d
        """
        H = {r["d"]: float(r["h"] or 0) for r in self.db.cur.execute(q_hours, [d1, d2]).fetchall()}
        S = {r["d"]: float(r["spend"] or 0) for r in self.db.cur.execute(q_spend, [d1, d2]).fetchall()}
        days = sorted(set(H.keys()) | set(S.keys()))
        xs = [H.get(d,0.0) for d in days]
        ys = [S.get(d,0.0) for d in days]

        # кореляція Пірсона (якщо >=2 точки)
        r = ""
        if len(days) >= 2:
            import math
            n = len(days)
            sx = sum(xs); sy = sum(ys)
            sxx = sum(x*x for x in xs); syy = sum(y*y for y in ys); sxy = sum(x*y for x,y in zip(xs,ys))
            denom = math.sqrt((n*sxx - sx*sx)*(n*syy - sy*sy)) or 0.0
            r = (n*sxy - sx*sy)/denom if denom else 0.0

        self.cross_canvas.figure.clear(); ax = self.cross_canvas.figure.add_subplot(111)
        ax.scatter(xs, ys); ax.set_xlabel("Години (події)"); ax.set_ylabel("Витрати")
        ax.set_title(f"Взаємозвʼязок годин і витрат (r={r:.2f})")
        self.cross_canvas.draw()

        for d in days:
            self._add_row(self.tbl_cross, ["hours_vs_spend", d, H.get(d,0.0), S.get(d,0.0), ""])


# -------------------- APP ENTRY --------------------
def main():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    apply_dark(app)

    win = MainWindow()
    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
