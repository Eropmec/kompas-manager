"""Расчёт обозначений по схеме и структуре проекта.

Правила:
- головная сборка: сборка = 0, деталь = 0 (при нескольких головных — следующие получают номера сборок);
- подсборки любого уровня получают номера сборок 1, 2, 3… в порядке обхода дерева;
- элемент нумеруется в первой сборке, где он встретился (общие детали — один раз);
- подсборка: деталь = 0; деталь: номер сборки-владельца и свой номер 1, 2, 3…;
- закреплённые номера сохраняются, автонумерация их пропускает;
- исключённые элементы (стандартные и покупные изделия) и файлы вне папки проекта не нумеруются,
  исключённая сборка не нумеруется вместе с содержимым;
- детали вне сборок нумеруются в первой головной сборке.
"""
from .model import WARNING, Issue


class _Counter:
    def __init__(self, start, taken):
        self.next = start
        self.taken = set(taken)

    def take(self):
        while self.next in self.taken:
            self.next += 1
        value = self.next
        self.taken.add(value)
        self.next += 1
        return value


def assign(project, settings):
    """Новые обозначения: {ключ модели: обозначение}, и список предупреждений."""
    root = project.root
    scheme = settings.scheme
    warnings = []

    def numberable(key):
        d = project.doc(key)
        return (
            d is not None
            and d.kind in ("part", "assembly")
            and project.inside(key)
            and not settings.is_excluded(root, key)
        )

    # 1. Обход дерева: порядок сборок и владелец каждой детали
    assemblies = []  # сборки в порядке обхода (без головных)
    owner = {}  # деталь -> сборка, где она нумеруется
    visited = set()
    roots = [k for k in project.roots() if numberable(k)]

    def walk(asm, stack):
        for child, _count in project.components.get(asm, []):
            if child in visited or child in stack or not numberable(child):
                continue
            visited.add(child)
            d = project.doc(child)
            if d.kind == "assembly":
                assemblies.append(child)
                walk(child, stack | {child})
            else:
                owner[child] = asm

    for r in roots:
        visited.add(r)
        walk(r, {r})

    for part in project.loose_parts():
        if part not in visited and numberable(part):
            if roots:
                owner[part] = roots[0]
            else:
                warnings.append(Issue(WARNING, part, "Деталь вне сборок и нет головной сборки — номер не присвоен"))

    # 2. Номера сборок
    asm_no = {}
    pinned_asm = {}
    for key in roots[1:] + assemblies:
        p = settings.pin(root, key).get("сборка")
        if p is not None:
            pinned_asm[key] = p
    if roots:
        asm_no[roots[0]] = settings.pin(root, roots[0]).get("сборка", 0)
    counter = _Counter(1, list(pinned_asm.values()) + list(asm_no.values()))
    for key in roots[1:] + assemblies:
        asm_no[key] = pinned_asm[key] if key in pinned_asm else counter.take()

    # 3. Номера деталей внутри сборок-владельцев
    parts_of = {}
    for part, asm in owner.items():
        parts_of.setdefault(asm, []).append(part)
    order = {k: i for i, k in enumerate(_tree_order(project, roots))}
    part_no = {}
    for asm, parts in parts_of.items():
        parts.sort(key=lambda k: order.get(k, len(order)))
        pinned = {k: settings.pin(root, k).get("деталь") for k in parts}
        pinned = {k: v for k, v in pinned.items() if v is not None}
        counter = _Counter(1, pinned.values())
        for part in parts:
            part_no[part] = pinned[part] if part in pinned else counter.take()

    # 4. Обозначения
    result = {}
    asm_width, part_width = scheme.width("сборка"), scheme.width("деталь")
    for key, n in asm_no.items():
        result[key] = scheme.format(settings.code, n, 0)
        if asm_width and len(str(n)) > asm_width:
            warnings.append(Issue(WARNING, key, f"Номер сборки {n} не помещается в {asm_width} знака"))
    for key, n in part_no.items():
        result[key] = scheme.format(settings.code, asm_no[owner[key]], n)
        if part_width and len(str(n)) > part_width:
            warnings.append(Issue(WARNING, key, f"Номер детали {n} не помещается в {part_width} знака"))

    seen = {}
    for key, des in result.items():
        if des in seen:
            warnings.append(Issue(WARNING, key, f"Обозначение {des} получилось у двух элементов — проверьте закреплённые номера"))
        seen[des] = key
    return result, warnings


def _tree_order(project, roots):
    """Все элементы в порядке обхода дерева (для стабильной нумерации деталей)."""
    out, seen = [], set()

    def walk(key):
        for child, _ in project.components.get(key, []):
            if child not in seen:
                seen.add(child)
                out.append(child)
                walk(child)

    for r in roots:
        seen.add(r)
        out.append(r)
        walk(r)
    out.extend(k for k in project.loose_parts() if k not in seen)
    return out
