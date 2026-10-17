"""Выполнение плана переобозначения через Kompas API.

Порядок (проверен на прототипе):
1. резервная копия всех затронутых файлов;
2. модели: копия под новым именем, запись обозначения и наименования;
3. сборки: замена компонентов на новые файлы;
4. чертежи: перепривязка видов, перестроение, штамп, сохранение под новым именем;
5. спецификации: перепривязка связанных документов, штамп, сохранение под новым именем;
6. удаление старых файлов (их копии остаются в резервной папке).

Старые файлы удаляются только если все шаги прошли без ошибок.
"""
import os
import shutil

from kompas_manager.core.backup import Backup
from kompas_manager.core.model import norm
from kompas_manager.core.settings import FILE_NAME as SETTINGS_FILE


class RenameResult:
    def __init__(self):
        self.errors = []
        self.warnings = []
        self.backup = None
        self.done = False


def check_not_open(K, app, paths):
    """Файлы, открытые в КОМПАСе: переименовывать их нельзя."""
    return [p for p in paths if K.find_open(app, p) is not None]


def execute(plan, K, show=False, log=print, progress=None):
    res = RenameResult()
    ops = plan.ops
    total = len(ops) + 2
    step = [0]

    def tick(text):
        step[0] += 1
        if progress:
            progress(step[0], total, text)

    def current_path(op):
        """Где сейчас лежит рабочая версия файла: модели к этому шагу уже скопированы под новым именем."""
        return op.new_path if op.kind in ("part", "assembly") and op.renamed else op.old_path

    session = K.Session(show, log)
    try:
        app = session.app
        opened = check_not_open(K, app, plan.affected_paths())
        if opened:
            res.errors.append("Закройте в КОМПАСе файлы: " + ", ".join(os.path.basename(p) for p in opened))
            return res

        extra = [os.path.join(plan.root, SETTINGS_FILE)]
        extra = [p for p in extra if os.path.isfile(p)]  # настройки проекта тоже откатываются
        res.backup = Backup.create(plan.root, plan.affected_paths() + extra, "Переобозначение")
        log(f"Резервная копия: {res.backup.folder}")
        tick("резервная копия")

        def fail(op, what, e):
            msg = f"{os.path.basename(op.old_path)}: {what}: {e}"
            res.errors.append(msg)
            log("  ОШИБКА " + msg)

        # 2. Модели: копия и свойства
        for op in [o for o in ops if o.kind in ("part", "assembly")]:
            tick(os.path.basename(op.new_path))
            try:
                if op.renamed:
                    shutil.copy2(op.old_path, op.new_path)
                    res.backup.created(op.new_path)
                if op.retitle:
                    doc = K.open_doc(app, op.new_path, visible=show, readonly=False)
                    try:
                        K.write_props(doc, op.new_designation, op.new_name)
                        doc.Save()
                        got = K.read_props(doc)
                    finally:
                        K.close_doc(doc)
                    if tuple(got) != (op.new_designation, op.new_name):
                        res.warnings.append(f"{os.path.basename(op.new_path)}: свойства прочитались как {got}")
                log(f"  модель: {os.path.basename(op.old_path)} -> {os.path.basename(op.new_path)}")
            except Exception as e:
                fail(op, "модель", e)

        # 3. Сборки: компоненты
        for op in [o for o in ops if o.kind == "assembly" and o.relink]:
            path = current_path(op)
            try:
                links = dict(op.relink)
                doc = K.open_doc(app, path, visible=show, readonly=False)
                try:
                    replaced = 0
                    for c in K.components(doc):
                        new = links.get(norm(c.FileName))
                        if new:
                            c.FileName = new
                            c.Update()
                            replaced += 1
                    try:
                        K.rebuild_3d(doc)
                    except Exception as e:
                        res.warnings.append(f"{os.path.basename(path)}: перестроение сборки: {e}")
                    doc.Save()
                finally:
                    K.close_doc(doc)
                log(f"  сборка {os.path.basename(path)}: заменено компонентов {replaced}")
            except Exception as e:
                fail(op, "компоненты сборки", e)

        # 4–5. Чертежи и спецификации
        for op in [o for o in ops if o.kind in ("drawing", "spec")]:
            tick(os.path.basename(op.new_path))
            try:
                doc = K.open_doc(app, op.old_path, visible=show, readonly=False)
                try:
                    links = dict(op.relink)
                    if op.kind == "drawing" and links:
                        n = 0
                        for _v, av in K.association_views(doc):
                            new = links.get(norm(av.SourceFileName))
                            if new:
                                av.SourceFileName = new
                                av.Update()
                                n += 1
                        log(f"  чертёж {os.path.basename(op.old_path)}: перепривязано видов {n}")
                        try:
                            K.rebuild_2d(doc)
                        except Exception as e:
                            res.warnings.append(f"{os.path.basename(op.old_path)}: перестроение: {e}")
                    if op.kind == "spec" and links:
                        n = K.spec_relink(doc, links)
                        log(f"  спецификация {os.path.basename(op.old_path)}: перепривязано документов {n}")
                    if op.retitle:
                        target = (op.new_designation, op.new_name)
                        if tuple(K.stamp_values(doc)) != target:
                            K.write_stamp(doc, *target)
                    if op.renamed:
                        doc.SaveAs(op.new_path)
                        res.backup.created(op.new_path)
                    else:
                        doc.Save()
                finally:
                    K.close_doc(doc)
                if op.renamed and not os.path.exists(op.new_path):
                    raise RuntimeError("файл под новым именем не появился")
            except Exception as e:
                fail(op, "документ", e)

        # 6. Старые файлы
        tick("завершение")
        if res.errors:
            log("Были ошибки: старые файлы не удалены. Проверьте журнал или выполните откат.")
            return res
        for op in [o for o in ops if o.renamed]:
            try:
                res.backup.remove_original(op.old_path)
            except Exception as e:
                res.warnings.append(f"{os.path.basename(op.old_path)}: не удалён старый файл: {e}")
        res.done = True
        log("Переобозначение завершено")
        return res
    finally:
        session.close(log)
