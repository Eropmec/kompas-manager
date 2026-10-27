"""Настройки проекта: схема обозначения, код, закреплённые номера, исключения.

Хранятся в файле .kompas_manager.json в папке проекта (синхронизируются облаком вместе с проектом).
Файлы в настройках указаны путями относительно папки проекта.
"""
import json
import os
from dataclasses import dataclass, field

from .model import norm
from .schemes import DEFAULT_SCHEMES, Scheme

FILE_NAME = ".kompas_manager.json"


@dataclass
class ProjectSettings:
    scheme: Scheme = field(default_factory=lambda: Scheme(**DEFAULT_SCHEMES[0]))
    code: str = "АБВГ"
    pins: dict = field(default_factory=dict)  # отн. путь -> {"сборка": N} или {"деталь": N}
    excluded: list = field(default_factory=list)  # отн. пути моделей, не получающих обозначение
    origins: dict = field(default_factory=dict)  # отн. путь копии -> {"source": путь, "values": {имя: значение}}

    # ---------- файл ----------

    @classmethod
    def load(cls, root):
        path = os.path.join(root, FILE_NAME)
        s = cls()
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return s
        sch = data.get("scheme") or {}
        if sch.get("template"):
            s.scheme = Scheme(sch.get("name", ""), sch["template"])
        s.code = data.get("code", s.code)
        s.pins = {k: dict(v) for k, v in (data.get("pins") or {}).items()}
        s.excluded = list(data.get("excluded") or [])
        s.origins = {k: dict(v) for k, v in (data.get("origins") or {}).items()}
        return s

    def save(self, root):
        data = {
            "scheme": self.scheme.to_dict(),
            "code": self.code,
            "pins": self.pins,
            "excluded": sorted(self.excluded),
            "origins": self.origins,
        }
        with open(os.path.join(root, FILE_NAME), "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    # ---------- доступ по ключу файла ----------

    @staticmethod
    def rel(root, key_or_path):
        return os.path.relpath(key_or_path, root).replace("\\", "/")

    def _find(self, root, key, store):
        for rel in store:
            if norm(os.path.join(root, rel)) == key:
                return rel
        return None

    def pin(self, root, key):
        rel = self._find(root, key, self.pins)
        return self.pins.get(rel, {}) if rel else {}

    def set_pin(self, root, key, field_name, value):
        rel = self._find(root, key, self.pins) or self.rel(root, key)
        if value is None:
            self.pins.pop(rel, None)
        else:
            self.pins[rel] = {field_name: int(value)}

    def is_excluded(self, root, key):
        return self._find(root, key, self.excluded) is not None

    def set_excluded(self, root, key, excluded):
        rel = self._find(root, key, self.excluded)
        if excluded and rel is None:
            self.excluded.append(self.rel(root, key))
        elif not excluded and rel is not None:
            self.excluded.remove(rel)

    def rename_paths(self, root, mapping):
        """Обновить пути после переобозначения. mapping: norm-ключ старого файла -> новый путь."""
        def moved(rel):
            new = mapping.get(norm(os.path.join(root, rel)))
            return self.rel(root, new) if new else rel

        self.pins = {moved(rel): v for rel, v in self.pins.items()}
        self.excluded = [moved(rel) for rel in self.excluded]
        self.origins = {moved(rel): v for rel, v in self.origins.items()}

    # ---------- происхождение копий (библиотека, внешние файлы) ----------

    def add_origin(self, root, path, source, values=None):
        from .library import values_key

        self.origins[self.rel(root, path)] = {"source": os.path.normpath(source), "values": values_key(values or {})}

    def origin(self, root, path):
        return self.origins.get(self.rel(root, path))

    def find_origin(self, root, source, values=None):
        """Файл изделия, сделанный из source с теми же значениями, или None."""
        from .library import values_key

        want = values_key(values or {})
        for rel, o in self.origins.items():
            if norm(o.get("source", "")) == norm(source) and o.get("values", {}) == want:
                path = os.path.normpath(os.path.join(root, rel))
                if os.path.exists(path):
                    return path
        return None
