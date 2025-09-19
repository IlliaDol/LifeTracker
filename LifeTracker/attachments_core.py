from __future__ import annotations
import os, sys, shutil, time, subprocess
from pathlib import Path
from typing import Iterable, List, Dict

def _ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)

def _slug_date(date_str: str) -> str:
    return "".join(ch if (ch.isdigit() or ch == "-") else "_" for ch in date_str.strip())

def _unique_dest(dest_dir: Path, filename: str) -> Path:
    name = Path(filename).name
    stem = Path(name).stem
    suff = Path(name).suffix
    cand = dest_dir / name
    i = 1
    while cand.exists():
        cand = dest_dir / f"{stem} ({i}){suff}"
        i += 1
    return cand

def _human_size(nbytes: int) -> str:
    for unit in ("B","KB","MB","GB","TB"):
        if nbytes < 1024 or unit=="TB":
            return f"{nbytes:.0f} {unit}" if unit=="B" else f"{nbytes:.1f} {unit}"
        nbytes /= 1024.0
    return f"{nbytes:.1f} TB"

class AttachmentManager:
    """Stores files under <data_dir>/<YYYY-MM-DD>/_files/"""
    def __init__(self, data_dir: Path | str):
        self.data_dir = Path(data_dir)
        _ensure_dir(self.data_dir)

    def attachments_dir(self, date_str: str) -> Path:
        d = self.data_dir / _slug_date(date_str) / "_files"
        _ensure_dir(d)
        return d

    def add_files(self, date_str: str, paths: Iterable[Path | str]):
        dests = []
        adir = self.attachments_dir(date_str)
        for p in paths:
            p = Path(p)
            if p.exists() and p.is_file():
                dest = _unique_dest(adir, p.name)
                shutil.copy2(p, dest)
                dests.append(dest)
        return dests

    def list_files(self, date_str: str) -> List[Dict[str, object]]:
        adir = self.attachments_dir(date_str)
        out = []
        for p in sorted(adir.glob("*"), key=lambda x: x.stat().st_mtime, reverse=True):
            if p.is_file():
                st = p.stat()
                out.append({
                    "name": p.name,
                    "path": str(p),
                    "size_bytes": st.st_size,
                    "size_h": _human_size(st.st_size),
                    "mtime": time.strftime("%Y-%m-%d %H:%M", time.localtime(st.st_mtime)),
                    "mtime_ts": int(st.st_mtime),
                })
        return out

    def delete_file(self, date_str: str, name: str) -> bool:
        p = self.attachments_dir(date_str) / name
        try:
            if p.exists() and p.is_file():
                p.unlink()
                return True
            return False
        except Exception:
            return False

    def open_file(self, path: str | Path) -> None:
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
