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
