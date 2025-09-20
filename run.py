import os, sys
from importlib import import_module

BASE = os.path.dirname(__file__)
sys.path.insert(0, BASE)  # щоб імпортувався пакет LifeTracker

if __name__ == "__main__":
    app = import_module("LifeTracker.main")
    if hasattr(app, "main"):
        app.main()            # викликаємо main() з LifeTracker/main.py
    else:
        import runpy
        runpy.run_module("LifeTracker.main", run_name="__main__")
