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


# --- Third-party ---
import requests
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


# -------------------- DB LAYER --------------------
class DB:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.row_factory = sqlite3.Row
        self.cur = self.conn.cursor()
        self._migrate()

    def _migrate(self):
        # tasks
        self.cur.execute("""
        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            description TEXT,
            due_ts TEXT,                 -- ISO datetime
            priority TEXT DEFAULT 'Low', -- Low/Medium/High
            status INTEGER DEFAULT 0,    -- 0=open,1=done
            category TEXT,
            tags TEXT,
            created_at TEXT
        )""")
        # expenses
        self.cur.execute("""
        CREATE TABLE IF NOT EXISTS expenses(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            dt TEXT,                 -- ISO date
            category TEXT,
            amount REAL NOT NULL,
            note TEXT,
            created_at TEXT
        )""")
        # notes
        self.cur.execute("""
        CREATE TABLE IF NOT EXISTS notes(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT,
            body TEXT,
            created_at TEXT
        )""")
        # events (calendar)
        self.cur.execute("""
        CREATE TABLE IF NOT EXISTS events(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            start_ts TEXT,   -- ISO datetime
            end_ts TEXT,
            location TEXT,
            description TEXT,
            remind_minutes INTEGER,
            created_at TEXT
        )""")
        self.conn.commit()

    # ---- tasks ----
    def add_task(self, title, description, due_ts, priority, category=None, tags=None):
        self.cur.execute("""
            INSERT INTO tasks(title, description, due_ts, priority, status, category, tags, created_at)
            VALUES (?,?,?,?,0,?,?,?)
        """, (title, description, due_ts, priority, category, tags, datetime.now().isoformat()))
        self.conn.commit()

    def list_tasks(self, scope="all"):
        q = "SELECT * FROM tasks"
        params = ()
        now = datetime.now()
        today = now.date().isoformat()
        if scope == "today":
            q += " WHERE date(due_ts)=?"
            params = (today,)
        elif scope == "week":
            start = (now - timedelta(days=now.weekday())).date().isoformat()
            end = (now + timedelta(days=(6 - now.weekday()))).date().isoformat()
            q += " WHERE date(due_ts) BETWEEN ? AND ?"
            params = (start, end)
        q += " ORDER BY due_ts IS NULL, due_ts ASC"
        return self.cur.execute(q, params).fetchall()

    def toggle_task(self, task_id: int, done: bool):
        self.cur.execute("UPDATE tasks SET status=? WHERE id=?", (1 if done else 0, task_id))
        self.conn.commit()

    def delete_task(self, task_id: int):
        self.cur.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        self.conn.commit()

    # ---- expenses ----
    def add_expense(self, dt, category, amount, note):
        self.cur.execute("""
            INSERT INTO expenses(dt, category, amount, note, created_at)
            VALUES (?,?,?,?,?)
        """, (dt, category, float(amount), note, datetime.now().isoformat()))
        self.conn.commit()

    def list_expenses(self, start=None, end=None):
        if start and end:
            return self.cur.execute(
                "SELECT * FROM expenses WHERE date(dt) BETWEEN ? AND ? ORDER BY dt DESC", (start, end)
            ).fetchall()
        return self.cur.execute("SELECT * FROM expenses ORDER BY dt DESC").fetchall()

    def delete_expense(self, expense_id: int):
        self.cur.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
        self.conn.commit()

    # ---- notes ----
    def add_note(self, title, body):
        self.cur.execute("INSERT INTO notes(title, body, created_at) VALUES (?,?,?)",
                         (title, body, datetime.now().isoformat()))
        self.conn.commit()

    def list_notes(self):
        return self.cur.execute("SELECT * FROM notes ORDER BY created_at DESC").fetchall()

    def delete_note(self, note_id: int):
        self.cur.execute("DELETE FROM notes WHERE id=?", (note_id,))
        self.conn.commit()

    # ---- events ----
    def add_event(self, title, start_ts, end_ts=None, location=None, description=None, remind_minutes=None):
        self.cur.execute("""
            INSERT INTO events(title, start_ts, end_ts, location, description, remind_minutes, created_at)
            VALUES (?,?,?,?,?,?,?)
        """, (title, start_ts, end_ts, location, description, remind_minutes, datetime.now().isoformat()))
        self.conn.commit()

    def list_events_for_date(self, y, m, d):
        theday = date(y, m, d).isoformat()
        return self.cur.execute(
            "SELECT * FROM events WHERE date(start_ts)=? ORDER BY start_ts",
            (theday,)
        ).fetchall()

    def list_events_range(self, start_date_iso, end_date_iso):
        return self.cur.execute(
            "SELECT * FROM events WHERE date(start_ts) BETWEEN ? AND ? ORDER BY start_ts",
            (start_date_iso, end_date_iso)
        ).fetchall()


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
        rows = self.db.list_expenses(start, end)
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
    def __init__(self, db: DB):
        super().__init__()
        self.db = db
        v = QtWidgets.QVBoxLayout(self)

        header = QtWidgets.QLabel("💰 Витрати")
        header.setProperty("heading", "h1")
        v.addWidget(header)

        form = QtWidgets.QHBoxLayout()
        self.dt = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        self.dt.setCalendarPopup(True)
        self.cat = QtWidgets.QComboBox()
        self.cat.setEditable(True)
        self.cat.addItems(["Продукти", "Транспорт", "Розваги", "Комуналка", "Інше"])
        self.amount = QtWidgets.QDoubleSpinBox()
        self.amount.setMaximum(10**9); self.amount.setDecimals(2); self.amount.setValue(0.0)
        self.note = QtWidgets.QLineEdit()
        add = QtWidgets.QPushButton("Додати"); add.setObjectName("Primary")
        add.clicked.connect(self.add_expense)

        form.addWidget(self.dt); form.addWidget(self.cat); form.addWidget(self.amount); form.addWidget(self.note); form.addWidget(add)
        v.addLayout(form)

        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Назва","Крайній термін","Пріор.","Статус","Категорія","Дія","🗑"])
        self.table.horizontalHeader().setStretchLastSection(True)
        v.addWidget(self.table)


        # Summary + chart
        sumlay = QtWidgets.QHBoxLayout()
        self.total_lbl = QtWidgets.QLabel("Разом: 0.00 " + EUR)
        sumlay.addWidget(self.total_lbl); sumlay.addStretch(1)

        btn_export_xlsx = QtWidgets.QPushButton("Експорт в Excel")
        btn_export_xlsx.clicked.connect(self.export_excel)
        btn_export_pdf = QtWidgets.QPushButton("Експорт в PDF")
        btn_export_pdf.clicked.connect(self.export_pdf)
        sumlay.addWidget(btn_export_xlsx); sumlay.addWidget(btn_export_pdf)
        v.addLayout(sumlay)

        self.canvas = MplCanvas()
        v.addWidget(self.canvas)

        self.reload()

    def add_expense(self):
        dt = self.dt.date().toString("yyyy-MM-dd")
        cat = self.cat.currentText().strip() or "Інше"
        amt = self.amount.value()
        note = self.note.text().strip()
        if amt <= 0:
            QtWidgets.QMessageBox.warning(self, "Помилка", "Сума має бути > 0")
            return
        self.db.add_expense(dt, cat, amt, note)
        self.note.clear(); self.amount.setValue(0.0)
        self.reload()

    def export_excel(self):
        rows = self.db.list_expenses()
        if not rows:
            QtWidgets.QMessageBox.information(self, "Експорт", "Немає даних для експорту.")
            return
        df = pd.DataFrame([dict(r) for r in rows])
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Зберегти Excel", "expenses.xlsx", "Excel (*.xlsx)")
        if not path: return
        df.to_excel(path, index=False)
        QtWidgets.QMessageBox.information(self, "Готово", f"Збережено: {path}")

    def export_pdf(self):
        rows = self.db.list_expenses()
        if not rows:
            QtWidgets.QMessageBox.information(self, "Експорт", "Немає даних для експорту.")
            return
        path, _ = QtWidgets.QFileDialog.getSaveFileName(self, "Зберегти PDF", "expenses.pdf", "PDF (*.pdf)")
        if not path: return
        c = pdfcanvas.Canvas(path, pagesize=A4)
        w, h = A4
        y = h - 40
        c.setFont("Helvetica-Bold", 14)
        c.drawString(40, y, "Expenses Report"); y -= 20
        c.setFont("Helvetica", 10)
        for r in rows:
            line = f"{r['dt']}  |  {r['category']:<12}  |  {r['amount']:>8.2f}  |  {r['note'] or ''}"
            c.drawString(40, y, line)
            y -= 14
            if y < 50:
                c.showPage(); y = h - 40
        c.save()
        QtWidgets.QMessageBox.information(self, "Готово", f"Збережено: {path}")

    def reload(self):
        rows = self.db.list_expenses()
        self.table.setRowCount(len(rows))
        total = 0.0
        cats = defaultdict(float)
        for i, r in enumerate(rows):
            total += r["amount"]; cats[r["category"]] += r["amount"]
            self.table.setItem(i, 0, QtWidgets.QTableWidgetItem(r["dt"]))
            self.table.setItem(i, 1, QtWidgets.QTableWidgetItem(r["category"]))
            self.table.setItem(i, 2, QtWidgets.QTableWidgetItem(f"{r['amount']:.2f} {EUR}"))
            self.table.setItem(i, 3, QtWidgets.QTableWidgetItem(r["note"] or ""))
            btn = QtWidgets.QPushButton("🗑")
            btn.setObjectName("Danger")
            btn.clicked.connect(lambda _, rid=r["id"]: self.remove(rid))
            self.table.setCellWidget(i, 4, btn)
        self.total_lbl.setText(f"Разом: {total:.2f} {EUR}")

        self.canvas.ax.clear()
        if cats:
            self.canvas.ax.pie(cats.values(), labels=cats.keys(), autopct="%1.1f%%")
            self.canvas.ax.set_title("Витрати по категоріях")
        else:
            self.canvas.ax.text(0.5, 0.5, "Немає даних", ha="center", va="center")
        self.canvas.draw()

    def remove(self, expense_id):
        self.db.delete_expense(expense_id)
        self.reload()


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
        self.month.addItems([
            "Січ", "Лют", "Бер", "Кві", "Тра", "Чер",
            "Лип", "Сер", "Вер", "Жов", "Лис", "Гру"
        ])
        self.year = QtWidgets.QSpinBox()
        self.year.setRange(1900, 2100)

        qd = QtCore.QDate.currentDate()
        self.month.setCurrentIndex(qd.month() - 1)
        self.year.setValue(qd.year())

        today_btn = QtWidgets.QPushButton("Сьогодні")

        ctrl.addWidget(QtWidgets.QLabel("Місяць:"))
        ctrl.addWidget(self.month)
        ctrl.addWidget(QtWidgets.QLabel("Рік:"))
        ctrl.addWidget(self.year)
        ctrl.addStretch(1)
        ctrl.addWidget(today_btn)
        layout.addLayout(ctrl)

        # Сам календар
        self.calendar = QtWidgets.QCalendarWidget()
        self.calendar.setGridVisible(True)
        layout.addWidget(self.calendar)

        # Список завдань під календарем
        self.task_list = QtWidgets.QListWidget()
        layout.addWidget(self.task_list)

        btn_layout = QtWidgets.QHBoxLayout()
        self.add_task_btn = QtWidgets.QPushButton("Додати завдання")
        self.del_task_btn = QtWidgets.QPushButton("Видалити завдання")
        btn_layout.addWidget(self.add_task_btn)
        btn_layout.addWidget(self.del_task_btn)
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
        y = self.year.value()
        m = self.month.currentIndex() + 1
        self.calendar.setCurrentPage(y, m)

    def _go_today(self):
        qd = QtCore.QDate.currentDate()
        self.month.setCurrentIndex(qd.month() - 1)
        self.year.setValue(qd.year())
        self.calendar.setSelectedDate(qd)
        self.calendar.showSelectedDate()
        self.load_tasks_for_day()

    def _selected_iso_date(self):
        """Повертає вибрану дату у форматі YYYY-MM-DD"""
        return self.calendar.selectedDate().toString("yyyy-MM-dd")

    def load_tasks_for_day(self):
        """Підтягуємо завдання для обраного дня."""
        self.task_list.clear()
        d = self._selected_iso_date()
        try:
            rows = self.db.cur.execute(
                "SELECT id, title FROM tasks WHERE due_date=?", (d,)
            ).fetchall()
            for r in rows:
                self.task_list.addItem(f"{r[0]} | {r[1]}")
        except sqlite3.OperationalError:
            # Якщо нема колонки — створимо
            self.db.cur.execute("ALTER TABLE tasks ADD COLUMN due_date TEXT")
            self.db.conn.commit()

    def add_task(self):
        d = self._selected_iso_date()
        title, ok = QtWidgets.QInputDialog.getText(self, "Нове завдання", "Назва:")
        if ok and title:
            self.db.cur.execute("INSERT INTO tasks (title, due_date, priority) VALUES (?, ?, ?)",
                                (title, d, "середній"))
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
        rows = self.db.list_expenses(start, end)
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
        rows = self.db.list_expenses(start, end)
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
        with pd.ExcelWriter(path) as writer:
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
