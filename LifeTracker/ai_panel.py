import requests
import config  # <--- імпортуємо твій ключ
from PyQt5 import QtWidgets
import os

class AIAssistantTab(QtWidgets.QWidget):
    ...
    def query_deepseek(self, prompt: str) -> str:
        """Запит до DeepSeek API"""
        api_key = config.DEEPSEEK_API_KEY
        if not api_key:
            raise RuntimeError("У config.py не знайдено ключ!")

        url = "https://api.deepseek.com/v1/chat/completions"
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "deepseek-chat",
            "messages": [
                {"role": "system", "content": "Ти асистент у додатку LifeTracker."},
                {"role": "user", "content": prompt}
            ],
            "temperature": 0.7
        }

        r = requests.post(url, headers=headers, json=data, timeout=30)
        if r.status_code != 200:
            raise RuntimeError(f"DeepSeek API error {r.status_code}: {r.text}")

        resp = r.json()
        return resp["choices"][0]["message"]["content"].strip()
