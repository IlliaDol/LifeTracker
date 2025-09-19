# -*- coding: utf-8 -*-
import os
import sys
from PyQt5 import QtWidgets, QtCore
import main  # основне вікно і база
from ai_panel import AIAssistantTab

APP_DIR = os.path.dirname(os.path.abspath(__file__))
STYLE_PATH = os.path.join(APP_DIR, "style.qss")


def apply_dark(app: QtWidgets.QApplication):
    if os.path.exists(STYLE_PATH):
        with open(STYLE_PATH, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())
    pal = app.palette()
    pal.setColor(pal.Window, QtCore.Qt.black)
    pal.setColor(pal.Base, QtCore.Qt.black)
    pal.setColor(pal.Text, QtCore.Qt.white)
    app.setPalette(pal)


class EnhancedCalendar(QtWidgets.QWidget):
    """Календар з вибором місяця і року"""
    def __init__(self, parent=None):
        super().__init__(parent)

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

        # Події
        self.month.currentIndexChanged.connect(self._apply_month_year)
        self.year.valueChanged.connect(self._apply_month_year)
        today_btn.clicked.connect(self._go_today)

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


def main_dark():
    app = QtWidgets.QApplication(sys.argv)
    app.setApplicationName(main.APP_NAME)
    apply_dark(app)

    if hasattr(main, "pin_gate_or_ok") and not main.pin_gate_or_ok():
        return

    # головне вікно
    win = main.MainWindow()

    # додаємо календар як окрему сторінку
    cal_page = EnhancedCalendar()
    win.sidebar.addItem("📅 Календар")
    win.pages.addWidget(cal_page)

    # додаємо AI вкладку
    try:
        ai_tab = AIAssistantTab(win.db, win)
        win.sidebar.addItem("🤖 AI")
        win.pages.addWidget(ai_tab)
    except Exception as e:
        print("AI tab error:", e)

    win.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main_dark()
