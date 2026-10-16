"""Правила имён файлов."""
import re

_BAD_CHARS = re.compile(r'[<>:"/\\|?*]')


def file_name(designation, name, ext):
    """Имя файла по шаблону «Обозначение - Наименование», например «АБВГ.000.00 - Втулка.m3d»."""
    raw = f"{designation.strip()} - {name.strip()}"
    return _BAD_CHARS.sub("_", raw).strip() + ext
