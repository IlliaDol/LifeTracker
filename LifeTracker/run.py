# run.py — запуск одним файлом
import os, sys
BASE = os.path.dirname(__file__)
sys.path.insert(0, BASE)  # щоб імпортувався пакет LifeTracker

from LifeTracker.main import main  # твоя функція main() вже є в main.py
if __name__ == "__main__":
    main()
