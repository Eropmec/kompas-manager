"""Новая структура изделия: дерево сборок и деталей до создания файлов.

Обозначения считаются тем же алгоритмом, что и «Применить схему» для готового проекта,
поэтому новая структура нумеруется так же, как существующая.
"""
import os
from dataclasses import dataclass, field

from .model import DocInfo
from .naming import file_name
from .numbering import assign
from .project import Project


@dataclass
class Node:
    kind: str  # "assembly" | "part"
    name: str
    children: list = field(default_factory=list)
    count: int = 1  # количество вхождений в родительскую сборку
    designation: str = ""  # вручную; пусто — по схеме

    def walk(self):
        yield self
        for c in self.children:
            yield from c.walk()


@dataclass
class FileItem:
    node: Node
    path: str
    designation: str
    name: str
    components: list = field(default_factory=list)  # [(путь, количество)] для сборок


def designate(root, folder, settings):
    """Обозначения всех узлов по схеме: {id(node): обозначение}."""
    nodes = list(root.walk())
    fake = {id(n): os.path.join(folder, f"__node{i}{'.a3d' if n.kind == 'assembly' else '.m3d'}")
            for i, n in enumerate(nodes)}
    docs = []
    for n in nodes:
        refs = []
        for c in n.children:
            refs += [fake[id(c)]] * max(1, c.count)
        docs.append(DocInfo(path=fake[id(n)], kind=n.kind, designation="", name=n.name, refs=refs))
    result, warnings = assign(Project(folder, docs), settings)
    by_path = {os.path.normcase(os.path.abspath(p)): i for i, p in fake.items()}
    out = {}
    for key, des in result.items():
        out[by_path[key]] = des
    for n in nodes:
        if n.designation.strip():
            out[id(n)] = n.designation.strip()
    return out, warnings


def plan_files(root, folder, settings):
    """Список файлов к созданию: детали, затем сборки снизу вверх. И список проблем."""
    designations, warnings = designate(root, folder, settings)
    problems = [w.message for w in warnings]
    paths = {}
    seen = {}
    for n in root.walk():
        des = designations.get(id(n), "")
        if not n.name.strip():
            problems.append("Есть элемент без наименования")
        ext = ".a3d" if n.kind == "assembly" else ".m3d"
        path = os.path.join(folder, file_name(des, n.name, ext) if des else n.name.strip() + ext)
        key = os.path.normcase(path)
        if key in seen:
            problems.append(f"Два элемента получают одно имя файла: {os.path.basename(path)}")
        seen[key] = n
        if os.path.exists(path):
            problems.append(f"Файл уже существует: {os.path.basename(path)}")
        paths[id(n)] = (path, des)

    items = []

    def visit(n):
        for c in n.children:
            visit(c)
        path, des = paths[id(n)]
        comps = [(paths[id(c)][0], max(1, c.count)) for c in n.children]
        items.append(FileItem(n, path, des, n.name.strip(), comps))

    visit(root)
    items.sort(key=lambda it: 0 if it.node.kind == "part" else 1)  # детали первыми, сборки — снизу вверх
    return items, problems
