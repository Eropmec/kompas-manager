"""Схемы обозначения.

Схема задаётся шаблоном с полями в фигурных скобках:
    {код}        — постоянная часть, задаётся в настройках проекта (например, АБВГ);
    {сборка:3}   — номер сборки, дополняется нулями до 3 знаков;
    {деталь:2}   — номер детали внутри сборки, до 2 знаков.

Пример: «{код}.{сборка:3}.{деталь:2}» даёт АБВГ.000.00 (головная сборка),
АБВГ.001.00 (подсборка), АБВГ.001.01 (деталь в подсборке АБВГ.001.00).
Подсборки любого уровня нумеруются в одном поле «сборка».
"""
import json
import os
import re
from dataclasses import asdict, dataclass

FIELD_RE = re.compile(r"\{(код|сборка|деталь)(?::(\d+))?\}")

DEFAULT_SCHEMES = [
    {"name": "Код.ССС.ДД (АБВГ.001.01)", "template": "{код}.{сборка:3}.{деталь:2}"},
]


class SchemeError(ValueError):
    pass


@dataclass
class Scheme:
    name: str
    template: str

    def fields(self):
        return {m.group(1): int(m.group(2) or 0) for m in FIELD_RE.finditer(self.template)}

    def validate(self):
        """Список ошибок шаблона (пустой, если всё в порядке)."""
        errors = []
        if not self.name.strip():
            errors.append("Не задано название схемы")
        fields = self.fields()
        for required in ("сборка", "деталь"):
            if required not in fields:
                errors.append(f"В шаблоне нет поля {{{required}}}")
        leftover = FIELD_RE.sub("", self.template)
        if "{" in leftover or "}" in leftover:
            errors.append("Неизвестное поле в фигурных скобках. Допустимы {код}, {сборка:N}, {деталь:N}")
        return errors

    def width(self, field):
        return self.fields().get(field, 0)

    def format(self, code, asm, part):
        def repl(m):
            name, width = m.group(1), int(m.group(2) or 0)
            if name == "код":
                return code
            value = asm if name == "сборка" else part
            return str(value).zfill(width)

        return FIELD_RE.sub(repl, self.template)

    def to_dict(self):
        return asdict(self)


def library_path():
    base = os.environ.get("APPDATA") or os.path.join(os.path.expanduser("~"), ".config")
    folder = os.path.join(base, "KompasManager")
    os.makedirs(folder, exist_ok=True)
    return os.path.join(folder, "schemes.json")


def load_library(path=None):
    path = path or library_path()
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        schemes = [Scheme(d["name"], d["template"]) for d in data.get("schemes", [])]
        if schemes:
            return schemes
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return [Scheme(**d) for d in DEFAULT_SCHEMES]


def save_library(schemes, path=None):
    path = path or library_path()
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"schemes": [s.to_dict() for s in schemes]}, f, ensure_ascii=False, indent=2)
