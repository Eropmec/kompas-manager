"""План переобозначения: какие файлы переименовать, что записать в свойства и штампы,
в каких документах обновить ссылки. Сам ничего не меняет.

Вход — новые обозначения и наименования моделей. Связанные чертежи и спецификации
переобозначаются вслед за своей моделью:
- обозначение в штампе = новое обозначение модели + код документа, если он был («АБВГ.000.00 СБ»);
- имя файла = «Обозначение - Наименование» по штампу.
"""
import os
from dataclasses import dataclass, field

from .model import ERROR, WARNING, Issue, norm
from .naming import file_name

ORDER = {"part": 0, "assembly": 1, "drawing": 2, "spec": 3}


@dataclass
class FileOp:
    key: str
    kind: str
    old_path: str
    new_path: str
    old_designation: str = ""
    new_designation: str = ""
    old_name: str = ""
    new_name: str = ""
    retitle: bool = False  # записать обозначение и наименование (свойства модели или штамп)
    relink: list = field(default_factory=list)  # ссылки, которые нужно обновить: [(старый ключ, новый путь)]

    @property
    def renamed(self):
        return norm(self.old_path) != norm(self.new_path)


@dataclass
class RenamePlan:
    root: str
    ops: list
    issues: list

    @property
    def mapping(self):
        """norm-ключ старого файла -> новый путь, для всех переименуемых файлов."""
        return {op.key: op.new_path for op in self.ops if op.renamed}

    @property
    def errors(self):
        return [i for i in self.issues if i.severity == ERROR]

    def affected_paths(self):
        return [op.old_path for op in self.ops]


def _primary(project, d):
    """Модель, к которой относится чертёж или спецификация (по обозначению в штампе, иначе первая)."""
    candidates = [norm(r) for r in d.refs if project.doc(norm(r)) and project.doc(norm(r)).kind in ("part", "assembly")]
    stamp = d.designation.strip()
    for k in candidates:
        des = project.doc(k).designation.strip()
        if des and stamp.startswith(des):
            return k
    return candidates[0] if candidates else None


def build_plan(project, changes):
    """changes: {ключ модели: (новое обозначение, новое наименование)}."""
    issues = []
    ops = {}

    def op_for(key):
        if key not in ops:
            d = project.doc(key)
            ops[key] = FileOp(key, d.kind, d.path, d.path, d.designation, d.designation, d.name, d.name)
        return ops[key]

    # 1. Модели
    for key, (des, name) in changes.items():
        d = project.doc(key)
        if d is None or d.kind not in ("part", "assembly"):
            continue
        des, name = des.strip(), name.strip()
        if (des, name) == (d.designation.strip(), d.name.strip()):
            expected = file_name(des, name, os.path.splitext(d.path)[1])
            if os.path.basename(d.path) == expected:
                continue  # ничего не меняется
        if not des or not name:
            issues.append(Issue(ERROR, key, "Пустое обозначение или наименование"))
            continue
        op = op_for(key)
        op.new_designation, op.new_name, op.retitle = des, name, True
        op.new_path = os.path.join(os.path.dirname(d.path), file_name(des, name, os.path.splitext(d.path)[1]))

    model_ops = {k: o for k, o in ops.items()}

    # 2. Чертежи и спецификации переобозначенных моделей
    for key, d in project.docs.items():
        if d.kind not in ("drawing", "spec"):
            continue
        primary = _primary(project, d)
        if primary not in model_ops:
            continue
        m = model_ops[primary]
        stamp = d.designation.strip()
        old_model = m.old_designation.strip()
        suffix = stamp[len(old_model):] if old_model and stamp.startswith(old_model) else ""
        op = op_for(key)
        op.new_designation = m.new_designation + suffix
        op.new_name = m.new_name
        op.retitle = True
        op.new_path = os.path.join(
            os.path.dirname(d.path), file_name(op.new_designation, op.new_name, os.path.splitext(d.path)[1])
        )

    # 3. Ссылки на переименованные файлы
    mapping = {k: o.new_path for k, o in ops.items() if o.renamed}
    for key, d in project.docs.items():
        links = [(norm(r), mapping[norm(r)]) for r in dict.fromkeys(d.refs) if norm(r) in mapping]
        if links:
            op_for(key).relink = links

    # 4. Проверки
    targets = {}
    old_keys = set(mapping)
    for op in ops.values():
        if op.renamed:
            nk = norm(op.new_path)
            if nk in targets:
                issues.append(Issue(ERROR, op.key, f"Два файла получают одно имя: {os.path.basename(op.new_path)}"))
            targets[nk] = op.key
            if nk in old_keys:
                issues.append(Issue(ERROR, op.key, f"Новое имя совпадает со старым именем другого файла: {os.path.basename(op.new_path)}"))
            elif os.path.exists(op.new_path) or nk in project.docs:
                issues.append(Issue(ERROR, op.key, f"Файл уже существует: {os.path.basename(op.new_path)}"))
        d = project.doc(op.key)
        if d.error:
            issues.append(Issue(WARNING, op.key, f"Файл был прочитан не полностью: {d.error}"))
        if not project.inside(op.key):
            issues.append(Issue(ERROR, op.key, "Файл вне папки проекта — изменять его нельзя"))

    final_des = {}
    for key, d in project.docs.items():
        if d.kind in ("part", "assembly"):
            des = ops[key].new_designation if key in ops else d.designation
            if des.strip():
                final_des.setdefault(des.strip(), []).append(key)
    for des, keys in final_des.items():
        if len(keys) > 1 and any(k in model_ops for k in keys):
            for k in keys:
                if k in model_ops:
                    issues.append(Issue(ERROR, k, f"Обозначение {des} будет у {len(keys)} файлов"))

    for op in model_ops.values():
        if file_name(op.new_designation, op.new_name, "") != f"{op.new_designation} - {op.new_name}":
            issues.append(Issue(WARNING, op.key, "Недопустимые в именах файлов символы заменены на «_»"))

    ordered = sorted(ops.values(), key=lambda o: (ORDER[o.kind], project.display_path(o.key).lower()))
    return RenamePlan(project.root, ordered, issues)
