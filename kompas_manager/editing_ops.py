"""Правка готовой сборки и восстановление версий через Kompas API.

Перед каждым изменением затронутые файлы копируются в _backup (откат — «Откатить последнее»).
"""
import os

from kompas_manager.core.backup import Backup
from kompas_manager.core.model import norm
from kompas_manager.core.versions import extract_version, move_to_old, save_version
from kompas_manager.structure_ops import _new_model, relink_files


def _count(K, doc, child):
    return sum(1 for c in K.components(doc) if norm(c.FileName) == norm(child))


def _delete_instances(K, doc, child, log, limit=None):
    """Удалить вхождения child из открытой сборки (все или не больше limit): API7, затем API5.
    Если удалилось не всё нужное — исключение до сохранения, сборка не меняется."""
    before = _count(K, doc, child)
    want = before if limit is None else min(limit, before)
    removed, how = 0, ""
    # С конца, чтобы индексы оставшихся компонентов не сдвигались
    for c in reversed(K.components(doc)):
        if removed >= want:
            break
        if norm(c.FileName) != norm(child):
            continue
        try:
            how = K.delete_component(c, log)
            removed += 1
        except Exception as e:
            log(f"  {e}")
            break
    left = _count(K, doc, child)
    if before - left < want:
        log(f"  после API7 осталось вхождений: {left}, пробую API5")
        try:
            K.delete_components5(doc, child, log, limit=None if limit is None else want - (before - left))
            how = "API5 ksDocument3D.DeleteObject"
        except Exception as e:
            log(f"  API5: {e}")
        left = _count(K, doc, child)
    removed = before - left
    if removed < want:
        raise RuntimeError(f"КОМПАС не удалил вхождения ({want - removed}); сборка не сохранена, файлы не удалялись")
    if removed:
        log(f"  удалено вхождений: {removed} ({how})")
    return removed


def move_occurrence(K, root, old_parent, new_parent, child, show=False, log=print):
    """Перенести одно вхождение child из сборки old_parent в new_parent (файлы не копируются)."""
    Backup.create(root, [old_parent, new_parent], "Перенос в другую сборку")
    session = K.Session(show, log)
    try:
        app = session.app
        target = K.open_doc(app, new_parent, visible=show, readonly=False)
        try:
            how = K.add_component(target, child, log)
            log(f"  {os.path.basename(child)} добавлен в {os.path.basename(new_parent)} ({how})")
            source = K.open_doc(app, old_parent, visible=show, readonly=False)
            try:
                _delete_instances(K, source, child, log, limit=1)
                source.Save()
            finally:
                K.close_doc(source)
            target.Save()
        finally:
            K.close_doc(target)
    finally:
        session.close(log)
    log(f"Перенесено: {os.path.basename(child)} из {os.path.basename(old_parent)} в {os.path.basename(new_parent)}")


def delete_from_assembly(K, root, plan, show=False, log=print):
    """Удалить все вхождения plan.child из plan.parent и, по плану, файлы узла.
    Возвращает число удалённых вхождений; резервная копия — в _backup (откат Ctrl+Z)."""
    return delete_from_assemblies(K, root, [plan], show=show, log=log)


def delete_from_assemblies(K, root, plans, show=False, log=print):
    """Несколько удалений одной операцией (одна резервная копия). Сначала меняются все сборки;
    файлы удаляются, только если из всех сборок вхождения ушли."""
    parents = list(dict.fromkeys(p.parent for p in plans))
    files = list(dict.fromkeys(f for p in plans for f in p.files if norm(f) not in {norm(x) for x in parents}))
    backup = Backup.create(root, parents + files, "Удаление из сборки")
    removed = 0
    session = K.Session(show, log)
    try:
        app = session.app
        for parent in parents:
            children = list(dict.fromkeys(p.child for p in plans if p.parent == parent))
            log(f"{os.path.basename(parent)}:")
            doc = K.open_doc(app, parent, visible=show, readonly=False)
            try:
                for child in children:
                    log(f"  удаляется {os.path.basename(child)}")
                    removed += _delete_instances(K, doc, child, log)
                try:
                    K.rebuild_3d(doc)
                except Exception as e:
                    log(f"  перестроение: {e}")
                doc.Save()
            finally:
                K.close_doc(doc)
            doc = K.open_doc(app, parent, visible=False, readonly=True)
            try:
                left = sum(_count(K, doc, c) for c in children)
            finally:
                K.close_doc(doc)
            if left:
                raise RuntimeError(f"{os.path.basename(parent)}: после сохранения осталось вхождений {left}; "
                                   "файлы не удалялись")
    finally:
        session.close(log)
    for f in files:
        try:
            backup.remove_original(f)
            log(f"  файл удалён (копия в _backup): {os.path.basename(f)}")
        except Exception as e:
            log(f"  не удалён {os.path.basename(f)}: {e}")
    return removed


