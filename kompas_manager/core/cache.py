"""Кэш результатов чтения файлов, чтобы повторное открытие проекта не запускало КОМПАС.

Запись считается актуальной, пока у файла не изменились время изменения и размер.
Кэш лежит локально (%LOCALAPPDATA%), а не в облачной папке проекта.
"""
import os
import sqlite3
import tempfile

from .model import DocInfo, norm

SCHEMA = "docs_v1"


def default_path():
    base = os.environ.get("LOCALAPPDATA") or os.path.join(os.path.expanduser("~"), ".cache")
    if not os.path.isdir(base):
        base = tempfile.gettempdir()
    folder = os.path.join(base, "KompasManager")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "scan_cache.sqlite3")


class ScanCache:
    def __init__(self, path=None):
        self.path = path or default_path()
        self.db = sqlite3.connect(self.path)
        self.db.execute(
            f"CREATE TABLE IF NOT EXISTS {SCHEMA} "
            "(key TEXT PRIMARY KEY, mtime REAL, size INTEGER, data TEXT)"
        )
        self.db.commit()

    def get(self, path, mtime, size):
        row = self.db.execute(f"SELECT mtime, size, data FROM {SCHEMA} WHERE key = ?", (norm(path),)).fetchone()
        if row is None or row[0] != mtime or row[1] != size:
            return None
        info = DocInfo.from_json(row[2])
        info.path = path
        return info

    def put(self, info):
        self.db.execute(
            f"INSERT OR REPLACE INTO {SCHEMA} (key, mtime, size, data) VALUES (?, ?, ?, ?)",
            (norm(info.path), info.mtime, info.size, info.to_json()),
        )
        self.db.commit()

    def clear(self):
        self.db.execute(f"DELETE FROM {SCHEMA}")
        self.db.commit()

    def close(self):
        self.db.close()
