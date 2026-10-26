"""Правка готовой сборки и восстановление версий через Kompas API.

Перед каждым изменением затронутые файлы копируются в _backup (откат — «Откатить последнее»).
"""
import os

from kompas_manager.core.backup import Backup
from kompas_manager.core.model import norm
from kompas_manager.core.versions import extract_version, move_to_old, save_version
from kompas_manager.structure_ops import _new_model, relink_files


def delete_from_assembly(K, root, plan, show=False, log=print):
    """Удалить все вхождения plan.child из plan.parent и, по плану, файлы узла."""
    backup = Backup.create(root, [plan.parent] + plan.files, "Удаление из сборки")
    session = K.Session(show, log)
    try:
        app = session.app
        doc = K.open_doc(app, plan.parent, visible=show, readonly=False)
        try:
            removed = 0
            # Удаляем с конца, чтобы индексы оставшихся компонентов не сдвигались
            for c in reversed(K.components(doc)):
                if norm(c.FileName) == norm(plan.child):
                    how = K.delete_component(c, log)
                    removed += 1
            if removed:
                log(f"  удалено вхождений: {removed} ({how})")
            try:
                K.rebuild_3d(doc)
            except Exception as e:
                log(f"  перестроение: {e}")
            doc.Save()
        finally:
            K.close_doc(doc)
        doc = K.open_doc(app, plan.parent, visible=False, readonly=True)
        try:
            left = sum(1 for c in K.components(doc) if norm(c.FileName) == norm(plan.child))
        finally:
            K.close_doc(doc)
        if left:
            raise RuntimeError(f"в сборке осталось вхождений: {left}; файлы не удалялись")
    finally:
        session.close(log)
    for f in plan.files:
        try:
            backup.remove_original(f)
            log(f"  файл удалён (копия в _backup): {os.path.basename(f)}")
        except Exception as e:
            log(f"  не удалён {os.path.basename(f)}: {e}")
    return removed


def append_to_assembly(K, root, plan, templates=None, show=False, log=print):
    """Создать новые элементы по AppendPlan и вставить их в существующую сборку."""
    templates = templates or {}
    backup = Backup.create(root, [plan.assembly], "Добавление в сборку")
    session = K.Session(show, log)
    try:
        app = session.app
        for it in plan.items:
            os.makedirs(os.path.dirname(it.path), exist_ok=True)
            doc = _new_model(K, app, it.path, templates.get(it.node.kind, ""), show)
            backup.created(it.path)
            try:
                K.write_props(doc, it.designation, it.name)
                for comp, count in it.components:
                    for _ in range(count):
                        K.add_component(doc, comp, log)
                doc.Save()
            finally:
                K.close_doc(doc)
            log(f"  создан: {os.path.basename(it.path)}")
        doc = K.open_doc(app, plan.assembly, visible=show, readonly=False)
        try:
            for path, count in plan.direct:
                for _ in range(count):
                    K.add_component(doc, path, log)
            doc.Save()
        finally:
            K.close_doc(doc)
        log(f"Вставлено в {os.path.basename(plan.assembly)}: {sum(c for _p, c in plan.direct)} вхождений")
        return [it.path for it in plan.items]
    finally:
        session.close(log)


def restore_version(K, project, plan, move_orphans=True, show=False, log=print):
    """Сохранить текущий узел как версию, распаковать выбранную, перепривязать родителей."""
    current = save_version(project, plan.current_key, f"Автосохранение перед восстановлением версии от {plan.version.time}")
    log(f"Текущее состояние сохранено: {os.path.basename(current.path)}")
    if plan.parents:
        Backup.create(project.root, plan.parents, "Восстановление версии узла")
    files = extract_version(plan.version, project.root)
    log(f"Распаковано файлов: {len(files)}")
    if plan.parents:
        session = K.Session(show, log)
        try:
            n = relink_files(K, session.app, plan.parents, plan.relink, log)
            log(f"Перепривязано в родительских сборках: {n}")
        finally:
            session.close(log)
    if move_orphans and plan.orphans:
        moved = move_to_old(project.root, plan.orphans)
        log(f"Файлы текущей версии, которых нет в восстановленной, убраны в _old: {len(moved)}")
    return current