def _matrix(K, c, log):
    try:
        return K.get_matrix(c)
    except Exception as e:
        log(f"  положение {os.path.basename(c.FileName)} не прочитано: {e}")
        return None


def combine_to_subassembly(K, root, parent, children, new_path, designation, name, template="",
                           show=False, log=print):
    """«Объединить компоненты в подсборку»: все вхождения children из сборки parent переносятся
    в новую сборку new_path (с теми же положениями), новая сборка вставляется в parent."""
    backup = Backup.create(root, [parent], "Объединение в подсборку")
    want = {norm(c) for c in children}
    lost = 0
    session = K.Session(show, log)
    try:
        app = session.app
        doc = K.open_doc(app, parent, visible=show, readonly=False)
        try:
            items = [(c.FileName, _matrix(K, c, log)) for c in K.components(doc) if norm(c.FileName) in want]
            if not items:
                raise RuntimeError("в сборке не найдены выбранные компоненты")
            os.makedirs(os.path.dirname(new_path), exist_ok=True)
            sub = _new_model(K, app, new_path, template, show)
            backup.created(new_path)
            try:
                K.write_props(sub, designation, name)
                for path, m in items:
                    if not K.insert_part(sub, path, m, log):
                        lost += 1
                sub.Save()
            finally:
                K.close_doc(sub)
            log(f"  создана подсборка {os.path.basename(new_path)}: компонентов {len(items)}")
            for child in dict.fromkeys(children):
                _delete_instances(K, doc, child, log)
            K.insert_part(doc, new_path, None, log)
            try:
                K.rebuild_3d(doc)
            except Exception as e:
                log(f"  перестроение: {e}")
            doc.Save()
        finally:
            K.close_doc(doc)
    finally:
        session.close(log)
    if lost:
        log(f"  внимание: положение не перенесено у компонентов: {lost}")
    log("  сопряжения выбранных компонентов с остальной сборкой не переносятся — проверьте сборку в КОМПАСе")
    return new_path, lost


def destroy_subassembly(K, root, parent, sub_path, show=False, log=print):
    """«Разрушить»: компоненты подсборки sub_path переходят в сборку parent в тех же положениях,
    вхождения подсборки удаляются. Файл подсборки остаётся (выпадет из структуры — уйдёт в _old при архивации)."""
    from kompas_manager.core.geometry import IDENTITY, compose, detect_layout

    Backup.create(root, [parent], "Разрушение подсборки")
    lost = 0
    session = K.Session(show, log)
    try:
        app = session.app
        sub = K.open_doc(app, sub_path, visible=False, readonly=True)
        try:
            inner = [(c.FileName, _matrix(K, c, log)) for c in K.components(sub)]
        finally:
            K.close_doc(sub)
        doc = K.open_doc(app, parent, visible=show, readonly=False)
        try:
            outers = [_matrix(K, c, log) for c in K.components(doc) if norm(c.FileName) == norm(sub_path)]
            if not outers:
                raise RuntimeError("подсборка не найдена в сборке")
            layout = detect_layout([m for m in outers + [m for _p, m in inner] if m])
            for om in outers:
                for path, im in inner:
                    m = compose(om or IDENTITY, im, layout) if im is not None else None
                    if not K.insert_part(doc, path, m, log):
                        lost += 1
            _delete_instances(K, doc, sub_path, log)
            try:
                K.rebuild_3d(doc)
            except Exception as e:
                log(f"  перестроение: {e}")
            doc.Save()
        finally:
            K.close_doc(doc)
    finally:
        session.close(log)
    log(f"Подсборка {os.path.basename(sub_path)} разрушена: в {os.path.basename(parent)} добавлено компонентов "
        f"{len(inner) * len(outers)}" + (f", без положения: {lost}" if lost else ""))
    return lost


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
