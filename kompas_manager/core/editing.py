"""Правка готовой сборки: удаление вхождений и добавление новых элементов."""
import os
from dataclasses import dataclass, field

from .model import DocInfo, norm
from .naming import file_name
from .numbering import assign
from .project import Project
from .structure import FileItem
from .transfer import subtree_keys


@dataclass
class DeletePlan:
    parent: str  # путь сборки, из которой удаляется вхождение
    child: str  # путь удаляемого компонента
    instances: int
    files: list = field(default_factory=list)  # файлы к удалению (не используются больше нигде)
    kept: list = field(default_factory=list)  # файлы узла, которые используются в других местах


def plan_delete(project, parent_key, child_key, with_files=True):
    instances = dict(project.components.get(parent_key, [])).get(child_key, 0)
    plan = DeletePlan(project.raw_paths.get(parent_key, parent_key), project.raw_paths.get(child_key, child_key),
                      instances)
    if not with_files or not project.inside(child_key):
        return plan
    models, docs = subtree_keys(project, child_key)
    removed = set(models)
    # Модель остаётся, если на неё ссылается что-то вне удаляемого узла
    changed = True
    while changed:
        changed = False
        for m in list(removed):
            users = set(project.parents.get(m, set()))
            if m == child_key:
                users.discard(parent_key)  # все вхождения из этой сборки удаляются
            outside = users - removed
            if outside:
                removed.discard(m)
                changed = True
    for m in models:
        (plan.files if m in removed else plan.kept).append(project.raw_paths.get(m, m))
    for d in docs:
        refs = {norm(r) for r in project.doc(d).refs}
        models_refs = {r for r in refs if project.doc(r) and project.doc(r).kind in ("part", "assembly")}
        if models_refs and models_refs <= removed:
            plan.files.append(project.raw_paths.get(d, d))
    return plan


@dataclass
class AppendPlan:
    assembly: str  # путь существующей сборки
    items: list  # FileItem новых файлов: детали, затем сборки снизу вверх
    direct: list  # [(путь, количество)] — что вставить в существующую сборку
    problems: list = field(default_factory=list)


def plan_append(project, assembly_key, new_children, settings, folder=None):
    """new_children — список core.structure.Node, добавляемых в существующую сборку."""
    folder = folder or os.path.dirname(project.raw_paths.get(assembly_key, assembly_key))
    docs = [DocInfo(d.path, d.kind, d.designation, d.name, list(d.refs)) for d in project.docs.values()]
    by_key = {norm(d.path): d for d in docs}
    fake = {}
    counter = [0]

    def register(node):
        counter[0] += 1
        ext = ".a3d" if node.kind == "assembly" else ".m3d"
        path = os.path.join(folder, f"__new{counter[0]}{ext}")
        fake[id(node)] = path
        refs = []
        for c in node.children:
            refs += [register(c)] * max(1, c.count)
        docs.append(DocInfo(path, node.kind, "", node.name, refs))
        return path

    target = by_key[assembly_key]
    for n in new_children:
        target.refs += [register(n)] * max(1, n.count)
    result, warnings = assign(Project(project.root, docs), settings)
    problems = [w.message for w in warnings if norm(w.key) in {norm(p) for p in fake.values()}]

    existing_des = {d.designation.strip() for d in project.docs.values() if d.designation.strip()}
    numbers = _next_numbers(project, assembly_key, new_children, settings)
    paths = {}
    for n in [x for c in new_children for x in c.walk()]:
        des = n.designation.strip() or numbers.get(id(n)) or result.get(norm(fake[id(n)]), "")
        if not n.name.strip():
            problems.append("Есть элемент без наименования")
        if des in existing_des:
            problems.append(f"Обозначение {des} уже занято в изделии — проверьте нумерацию существующих элементов")
        ext = ".a3d" if n.kind == "assembly" else ".m3d"
        path = os.path.join(folder, file_name(des, n.name, ext) if des else n.name.strip() + ext)
        if os.path.exists(path):
            problems.append(f"Файл уже существует: {os.path.basename(path)}")
        paths[id(n)] = (path, des)

    items = []

    def visit(n):
        for c in n.children:
            visit(c)
        path, des = paths[id(n)]
        items.append(FileItem(n, path, des, n.name.strip(),
                              [(paths[id(c)][0], max(1, c.count)) for c in n.children]))

    for n in new_children:
        visit(n)
    items.sort(key=lambda it: 0 if it.node.kind == "part" else 1)
    direct = [(paths[id(n)][0], max(1, n.count)) for n in new_children]
    return AppendPlan(project.raw_paths.get(assembly_key, assembly_key), items, direct, problems)


def _next_numbers(project, assembly_key, new_children, settings):
    """Обозначения новых элементов: следующие свободные номера после фактически занятых.
    Пусто, если обозначение сборки не разбирается по схеме (тогда — пересчёт по схеме)."""
    scheme, code = settings.scheme, settings.code
    target = project.doc(assembly_key)
    parsed = scheme.parse(target.designation, code) if target else None
    if parsed is None:
        return {}
    used_asm, used_parts = set(), {}
    for d in project.docs.values():
        if d.kind in ("part", "assembly"):
            pr = scheme.parse(d.designation, code)
            if pr:
                used_asm.add(pr[0])
                if pr[1]:
                    used_parts.setdefault(pr[0], set()).add(pr[1])
    out = {}

    def take(pool):
        n = max(pool | {0}) + 1
        pool.add(n)
        return n

    def number(node, owner_asm):
        if node.kind == "assembly":
            a = take(used_asm)
            out[id(node)] = scheme.format(code, a, 0)
            for c in node.children:
                number(c, a)
        else:
            out[id(node)] = scheme.format(code, owner_asm, take(used_parts.setdefault(owner_asm, set())))

    for n in new_children:
        number(n, parsed[0])
    return out
