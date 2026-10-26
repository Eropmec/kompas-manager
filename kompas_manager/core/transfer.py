"""Перенос узла (сборки с составом или детали) из одного проекта в другой.

Копируются модели узла, их чертежи и спецификации. Файлы вне папки исходного проекта
(библиотека) не копируются: копии продолжают ссылаться на них. Относительное расположение
файлов внутри узла сохраняется; узел кладётся в выбранную папку целевого проекта.
"""
import os
from dataclasses import dataclass, field

from .model import norm


@dataclass
class TransferPlan:
    source_root: str  # папка проекта-источника
    root_key: str  # ключ головной модели узла
    files: dict  # ключ старого файла -> новый путь
    target_dir: str
    problems: list = field(default_factory=list)
    sources: dict = field(default_factory=dict)  # ключ -> исходный путь как на диске

    @property
    def new_root(self):
        return self.files[self.root_key]


def subtree_keys(project, key):
    """Модели узла (внутри проекта) + их чертежи и спецификации."""
    models, stack = [], [key]
    while stack:
        k = stack.pop()
        if k in models or project.doc(k) is None or not project.inside(k):
            continue
        models.append(k)
        stack.extend(c for c, _ in project.components.get(k, []))
    docs = []
    for m in models:
        for d in project.drawings_of.get(m, []) + project.specs_of.get(m, []):
            if d not in docs and project.inside(d):
                docs.append(d)
    return models, docs


def plan_transfer(project, key, target_dir):
    models, docs = subtree_keys(project, key)
    paths = [project.raw_paths.get(k, k) for k in models + docs]
    base = os.path.dirname(project.raw_paths.get(key, key))
    # Общая папка всех файлов узла — чтобы сохранить их взаимное расположение
    try:
        common = os.path.commonpath([os.path.dirname(p) for p in paths] + [base])
    except ValueError:
        common = base
    files = {}
    problems = []
    for k, p in zip(models + docs, paths):
        new = os.path.join(target_dir, os.path.relpath(p, common))
        files[k] = new
        if os.path.exists(new):
            problems.append(f"Файл уже существует: {os.path.relpath(new, target_dir)}")
    if norm(target_dir).startswith(norm(common) + os.sep) or norm(target_dir) == norm(common):
        if any(norm(v) == k for k, v in files.items()):
            problems.append("Папка назначения совпадает с исходной — выберите другую")
    return TransferPlan(project.root, key, files, target_dir, problems, dict(zip(models + docs, paths)))


def relink_map(plan):
    """Для перепривязки внутри копий: ключ старого файла -> новый путь."""
    return dict(plan.files)


def folder_relink_map(old_root, new_root, refs):
    """После копирования папки: ссылки, ведущие в старую папку, -> такие же файлы в новой."""
    out = {}
    o = norm(old_root) + os.sep
    for r in refs:
        n = norm(r)
        if n.startswith(o):
            target = os.path.join(new_root, os.path.relpath(r, old_root))
            if os.path.exists(target):
                out[n] = target
    return out
