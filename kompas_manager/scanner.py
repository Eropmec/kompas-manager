"""Сканирование папки проекта: чтение свойств, штампов и ссылок документов через Kompas API.

Файлы, не изменившиеся с прошлого раза, берутся из кэша. Если читать нечего,
КОМПАС не запускается вообще.
"""
import os

from kompas_manager.core.model import KIND_BY_EXT, DocInfo, kind_of

# Служебные папки, которые не относятся к проекту
SKIP_DIRS = {"_old", "_backup", ".git"}


def list_files(root):
    result = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS and not d.startswith(".")]
        for f in files:
            if os.path.splitext(f)[1].lower() in KIND_BY_EXT and not f.startswith("~"):
                result.append(os.path.join(folder, f))
    return sorted(result)


def _text(value):
    return (value or "").strip() if isinstance(value, str) or value is None else str(value).strip()


def read_doc(K, app, path):
    """Прочитать один документ. Ошибки отдельных частей не прерывают чтение остальных."""
    info = DocInfo(path=path, kind=kind_of(path))
    errors = []
    doc, ours = K.open_for_reading(app, path)
    try:
        if info.kind in ("part", "assembly"):
            try:
                designation, name = K.read_props(doc)
                info.designation, info.name = _text(designation), _text(name)
            except Exception as e:
                errors.append(f"свойства: {e}")
        if info.kind in ("drawing", "spec"):
            try:
                designation, name = K.stamp_values(doc)
                info.designation, info.name = _text(designation), _text(name)
            except Exception as e:
                errors.append(f"штамп: {e}")
        if info.kind in ("assembly", "drawing", "spec"):
            try:
                info.refs = [r for r in K.references(doc, path) if r]
            except Exception as e:
                errors.append(f"ссылки: {e}")
    finally:
        if ours:
            K.close_doc(doc)
    info.error = "; ".join(errors)
    return info


def scan(root, cache, show=False, force=False, log=print, progress=None, cancelled=lambda: False):
    """Прочитать все документы проекта. Возвращает (список DocInfo, завершено_полностью)."""
    files = list_files(root)
    result, todo = [], []
    for path in files:
        st = os.stat(path)
        cached = None if force else cache.get(path, st.st_mtime, st.st_size)
        if cached is not None:
            result.append(cached)
        else:
            todo.append((path, st))

    log(f"Файлов КОМПАС: {len(files)}; из кэша: {len(result)}; прочитать: {len(todo)}")
    if not todo:
        return result, True

    from kompas_manager import kompas_api as K  # импорт здесь: модуль требует Windows и КОМПАС

    complete = True
    session = K.Session(show, log)
    try:
        for i, (path, st) in enumerate(todo):
            if cancelled():
                log("Сканирование остановлено пользователем")
                complete = False
                break
            if progress:
                progress(i, len(todo), os.path.relpath(path, root))
            try:
                info = read_doc(K, session.app, path)
            except Exception as e:
                info = DocInfo(path=path, kind=kind_of(path), error=f"файл не открылся: {e}")
            info.mtime, info.size = st.st_mtime, st.st_size
            if info.error:
                log(f"  {os.path.relpath(path, root)}: {info.error}")
            else:
                cache.put(info)  # неполностью прочитанные файлы перечитываются в следующий раз
            result.append(info)
    finally:
        session.close(log)
    if progress:
        progress(len(todo), len(todo), "")
    return result, complete
