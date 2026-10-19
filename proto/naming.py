"""Правила имён файлов. Без зависимостей от КОМПАСа, чтобы окно могло показывать предпросмотр."""
import re


def file_name(designation, name, ext):
    """Имя файла по шаблону «Обозначение - Наименование», например «АБВГ.000.00 - Втулка.m3d»."""
    raw = f"{designation.strip()} - {name.strip()}"
    return re.sub(r'[<>:"/\\|?*]', "_", raw).strip() + ext


_FIELD = re.compile(r"\{([^{}]+)\}")


def format_number(value):
    """1000.0 -> «1000», 2.5 -> «2.5», текст остаётся как есть."""
    if isinstance(value, (int, float)):
        if float(value).is_integer():
            return str(int(value))
        return f"{value:.6g}"
    return str(value)


def format_template(template, values):
    """Подставить значения переменных в шаблон: «BTEL.D{D}S{s}» -> «BTEL.D1000S10».
    Возвращает (текст, список неизвестных переменных)."""
    missing = []

    def repl(m):
        name = m.group(1).strip()
        if name not in values:
            missing.append(name)
            return m.group(0)
        return format_number(values[name])

    return _FIELD.sub(repl, template), missing


def parse_values(text):
    """«D=800; s=8» или по строке на переменную -> {"D": "800", "s": "8"}."""
    result = {}
    for part in re.split(r"[;\n]", text):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise ValueError(f"Ожидается «Имя=значение»: {part}")
        name, value = part.split("=", 1)
        if not name.strip() or not value.strip():
            raise ValueError(f"Пустое имя или значение: {part}")
        result[name.strip()] = value.strip().replace(",", ".")
    return result
