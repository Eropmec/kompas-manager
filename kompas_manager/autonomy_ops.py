"""Операции для автономности изделия и наполнения его из других изделий и библиотеки.

- localize: внешние файлы (библиотека, другие проекты) копируются в папку ссылающегося документа,
  ссылки перепривязываются; цепочки (библиотечная сборка со своими деталями) обрабатываются целиком;
- paste_node: узел из другого изделия копируется в выбранную сборку и полностью отвязывается;
- level_up: новая головная сборка, в которую вставляется существующее изделие как есть;
- insert_library: копия библиотечного элемента сразу вставляется в выбранную сборку.
"""
import os
import shutil

from kompas_manager.core.backup import Backup
from kompas_manager.core.localize import Placement
from kompas_manager.core.model import norm
from kompas_manager.core.naming import file_name
from kompas_manager.structure_ops import relink_files, transfer

LINKED = (".a3d", ".cdw", ".spw")


def localize(K, root, docs, show=False, log=print, backup=True, known=None):
    """Сделать документы docs (и всё, на что они ссылаются) независимыми от файлов вне изделия.
    known — {norm-путь внешнего файла: уже сделанная копия в изделии} (по реестру происхождения).
    Возвращает (созданные файлы, отсутствующие внешние файлы, {копия: исходный файл})."""
    placement = Placement(root)
    known = {k: v for k, v in (known or {}).items() if os.path.exists(v)}
    mapping, referrers, created, missing, sources = {}, [], [], [], {}
    queue = [d for d in dict.fromkeys(docs) if os.path.splitext(d)[1].lower() in LINKED]
    seen = set()
    session = K.Session(show, log)
    try:
        app = session.app
        while queue:
            path = queue.pop(0)
            if norm(path) in seen:
                continue
            seen.add(norm(path))
            doc = K.open_doc(app, path, visible=False, readonly=True)
            try:
                refs = list(dict.fromkeys(K.references(doc, path)))
            finally:
                K.close_doc(doc)
            has_external = False
            for r in refs:
                if not r or placement.inside(r):
                    continue
                if not os.path.exists(r):
                    missing.append(r)
                    continue
                has_external = True
                nk = norm(r)
                if nk not in mapping and nk in known:
                    mapping[nk] = known[nk]
                if nk not in mapping:
                    target, reuse = placement.target(r, path)
                    if not reuse:
                        os.makedirs(os.path.dirname(target), exist_ok=True)
                        shutil.copy2(r, target)
                        created.append(target)
                        sources[target] = r
                        log(f"  скопирован в изделие: {os.path.relpath(target, root)}")
                        if os.path.splitext(target)[1].lower() in LINKED:
                            queue.append(target)  # у копии свои внешние ссылки (библиотечная сборка)
                    mapping[nk] = target
            if has_external:
                referrers.append(path)
        if not mapping:
            log("Внешних ссылок нет — изделие автономно")
            return created, missing, sources
        if backup:
            originals = [p for p in referrers if p not in created]
            if originals:
                Backup.create(root, originals, "Перенос внешних файлов в изделие")
        n = relink_files(K, app, referrers, mapping, log)
        log(f"Перепривязано ссылок: {n}; скопировано файлов: {len(created)}")
        return created, missing, sources
    finally:
        session.close(log)


def paste_node(K, root, plan, target_assembly, show=False, log=print, known=None):
    """Скопировать узел другого изделия в сборку и отвязать его от всех прежних файлов.
    Возвращает (новый головной файл узла, созданные файлы, отсутствующие, {копия внешнего файла: источник})."""
    created = transfer(K, plan, root, target_assembly, show=show, log=log)
    more, missing, sources = localize(K, root, created, show=show, log=log, backup=False, known=known)
    return plan.new_root, created + more, missing, sources


def level_up(K, folder, designation, name, head_path, show=False, log=print):
    """Создать новую головную сборку и вставить в неё существующее изделие без изменений."""
    path = os.path.join(folder, file_name(designation, name, ".a3d"))
    if os.path.exists(path):
        raise RuntimeError(f"файл уже существует: {os.path.basename(path)}")
    session = K.Session(show, log)
    try:
        doc = K.new_doc(session.app, path, visible=show)
        try:
            K.write_props(doc, designation, name)
            how = K.add_component(doc, head_path, log)
            doc.Save()
        finally:
            K.close_doc(doc)
        log(f"Создана сборка {os.path.basename(path)}, в неё вставлено {os.path.basename(head_path)} ({how})")
        return path
    finally:
        session.close(log)


def insert_library(K, root, plan, element, target_assembly, count=1, show=False, log=print, known=None):
    """Копия библиотечного элемента (или существующий файл того же типоразмера) — сразу в сборку.
    Возвращает (путь в изделии, {копии состава библиотечной сборки: источник})."""
    from kompas_manager.library_ops import insert_copy

    path = insert_copy(K, plan, element, show=show, log=log)
    sources = {}
    if os.path.splitext(path)[1].lower() == ".a3d" and not plan.reuse:
        # состав библиотечной сборки — в изделие
        _c, _m, sources = localize(K, root, [path], show=show, log=log, backup=False, known=known)
    Backup.create(root, [target_assembly], "Вставка из библиотеки")
    session = K.Session(show, log)
    try:
        doc = K.open_doc(session.app, target_assembly, visible=show, readonly=False)
        try:
            for _ in range(max(1, count)):
                K.add_component(doc, path, log)
            doc.Save()
        finally:
            K.close_doc(doc)
    finally:
        session.close(log)
    log(f"Вставлено в {os.path.basename(target_assembly)}: {os.path.basename(path)} × {max(1, count)}")
    return path, sources
