from __future__ import annotations
import os
import shutil
import subprocess
from pathlib import Path
from typing import Iterable, List, Dict, Optional
import time
import sys

# =============
# File helpers
# =============

def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def _slug_date(date_str: str) -> str:
    """Very permissive: keeps digits and dashes; replaces others with '_'."""
    return "".join(ch if (ch.isdigit() or ch == "-") else "_" for ch in date_str.strip())

def _unique_dest(dest_dir: Path, filename: str) -> Path:
    """
    Return a unique path inside dest_dir for filename.
    If 'name.ext' exists, try 'name (1).ext', 'name (2).ext', ...
    """
    dest_dir = Path(dest_dir)
    name = Path(filename).name
    stem = Path(name).stem
    suffix = Path(name).suffix  # includes dot
    candidate = dest_dir / name
    i = 1
    while candidate.exists():
        candidate = dest_dir / f"{stem} ({i}){suffix}"
        i += 1
    return candidate

def _human_size(nbytes: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if nbytes < 1024 or unit == "TB":
            return f"{nbytes:.0f} {unit}" if unit == "B" else f"{nbytes:.1f} {unit}"
        nbytes /= 1024.0
    return f"{nbytes:.1f} TB"

# =====================
# Attachment management
# =====================

class AttachmentManager:
    """
    Store attachments under <data_dir>/<YYYY-MM-DD>/_files/
    Cross-platform open/delete/list/copy helpers.
    Pure stdlib; no external deps.
    """

    def __init__(self, data_dir: Path | str):
        self.data_dir = Path(data_dir)
        _ensure_dir(self.data_dir)

    # ---- Paths ----
    def date_dir(self, date_str: str) -> Path:
        return self.data_dir / _slug_date(date_str)

    def attachments_dir(self, date_str: str) -> Path:
        p = self.date_dir(date_str) / "_files"
        _ensure_dir(p)
        return p

    # ---- CRUD ----
    def add_files(self, date_str: str, file_paths: Iterable[Path | str]) -> List[Path]:
        """Copy files into attachments dir. Returns list of destination paths."""
        dests: List[Path] = []
        adir = self.attachments_dir(date_str)
        for p in file_paths:
            src = Path(p)
            if not src.exists() or not src.is_file():
                continue
            dest = _unique_dest(adir, src.name)
            shutil.copy2(src, dest)  # preserve mtime
            dests.append(dest)
        return dests

    def list_files(self, date_str: str) -> List[Dict[str, object]]:
        """Return list of attachments as dicts: name, path, size_bytes, size_h, mtime, mtime_ts."""
        adir = self.attachments_dir(date_str)
        items: List[Dict[str, object]] = []
        for p in sorted(adir.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True):
            if p.is_file():
                stat = p.stat()
                items.append({
                    "name": p.name,
                    "path": str(p),
                    "size_bytes": stat.st_size,
                    "size_h": _human_size(stat.st_size),
                    "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(stat.st_mtime)),
                    "mtime_ts": int(stat.st_mtime),
                })
        return items

    def delete_file(self, date_str: str, filename: str) -> bool:
        path = self.attachments_dir(date_str) / filename
        try:
            if path.exists() and path.is_file():
                path.unlink()
                return True
            return False
        except Exception:
            return False

    # ---- Openers ----
    def open_file(self, path: Path | str) -> None:
        p = Path(path)
        if sys.platform.startswith("win"):
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(p)], check=False)
        else:
            subprocess.run(["xdg-open", str(p)], check=False)

    def open_date_folder(self, date_str: str) -> None:
        folder = self.attachments_dir(date_str)
        if sys.platform.startswith("win"):
            os.startfile(str(folder))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.run(["open", str(folder)], check=False)
        else:
            subprocess.run(["xdg-open", str(folder)], check=False)