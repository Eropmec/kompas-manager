"""Проект: связи между файлами, структура сборок и проверки."""
import os
from collections import defaultdict

from .model import ERROR, INFO, SEVERITY_ORDER, WARNING, DocInfo, Issue, norm
from .naming import file_name


class Project:
    """Проект, построенный из прочитанных документов.

    Ключ файла везде — norm-путь (см. model.norm).
    """

    def __init__(self, root, docs):
        self.root = os.path.abspath(root)
        self.root_key = norm(self.root)
        self.docs = {norm(d.path): d for d in docs}
        self.raw_paths = {k: d.path for k, d in self.docs.items()}

        self.components = {}  # сборка -> [(компонент, количество вхождений)] в порядке сборки
        self.parents = defaultdict(set)  # компонент -> сборки, в которые он входит
        self.drawings_of = defaultdict(list)  # модель -> чертежи по ней
        self.specs_of = defaultdict(list)  # документ -> спецификации, связанные с ним

        self.issues = []
        self._link()
        self._check()
        self.issues.sort(key=lambda i: (SEVERITY_ORDER[i.severity], self.display_path(i.key), i.message))
        self.issues_by_key = defaultdict(list)
        for issue in self.issues:
            self.issues_by_key[issue.key].append(issue)

    # ---------- доступ ----------

    def doc(self, key):
        return self.docs.get(key)

    def exists(self, key):
        return key in self.docs or os.path.exists(self.raw_paths.get(key, key))

    def inside(self, key):
        return key == self.root_key or key.startswith(self.root_key + os.sep)

    def display_path(self, key):
        """Путь для показа: относительно папки проекта, если файл внутри неё."""
        raw = self.raw_paths.get(key, key)
        if self.inside(key):
            return os.path.relpath(raw, self.root)
        return raw

    def roots(self):
        """Головные сборки: сборки, которые не входят ни в одну другую."""
        keys = [k for k, d in self.docs.items() if d.kind == "assembly" and not self.parents.get(k)]
        return sorted(keys, key=self._sort_key)

    def loose_parts(self):
        keys = [k for k, d in self.docs.items() if d.kind == "part" and not self.parents.get(k)]
        return sorted(keys, key=self._sort_key)

    def unlinked_documents(self):
        """Чертежи и спецификации, не связанные ни с одной моделью проекта."""
        models = {k for k, d in self.docs.items() if d.kind in ("part", "assembly")}
        result = []
        for k, d in self.docs.items():
            if d.kind in ("drawing", "spec") and not ({norm(r) for r in d.refs} & models):
                result.append(k)
        return sorted(result, key=self._sort_key)

    def worst_severity(self, key):
        issues = self.issues_by_key.get(key)
        if not issues:
            return None
        return min((i.severity for i in issues), key=SEVERITY_ORDER.get)

    def counts(self):
        result = defaultdict(int)
        for d in self.docs.values():
            result[d.kind] += 1
        for i in self.issues:
            result[i.severity] += 1
        return result

    def _sort_key(self, key):
        d = self.docs.get(key)
        return ((d.designation or d.name or "").lower() if d else "", self.display_path(key).lower())

    # ---------- связи ----------

    def _remember(self, path):
        key = norm(path)
        self.raw_paths.setdefault(key, path)
        return key

    def _link(self):
        for key, d in self.docs.items():
            if d.kind == "assembly":
                counts = {}
                for r in d.refs:
                    rk = self._remember(r)
                    counts[rk] = counts.get(rk, 0) + 1
                self.components[key] = list(counts.items())
                for rk in counts:
                    self.parents[rk].add(key)
            elif d.kind == "drawing":
                for rk in dict.fromkeys(self._remember(r) for r in d.refs):
                    self.drawings_of[rk].append(key)
            elif d.kind == "spec":
                for rk in dict.fromkeys(self._remember(r) for r in d.refs):
                    self.specs_of[rk].append(key)

    # ---------- проверки ----------

    def _add(self, severity, key, message):
        self.issues.append(Issue(severity, key, message))

    def _check(self):
        by_designation = defaultdict(list)

        for key, d in self.docs.items():
            if d.error:
                self._add(WARNING, key, f"Прочитано не полностью: {d.error}")

            for r in dict.fromkeys(d.refs):
                rk = norm(r)
                if not self.exists(rk):
                    self._add(ERROR, key, f"Битая ссылка, файл не найден: {r}")
                elif not self.inside(rk):
                    self._add(WARNING, key, f"Ссылка за пределы папки проекта: {r}")

            if d.kind in ("part", "assembly"):
                self._check_model(key, d)
                if d.designation.strip():
                    by_designation[d.designation.strip()].append(key)
            elif d.kind == "drawing":
                self._check_drawing(key, d)

        for designation, keys in by_designation.items():
            if len(keys) > 1:
                others = ", ".join(self.display_path(k) for k in keys)
                for k in keys:
                    self._add(ERROR, k, f"Обозначение {designation} повторяется у {len(keys)} файлов: {others}")

    def _check_model(self, key, d: DocInfo):
        designation, name = d.designation.strip(), d.name.strip()
        if not designation:
            self._add(WARNING, key, "Не задано обозначение")
        if not name:
            self._add(WARNING, key, "Не задано наименование")
        if designation and name:
            ext = os.path.splitext(d.path)[1]
            expected = file_name(designation, name, ext)
            if os.path.basename(d.path).lower() != expected.lower():
                self._add(WARNING, key, f"Имя файла не по шаблону, ожидается «{expected}»")
        if d.kind == "part":
            if not self.parents.get(key):
                self._add(INFO, key, "Деталь не входит ни в одну сборку проекта")
            if not self.drawings_of.get(key):
                self._add(INFO, key, "Нет чертежа")
        elif d.kind == "assembly" and not self.specs_of.get(key):
            self._add(INFO, key, "Нет спецификации")

    def _check_drawing(self, key, d: DocInfo):
        if not d.refs:
            self._add(INFO, key, "Чертёж не связан с моделью (нет ассоциативных видов)")
            return
        stamp = d.designation.strip()
        for mk in dict.fromkeys(norm(r) for r in d.refs):
            model = self.docs.get(mk)
            if model is None or not model.designation.strip() or not stamp:
                continue
            # Допускается код документа после обозначения: «АБВГ.000.00 СБ»
            if not stamp.startswith(model.designation.strip()):
                self._add(
                    WARNING,
                    key,
                    f"Обозначение в штампе «{stamp}» не совпадает с моделью «{model.designation.strip()}»",
                )
