from __future__ import annotations
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
from pathlib import Path
from typing import Optional, Callable
from .attachments import AttachmentManager

class AttachmentsFrame(ttk.Frame):
    """
    Reusable attachments panel for a selected date.
    Pass in a shared tk.StringVar 'date_var' that always contains the selected date 'YYYY-MM-DD'.
    """

    def __init__(self, master, manager: AttachmentManager, date_var: tk.StringVar, *args, **kwargs):
        super().__init__(master, *args, **kwargs)
        self.manager = manager
        self.date_var = date_var

        # Toolbar
        bar = ttk.Frame(self)
        bar.pack(fill="x", padx=6, pady=6)
        self.btn_add = ttk.Button(bar, text="➕ Додати", command=self._on_add)
        self.btn_open = ttk.Button(bar, text="👁 Відкрити", command=self._on_open)
        self.btn_del = ttk.Button(bar, text="🗑 Видалити", command=self._on_delete)
        self.btn_folder = ttk.Button(bar, text="📂 Папка", command=self._on_open_folder)
        for w in (self.btn_add, self.btn_open, self.btn_del, self.btn_folder):
            w.pack(side="left", padx=(0, 6))

        # Table
        cols = ("name", "size", "mtime")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", selectmode="browse")
        self.tree.heading("name", text="Файл")
        self.tree.heading("size", text="Розмір")
        self.tree.heading("mtime", text="Змінено")
        self.tree.column("name", width=360, anchor="w")
        self.tree.column("size", width=90, anchor="center")
        self.tree.column("mtime", width=140, anchor="center")
        self.tree.pack(fill="both", expand=True, padx=6, pady=(0,6))

        # Scrollbar
        yscroll = ttk.Scrollbar(self, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=yscroll.set)
        yscroll.place(relx=1.0, rely=0, relheight=1.0, anchor="ne")

        # Context menu
        self.menu = tk.Menu(self, tearoff=0)
        self.menu.add_command(label="Відкрити", command=self._on_open)
        self.menu.add_command(label="Показати папку", command=self._on_open_folder)
        self.menu.add_separator()
        self.menu.add_command(label="Видалити", command=self._on_delete)

        self.tree.bind("<Button-3>", self._popup_menu)  # Right click
        self.tree.bind("<Double-1>", lambda e: self._on_open())
        self.tree.bind("<Delete>", lambda e: self._on_delete())
        self.bind_all("<Control-Shift-A>", lambda e: self._on_add())

        # React to date changes
        self.date_var.trace_add("write", lambda *args: self.refresh())
        self.refresh()

    # ---------------
    # Public methods
    # ---------------
    def refresh(self):
        date = self.date_var.get().strip()
        for i in self.tree.get_children():
            self.tree.delete(i)
        if not date:
            return
        for item in self.manager.list_files(date):
            self.tree.insert("", "end", iid=item["name"], values=(item["name"], item["size_h"], item["mtime"]))

    # ---------------
    # UI callbacks
    # ---------------
    def _selection(self) -> Optional[str]:
        sel = self.tree.selection()
        return sel[0] if sel else None

    def _on_add(self):
        date = self.date_var.get().strip()
        if not date:
            messagebox.showwarning("Немає дати", "Спочатку оберіть дату в календарі/журналі.")
            return
        paths = filedialog.askopenfilenames(title="Оберіть файли для прикріплення")
        if not paths:
            return
        self.manager.add_files(date, paths)
        self.refresh()

    def _on_open(self):
        date = self.date_var.get().strip()
        name = self._selection()
        if not date or not name:
            return
        path = self.manager.attachments_dir(date) / name
        if path.exists():
            self.manager.open_file(path)
        else:
            messagebox.showerror("Помилка", "Файл не знайдено на диску.")
            self.refresh()

    def _on_delete(self):
        date = self.date_var.get().strip()
        name = self._selection()
        if not date or not name:
            return
        if not messagebox.askyesno("Підтвердження", f"Видалити '{name}'?"):
            return
        ok = self.manager.delete_file(date, name)
        if not ok:
            messagebox.showerror("Помилка", "Не вдалося видалити файл.")
        self.refresh()

    def _on_open_folder(self):
        date = self.date_var.get().strip()
        if not date:
            return
        self.manager.open_date_folder(date)

    def _popup_menu(self, event):
        try:
            row = self.tree.identify_row(event.y)
            if row:
                self.tree.selection_set(row)
            self.menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.menu.grab_release()