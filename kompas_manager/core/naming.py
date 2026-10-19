"""Правила имён файлов."""
import re

_BAD_CHARS = re.compile(r'[<>:"/\\|?*]')


def file_name(designation, name, ext):
    """Имя файла по шаблону «Обозначение - Наименование», например «АБВГ.000.00 - Втулка.m3d»."""
    raw = f"{designation.strip()} - {name.strip()}"
    return _BAD_CHARS.sub("_", raw).strip() + ext


_FIELD = re.compile(r"\{([^{}]+)\}")


def format_number(value):
    """1000.0 -> «1000», 2.5 -> «2.5», текст остаётся как есть."""
    if isinstance(value, bool):
        return str(int(value))
    if isinstance(value, (int, float)):
        if float(value).is_integer():
            return str(int(value))
        return f"{value:.6g}"
    return str(value).strip()


def format_template(template, values):
    """Подставить значения переменных в шаблон: «BTEL.D{D}S{s}» -> «BTEL.D1000S10».
    Возвращает (текст, список неизвестных переменных)."""
    missing = []

    def repl(m):
        name = m.group(1).strip()
        if name not in values or values[name] in (None, ""):
            missing.append(name)
            return m.group(0)
        return format_number(values[name])

    return _FIELD.sub(repl, template or ""), missing


def template_fields(template):
    return [m.group(1).strip() for m in _FIELD.finditer(template or "")]
