"""Автономность изделия: все файлы, на которые ссылается изделие, должны лежать в его папке.

Внешний файл (библиотека, другой проект) копируется в папку документа, который на него ссылается,
то есть на тот же уровень изделия. Один и тот же файл (то же имя) — одна копия на всё изделие.
"""
import os
import zipfile

from .model import KIND_BY_EXT, norm

SERVICE_PREFIXES = ("_", ".")
SKIP_FILES = ("~", "_tmp_")


def product_files(root):
    """Файлы КОМПАСа изделия (без служебных папок)."""
    out = []
    for folder, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if not d.startswith(SERVICE_PREFIXES)]
        for f in files:
            if os.path.splitext(f)[1].lower() in KIND_BY_EXT and not f.startswith(SKIP_FILES):
                out.append(os.path.join(folder, f))
    return out


class Placement:
    """Куда положить копию внешнего файла; одна копия на имя файла в пределах изделия."""

    def __init__(self, root, existing=None):
        self.root = os.path.abspath(root)
        self.by_name = {}
        for p in existing if existing is not None else product_files(root):
            self.by_name.setdefault(os.path.basename(p).lower(), p)

    def inside(self, path):
        n = norm(path)
        return n == norm(self.root) or n.startswith(norm(self.root) + os.sep)

    def target(self, external, referrer):
        """(путь копии, уже есть в изделии)."""
        name = os.path.basename(external)
        found = self.by_name.get(name.lower())
        if found:
            return found, True
        path = os.path.join(os.path.dirname(referrer), name)
        self.by_name[name.lower()] = path
        return path, False


def external_refs(project):
    """Внешние ссылки изделия: {ключ внешнего файла: (путь, [ключи ссылающихся документов])}."""
    out = {}
    for key, d in project.docs.items():
        if not project.inside(key):
            continue
        for r in dict.fromkeys(d.refs):
            rk = norm(r)
            if not project.inside(rk):
                out.setdefault(rk, (r, []))[1].append(key)
    return out


def archive_product(root, zip_path):
    """Архив изделия для передачи: только актуальные файлы, без _backup, _versions, _old и т. п."""
    root = os.path.abspath(root)
    count = 0
    base = os.path.basename(root.rstrip("\\/"))
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
        for folder, dirs, files in os.walk(root):
            dirs[:] = [d for d in dirs if not d.startswith(SERVICE_PREFIXES)]
            for f in files:
                if f.startswith(SKIP_FILES) or f.lower().endswith((".bak", ".tmp")):
                    continue
                path = os.path.join(folder, f)
                if os.path.abspath(path) == os.path.abspath(zip_path):
                    continue
                z.write(path, os.path.join(base, os.path.relpath(path, root)))
                count += 1
    return count


def structure_files(project, heads):
    """Что входит в структуру выбранных головных сборок: модели по дереву, их чертежи и
    спецификации. Возвращает (ключи файлов структуры, пути файлов проекта вне структуры)."""
    keep, stack = set(), [h for h in heads if project.doc(h) is not None]
    while stack:
        k = stack.pop()
        if k in keep or not project.inside(k):
            continue
        keep.add(k)
        stack.extend(c for c, _n in project.components.get(k, []))
    models = set(keep)
    for m in models:
        keep.update(d for d in project.drawings_of.get(m, []) + project.specs_of.get(m, []) if project.inside(d))
    # спецификации на спецификации / чертежи сборок второго уровня
    changed = True
    while changed:
        changed = False
        for k, d in project.docs.items():
            if k not in keep and d.kind in ("drawing", "spec") and project.inside(k) and \
                    {norm(r) for r in d.refs} & keep:
                keep.add(k)
                changed = True
    out = sorted(project.raw_paths[k] for k in project.docs if project.inside(k) and k not in keep)
    return keep, out
