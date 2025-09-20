

from __future__ import annotations
from PyQt5 import QtWidgets, QtCore
from pathlib import Path
from typing import Optional
# В attachments_qt.py, найверхніші рядки:
try:
    from .attachments_core import AttachmentManager
except ImportError:
    import os, sys
    sys.path.append(os.path.dirname(__file__))
    from attachments_core import AttachmentManager


def qdate_to_str(qd: QtCore.QDate) -> str:
    return qd.toString("yyyy-MM-dd")

class AttachmentsWidget(QtWidgets.QWidget):
    def __init__(self, manager: AttachmentManager, parent=None):
        super().__init__(parent)
        self.manager = manager
        v = QtWidgets.QVBoxLayout(self)

        # Controls row
        ctrl = QtWidgets.QHBoxLayout()
        self.date = QtWidgets.QDateEdit(QtCore.QDate.currentDate())
        self.date.setCalendarPopup(True)
        ctrl.addWidget(QtWidgets.QLabel("Дата:"))
        ctrl.addWidget(self.date)
        ctrl.addStretch(1)

        self.btn_add = QtWidgets.QPushButton("➕ Додати")
        self.btn_open = QtWidgets.QPushButton("👁 Відкрити")
        self.btn_del = QtWidgets.QPushButton("🗑 Видалити")
        self.btn_folder = QtWidgets.QPushButton("📂 Папка")
        for b in (self.btn_add, self.btn_open, self.btn_del, self.btn_folder):
            ctrl.addWidget(b)
        v.addLayout(ctrl)

        # Table
        self.table = QtWidgets.QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["Файл","Розмір","Змінено"])
        hh = self.table.horizontalHeader()
        hh.setSectionResizeMode(0, QtWidgets.QHeaderView.Stretch)
        hh.setSectionResizeMode(1, QtWidgets.QHeaderView.ResizeToContents)
        hh.setSectionResizeMode(2, QtWidgets.QHeaderView.ResizeToContents)
        self.table.setSelectionBehavior(QtWidgets.QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QtWidgets.QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        v.addWidget(self.table)

        # Connections
        self.date.dateChanged.connect(self.reload)
        self.btn_add.clicked.connect(self._on_add)
        self.btn_open.clicked.connect(self._on_open)
        self.btn_del.clicked.connect(self._on_delete)
        self.btn_folder.clicked.connect(self._on_open_folder)
        self.table.doubleClicked.connect(self._on_open)
        self.reload()

    def set_date_str(self, s: str):
        y, m, d = [int(x) for x in s.split("-")]
        self.date.setDate(QtCore.QDate(y, m, d))

    def _current_date_str(self) -> str:
        return qdate_to_str(self.date.date())

    def _selected_name(self) -> Optional[str]:
        rows = self.table.selectionModel().selectedRows()
        if not rows: return None
        return self.table.item(rows[0].row(), 0).text()

    def reload(self):
        ds = self._current_date_str()
        items = self.manager.list_files(ds)
        self.table.setRowCount(0)
        for it in items:
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QtWidgets.QTableWidgetItem(it["name"]))
            self.table.setItem(r, 1, QtWidgets.QTableWidgetItem(it["size_h"]))
            self.table.setItem(r, 2, QtWidgets.QTableWidgetItem(it["mtime"]))

    def _on_add(self):
        ds = self._current_date_str()
        paths, _ = QtWidgets.QFileDialog.getOpenFileNames(self, "Оберіть файли")
        if not paths: return
        self.manager.add_files(ds, paths)
        self.reload()

    def _on_open(self):
        ds = self._current_date_str()
        name = self._selected_name()
        if not name: return
        p = self.manager.attachments_dir(ds) / name
        if p.exists():
            self.manager.open_file(str(p))

    def _on_delete(self):
        ds = self._current_date_str()
        name = self._selected_name()
        if not name: return
        ret = QtWidgets.QMessageBox.question(self, "Підтвердження", f"Видалити '{name}'?")
        if ret != QtWidgets.QMessageBox.Yes: return
        self.manager.delete_file(ds, name)
        self.reload()

    def _on_open_folder(self):
        ds = self._current_date_str()
        self.manager.open_date_folder(ds)

class AttachmentsPage(QtWidgets.QWidget):
    def __init__(self, manager: AttachmentManager, parent=None):
        super().__init__(parent)
        v = QtWidgets.QVBoxLayout(self)
        header = QtWidgets.QLabel("📎 Вкладення")
        header.setProperty("heading", "h1")
        v.addWidget(header)
        self.widget = AttachmentsWidget(manager, self)
        v.addWidget(self.widget, 1)

    def set_date_str(self, s: str):
        self.widget.set_date_str(s)
