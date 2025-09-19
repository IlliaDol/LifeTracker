# -*- coding: utf-8 -*-
import os, sys
from PyQt5 import QtWidgets, QtCore
import main  # твій існуючий main.py
from ai_panel import AIAssistantTab

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STYLE_PATH = os.path.join(APP_DIR, "style.qss")

def apply_dark(app: QtWidgets.QApplication):
    # Жорстко темна тема
    if os.path.exists(STYLE_PATH):
        with open(STYLE_PATH, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
    pal = app.palette()
    pal.setColor(pal.Window, QtCore.Qt.black)
    pal.setColor(pal.Base, QtCore.Qt.black)
    pal.setColor(pal.Text, QtCore.Qt.white)
    app.setPalette(pal)

# Перевизначаємо main.apply_theme, щоб навіть із Settings завжди залишався дарк
def _force_apply_theme(_app=None):
    app = _app or QtWidgets.QApplication.instance()
    apply_dark(app)
main.apply_theme = _force_apply_theme  # monkey-patch

class EnhancedCalendarPage(main.CalendarPage):
    def __init__(self):
        super().__init__()
        root = self.layout()          # QHBoxLayout
        leftv = root.itemAt(0).layout()  # VBox із календарем

        # Панель вибору місяця/року
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
        today_btn.setObjectName("Primary")

        ctrl.addWidget(QtWidgets.QLabel("Місяць:"))
        ctrl.addWidget(self.month)
        ctrl.addWidget(QtWidgets.QLabel("Рік:"))
        ctrl.addWidget(self.year)
        ctrl.addStretch(1)
        ctrl.addWidget(today_btn)

        leftv.insertLayout(2, ctrl)

        # Прив’язка подій
        self.month.currentIndexChanged.connect(self._apply_month_year)
        self.year.valueChanged.connect(self._apply_month_year)
        today_btn.clicked.connect(self._go_today)

    def _apply_month_year(self):
        y = self.year.value()
        m = self.month.currentIndex() + 1
        qd = QtCore.QDate(y, m, 1)
        self.calendar.setCurrentPage(y, m)
        self.calendar.setSelectedDate(qd)
        self.reload_list()

    def _go_today(self):
        qd = QtCore.QDate.currentDate()
        self.month.setCurrentIndex(qd.month() - 1)
        self.year.setValue(qd.year())
        self.calendar.setSelectedDate(qd)
        self.calendar.showSelectedDate()
        self.reload_list()


def main_dark():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(main.APP_NAME)
    apply_dark(app)

    # PIN (якщо є)
    if hasattr(main, "pin_gate_or_ok") and not main.pin_gate_or_ok():
        return

    # спочатку створюємо вікно
    win = main.MainWindow()

    # замінюємо календар
    try:
        idx = win.pages.indexOf(win.page_calendar)
        new_cal = EnhancedCalendarPage()
        old = win.page_calendar
        win.pages.removeWidget(old)
        old.deleteLater()
        win.pages.insertWidget(idx, new_cal)
        win.page_calendar = new_cal
    except Exception:
        pass

    # додаємо AI вкладку
    try:
        ai_tab = AIAssistantTab(main, win)
        win.sidebar.addItem("🤖  AI")
        win.pages.addWidget(ai_tab)
    except Exception as e:
        print("AI tab error:", e)

    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main_dark()
