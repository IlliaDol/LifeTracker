# -*- coding: utf-8 -*-
from PyQt5 import QtWidgets, QtCore
import requests
import matplotlib.pyplot as plt
from io import BytesIO
from PIL import Image
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas

DEEPSEEK_API_KEY = "sk-12e5757a37f44dac829d92d4a03f8722"
DEEPSEEK_API_URL = "https://api.deepseek.com/v1/chat/completions"


class AIAssistantTab(QtWidgets.QWidget):
    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db

        layout = QtWidgets.QVBoxLayout(self)

        # Поле для введення
        self.input = QtWidgets.QTextEdit()
        self.input.setPlaceholderText("Введи своє завдання для ШІ...")
        layout.addWidget(self.input)

        # Кнопки
        btn_layout = QtWidgets.QHBoxLayout()
        self.ask_btn = QtWidgets.QPushButton("🤖 Запитати ШІ")
        self.graph_btn = QtWidgets.QPushButton("📊 Побудувати графік")
        btn_layout.addWidget(self.ask_btn)
        btn_layout.addWidget(self.graph_btn)
        layout.addLayout(btn_layout)

        # Вивід результатів
        self.output = QtWidgets.QTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output)

        # Місце для графіка
        self.canvas = None
        self.graph_area = QtWidgets.QVBoxLayout()
        layout.addLayout(self.graph_area)

        # Події
        self.ask_btn.clicked.connect(self.ask_ai)
        self.graph_btn.clicked.connect(self.show_graph)

    def ask_ai(self):
        text = self.input.toPlainText().strip()
        if not text:
            return
        self.output.setText("⏳ Чекай, думаю...")

        try:
            headers = {"Authorization": f"Bearer {DEEPSEEK_API_KEY}"}
            payload = {
                "model": "deepseek-chat",
                "messages": [{"role": "user", "content": text}],
                "max_tokens": 500
            }
            r = requests.post(DEEPSEEK_API_URL, json=payload, headers=headers, timeout=30)
            r.raise_for_status()
            data = r.json()
            answer = data["choices"][0]["message"]["content"]
            self.output.setText(answer)
        except Exception as e:
            self.output.setText(f"❌ Помилка: {e}")

    def show_graph(self):
        """Проста демка графіка"""
        if self.canvas:
            self.graph_area.removeWidget(self.canvas)
            self.canvas.deleteLater()

        fig, ax = plt.subplots()
        ax.plot([1, 2, 3, 4], [2, 5, 3, 7], marker="o")
        ax.set_title("Демо графік")
        ax.set_xlabel("X")
        ax.set_ylabel("Y")

        self.canvas = FigureCanvas(fig)
        self.graph_area.addWidget(self.canvas)
        self.canvas.draw()
