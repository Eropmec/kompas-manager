"""Операции со структурой проекта через Kompas API (проверены на прототипе).

- create_structure: создать детали и сборки по плану, вставить компоненты;
- transfer: скопировать узел в другой проект с перепривязкой и вставкой в сборку;
- relink_copied_folder: после копирования папки перепривязать ссылки, ведущие в оригинал.
"""
import os
import shutil

from kompas_manager.core.backup import Backup
from kompas_manager.core.model import norm
from kompas_manager.core.transfer import folder_relink_map


def _new_model(K, app, path, template, show):
    if template:
        shutil.copy2(template, path)
        return K.open_doc(app, path, visible=show, readonly=False)
    return K.new_doc(app, path, visible=show)


def create_structure(K, items, templates=None, show=False, log=print, progress=None):
    """items — из core.structure.plan_files. Возвращает список созданных файлов."""
    templates = templates or {}
    created = []
    session = K.Session(show, log)
    try:
        app = session.app
        for i, it in enumerate(items):
            if progress:
                progress(i, len(items), os.path.basename(it.path))
            os.makedirs(os.path.dirname(it.path), exist_ok=True)
            doc = _new_model(K, app, it.path, templates.get(it.node.kind, ""), show)
            created.append(it.path)
            try:
                K.write_props(doc, it.designation, it.name)
                for comp, count in it.components:
                    for _ in range(count):
                        K.add_component(doc, comp, log)
                doc.Save()
            finally:
                K.close_doc(doc)
            log(f"  создан: {os.path.basename(it.path)}"
                + (f" (компонентов: {sum(c for _p, c in it.components)})" if it.components else ""))
        if progress:
            progress(len(items), len(items), "")
        return created
    finally:
        session.close(log)


def relink_files(K, app, paths, mapping, log=print):
    """Перепривязать ссылки в документах paths по mapping (norm-ключ -> новый путь). Возвращает число замен."""
    total = 0
    for path in paths:
        ext = os.path.splitext(path)[1].lower()
        if ext not in (".a3d", ".cdw", ".spw"):
            continue
        doc = K.open_doc(app, path, visible=False, readonly=False)
        try:
            n = 0
            if ext == ".a3d":
                for c in K.components(doc):
                    new = mapping.get(norm(c.FileName))
                    if new:
                        c.FileName = new
                        c.Update()
                        n += 1
            elif ext == ".cdw":
                for _v, av in K.association_views(doc):
                    new = mapping.get(norm(av.SourceFileName))
                    if new:
                        av.SourceFileName = new
                        av.Update()
                        n += 1
                if n:
                    try:
                        K.rebuild_2d(doc)
                    except Exception as e:
                        log(f"  {os.path.basename(path)}: перестроение: {e}")
            else:
                links = {norm(r): mapping[norm(r)] for r in K.spec_attached(doc) if norm(r) in mapping}
                if links:
                    n = K.spec_relink(doc, links)
            if n:
                doc.Save()
                log(f"  {os.path.basename(path)}: перепривязано ссылок {n}")
            total += n
        finally:
            K.close_doc(doc)
    return total


def transfer(K, plan, target_root, target_assembly="", show=False, log=print):
    """Скопировать узел по TransferPlan; при target_assembly — вставить узел в неё компонентом."""
    backup = None
    if target_assembly:
        backup = Backup.create(target_root, [target_assembly], "Вставка узла из другого проекта")
    created = []
    for old_key, new in plan.files.items():
        os.makedirs(os.path.dirname(new), exist_ok=True)
        shutil.copy2(plan.sources.get(old_key, old_key), new)
        created.append(new)
        if backup is not None:
            backup.created(new)
    log(f"Скопировано файлов: {len(created)}")
    session = K.Session(show, log)
    try:
        app = session.app
        mapping = {k: v for k, v in plan.files.items()}
        relink_files(K, app, created, mapping, log)
        if target_assembly:
            doc = K.open_doc(app, target_assembly, visible=show, readonly=False)
            try:
                how = K.add_component(doc, plan.new_root, log)
                doc.Save()
            finally:
                K.close_doc(doc)
            log(f"Узел вставлен в {os.path.basename(target_assembly)} ({how})")
        return created
    finally:
        session.close(log)


def relink_copied_folder(K, old_root, new_root, show=False, log=print):
    """Проверить копию папки и перепривязать ссылки, ведущие в оригинал. Возвращает число замен."""
    from kompas_manager.scanner import list_files

    files = list_files(new_root)
    session = K.Session(show, log)
    try:
        app = session.app
        refs = []
        for path in files:
            if os.path.splitext(path)[1].lower() in (".a3d", ".cdw", ".spw"):
                doc = K.open_doc(app, path, visible=False, readonly=True)
                try:
                    refs += K.references(doc, path)
                finally:
                    K.close_doc(doc)
        mapping = folder_relink_map(old_root, new_root, refs)
        if not mapping:
            log("Все ссылки копии ведут на её собственные файлы или в библиотеку")
            return 0
        return relink_files(K, app, files, mapping, log)
    finally:
        session.close(log)
