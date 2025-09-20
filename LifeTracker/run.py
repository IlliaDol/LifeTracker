# run.py (клади у: C:\Users\thinkbook\Desktop\IDEAS\LifeTracker\run.py)
import os, sys

BASE = os.path.abspath(os.path.dirname(__file__))
PKG_DIR = os.path.join(BASE, "LifeTracker")

# 1) Переконайся, що пакет є у sys.path
if BASE not in sys.path:
    sys.path.insert(0, BASE)

# 2) Перевір наявність каталогу пакета
if not os.path.isdir(PKG_DIR):
    raise SystemExit(f"Не знайдено папку 'LifeTracker' за шляхом: {PKG_DIR}")

# 3) Імпортуй і запусти
try:
    from LifeTracker.main import main
except Exception as e:
    raise SystemExit(f"Не можу імпортувати LifeTracker.main: {e}")

if __name__ == "__main__":
    main()
