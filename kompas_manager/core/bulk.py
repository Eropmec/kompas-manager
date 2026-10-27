"""Массовые правки обозначений и наименований."""
import re


def replace_text(text, find, repl, case_sensitive=False):
    if not find:
        return text
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.sub(re.escape(find), lambda _m: repl, text, flags=flags)


def bulk_replace(values, field, find, repl, case_sensitive=False):
    """values: {ключ: (обозначение, наименование)}. Возвращает только изменившиеся записи."""
    idx = 0 if field == "designation" else 1
    out = {}
    for key, pair in values.items():
        new = replace_text(pair[idx], find, repl, case_sensitive)
        if new != pair[idx]:
            out[key] = (new, pair[1]) if idx == 0 else (pair[0], new)
    return out


def group_edit(values, name_mode="keep", name_text="", name_find="", des_find="", des_repl="", case_sensitive=False):
    """Групповая правка выделенных элементов. values: {ключ: (обозначение, наименование)}.
    name_mode: keep | set | prefix | suffix | replace. Возвращает новые значения всех элементов."""
    out = {}
    for key, (des, name) in values.items():
        if name_mode == "set":
            name = name_text
        elif name_mode == "prefix":
            name = name_text + name
        elif name_mode == "suffix":
            name = name + name_text
        elif name_mode == "replace" and name_find:
            name = replace_text(name, name_find, name_text, case_sensitive)
        if des_find:
            des = replace_text(des, des_find, des_repl, case_sensitive)
        out[key] = (des.strip(), name.strip())
    return out
