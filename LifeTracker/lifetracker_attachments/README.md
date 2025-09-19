# LifeTracker Attachments Module

Додає універсальні вкладення (файли) **для будь‑якої дати**: додавання, перегляд, відкриття папки, видалення.
Зберігати файли буде в папці:  
`DATA_DIR/YYYY-MM-DD/_files/`

## 1) Встановлення
1. Скопіюйте папку `lifetracker_attachments/` у корінь вашого проєкту.
2. Переконайтесь, що у вашому коді є шлях до теки з даними (`DATA_DIR`). Якщо ні — створіть:
   ```python
   from pathlib import Path
   DATA_DIR = Path("data")  # або ваш шлях
   DATA_DIR.mkdir(parents=True, exist_ok=True)
   ```

## 2) Ініціалізація в `main.py`
```python
from pathlib import Path
import tkinter as tk
from lifetracker_attachments.attachments import AttachmentManager
from lifetracker_attachments.attachments_ui import AttachmentsFrame

# 1) Спільна тека з даними
DATA_DIR = Path("data")  # замініть на вашу
manager = AttachmentManager(DATA_DIR)

# 2) Спільна змінна з вибраною датою (формат YYYY-MM-DD)
selected_date_var = tk.StringVar(value="2025-09-20")  # у вас ця змінна вже має оновлюватись календарем
# !!! Важливо: прив'яжіть ваш календар/журнал так, щоб selected_date_var.set("YYYY-MM-DD") викликався при зміні дати

# 3) Створіть віджет у потрібному місці (frame/tab/pane)
attachments_frame = AttachmentsFrame(parent_frame, manager, selected_date_var)
attachments_frame.pack(fill="both", expand=True)
```

## 3) Як це працює
- Кнопка **"➕ Додати"** відкриває діалог вибору файлів і копіює їх у `DATA_DIR/<дата>/_files/`.
- Подвійний клік/кнопка **"👁 Відкрити"** відкриває файл стандартною програмою ОС.
- **"📂 Папка"** відкриває теку з файлами на диску.
- **"🗑 Видалити"** прибирає файл з диска.
- **Гарячі клавіші**: `Ctrl+Shift+A` — додати, `Delete` — видалити, подвійний клік — відкрити.
- Контекстне меню по правому кліку.
- Файли автоматично перейменовуються, якщо вже є такий самий (додається суфікс " (1)", " (2)", ...).

## 4) Інтеграція зі своїм календарем/журналом
- У місці, де у вас змінюється обрана дата, викликайте `selected_date_var.set("YYYY-MM-DD")`.
- `AttachmentsFrame` автоматично перезавантажиться при зміні змінної.

## 5) API для розробки (необов'язково)
```python
manager.add_files("2025-09-20", ["C:/temp/a.pdf", "/home/me/pic.png"])
manager.list_files("2025-09-20")
manager.delete_file("2025-09-20", "a.pdf")
manager.open_date_folder("2025-09-20")
```

## 6) Зв'язок з тасками (опційно)
Якщо треба вкладення **до конкретного завдання**, радимо підпапки `DATA_DIR/YYYY-MM-DD/_files/<task_id>/`. 
Це можна легко додати, створивши окремий менеджер з параметром `task_id` та прокидуючи його у `AttachmentsFrame`.

---

**Все на стандартній бібліотеці Python. Працює на Windows/macOS/Linux.**
Якщо потрібні патчі під ваш `main.py` — киньте його сюди, піджену інтеграцію за вас.
```