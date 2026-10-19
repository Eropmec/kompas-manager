"""Обёртка над COM-интерфейсом КОМПАС-3D (API7 + API5) для прототипа.

Все вызовы Kompas API собраны здесь, чтобы при расхождении с реальным API
(версия v24) исправлять одно место, а не скрипты.
"""
import os
import sys
import tempfile
import types

from naming import file_name  # noqa: F401  (используется скриптами через K.file_name)


def _setup_gen_path():
    """В exe pywin32 должен генерировать обёртки библиотек типов в папку с правом записи."""
    if not getattr(sys, "frozen", False):
        return
    import win32com

    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    gen = os.path.join(base, "KompasManager", "gen_py")
    os.makedirs(gen, exist_ok=True)
    win32com.__gen_path__ = gen
    mod = sys.modules.get("win32com.gen_py")
    if mod is None:
        mod = types.ModuleType("win32com.gen_py")
        sys.modules["win32com.gen_py"] = mod
    mod.__path__ = [gen]


_setup_gen_path()

import pythoncom  # noqa: E402
from win32com.client import Dispatch, GetActiveObject, gencache  # noqa: E402

gencache.is_readonly = False

# Библиотеки типов КОМПАС: API7, API5 и константы
KAPI7_TLB = "{69AC2981-37C0-4379-84FD-5DD2F3C0A520}"
KAPI5_TLB = "{0422828C-F174-495E-AC5D-D31014DBBE87}"
CONST_TLB = "{75C9F5D0-B5B8-4526-8681-9903C567D2ED}"

EXT_TYPES = {
    ".m3d": "деталь",
    ".a3d": "сборка",
    ".cdw": "чертёж",
    ".spw": "спецификация",
}

# Ячейки основной надписи
STAMP_NAME = 1         # наименование
STAMP_DESIGNATION = 2  # обозначение


def _module(tlb):
    mod = gencache.EnsureModule(tlb, 0, 1, 0)
    if mod is None:
        raise RuntimeError(
            f"Не найдена библиотека типов {tlb}. "
            "Проверьте, что КОМПАС-3D установлен и Python той же разрядности (64 бит)."
        )
    return mod


api7 = _module(KAPI7_TLB)
api5 = _module(KAPI5_TLB)
const = _module(CONST_TLB).constants


# ---------- общие помощники ----------

def cast(obj, iface):
    """Привести COM-объект к интерфейсу из библиотеки типов."""
    return iface(obj._oleobj_.QueryInterface(iface.CLSID, pythoncom.IID_IDispatch))


def try_cast(obj, iface):
    try:
        return cast(obj, iface)
    except Exception:
        return None


def items(coll, *method_names):
    """Перебор коллекции API7: пробует методы доступа по индексу по очереди."""
    if coll is None:
        return
    for i in range(coll.Count):
        for m in method_names + ("Item",):
            f = getattr(coll, m, None)
            if f is not None:
                yield f(i)
                break


def norm(path):
    """Путь для сравнения: абсолютный, без учёта регистра."""
    return os.path.normcase(os.path.abspath(path)) if path else ""


def public_props(obj):
    """Список свойств типизированного COM-объекта (для разведки API)."""
    return sorted(getattr(obj, "_prop_map_get_", {}).keys())


def list_kompas_files(path):
    if os.path.isfile(path):
        return [os.path.abspath(path)]
    result = []
    for root, _dirs, files in os.walk(path):
        for f in files:
            if os.path.splitext(f)[1].lower() in EXT_TYPES:
                result.append(os.path.join(root, f))
    return sorted(result)


def ext_of(path):
    return os.path.splitext(path)[1].lower()


# ---------- приложение и документы ----------

def is_running():
    """Запущен ли уже КОМПАС (например, пользователь работает в нём)."""
    try:
        GetActiveObject("Kompas.Application.7")
        return True
    except Exception:
        return False


def connect():
    raw = Dispatch("Kompas.Application.7")
    app = try_cast(raw, api7.IApplication)
    if app is None:
        app = cast(raw, api7.IKompasAPIObject).Application
    return app


class Session:
    """КОМПАС на время одной операции.

    Если КОМПАС не был запущен, он запускается в фоне без окна
    (или с окном при show=True) и закрывается в конце.
    Если пользователь уже работает в КОМПАСе, используется он: окно не прячется
    и не закрывается.
    """

    def __init__(self, show=False, log=print):
        self.started = not is_running()
        self.app = connect()
        if self.started:
            self.app.Visible = show
            try:
                # Диалоги КОМПАСа не показывать, на вопросы отвечать «Нет»,
                # иначе скрытый КОМПАС может ждать ответа, которого никто не даст.
                self.app.HideMessage = const.ksHideMessageNo
            except Exception as e:
                log(f"  не удалось отключить диалоги КОМПАСа: {e}")
            log("  КОМПАС запущен в фоне" + (" с окном" if show else " без окна"))
        else:
            log("  КОМПАС уже был запущен — используется он, окно не скрывается и не закрывается")

    def close(self, log=print):
        if not self.started:
            return
        try:
            self.app.Quit()
            log("  фоновый КОМПАС закрыт")
        except Exception as e:
            log(f"  не удалось закрыть фоновый КОМПАС: {e}")


def connect5():
    raw = Dispatch("Kompas.Application.5")
    return cast(raw, api5.KompasObject)


def open_doc(app, path, visible=False, readonly=True):
    doc = app.Documents.Open(path, visible, readonly)
    if doc is None:
        raise RuntimeError(f"КОМПАС не открыл файл: {path}")
    return doc


def close_doc(doc):
    doc.Close(getattr(const, "kdDoNotSaveChanges", 0))


# ---------- 3D ----------

def top_part(doc):
    return cast(doc, api7.IKompasDocument3D).TopPart


def read_props(doc):
    tp = top_part(doc)
    return tp.Marking, tp.Name


def write_props(doc, designation, name):
    tp = top_part(doc)
    tp.Marking = designation
    tp.Name = name
    tp.Update()


def components(doc):
    return list(items(top_part(doc).Parts, "Part"))


# ---------- переменные 3D ----------

def _wrap(obj, iface):
    """Элемент массива COM: сырой PyIDispatch или уже обёрнутый объект -> интерфейс."""
    if obj is None:
        return None
    if hasattr(obj, "_oleobj_"):
        return try_cast(obj, iface) or obj
    try:
        return iface(obj)
    except Exception:
        return obj


def _first_attr(obj, names, default=None):
    for n in names:
        try:
            value = getattr(obj, n)
        except Exception:
            continue
        if value is not None:
            return value
    return default


def var_info(v):
    return {
        "name": _first_attr(v, ("Name",), ""),
        "expression": _first_attr(v, ("Expression",), ""),
        "value": _first_attr(v, ("Value",), None),
        "external": bool(_first_attr(v, ("External",), False)),
        "info": bool(_first_attr(v, ("IsInformation", "Information", "InformationVariable"), False)),
        "note": _first_attr(v, ("Note", "Comment"), ""),
    }


def feature(part):
    f = try_cast(part, api7.IFeature7)
    if f is None:
        raise RuntimeError("Не удалось получить IFeature7 для детали")
    return f


def variable_objects(part, external=True, in_source=True):
    raw = feature(part).Variables(external, in_source)
    if raw is None:
        return []
    if not isinstance(raw, (list, tuple)):
        raw = [raw]
    return [_wrap(v, api7.IVariable7) for v in raw]


def variables(part, external=True, in_source=True):
    """Список переменных: [{name, expression, value, external, info, note}]."""
    return [var_info(v) for v in variable_objects(part, external, in_source)]


def set_variables(doc, values, log=print):
    """Записать выражения внешних переменных модели и перестроить её.
    values: {имя: выражение}. Возвращает способ перестроения."""
    part = top_part(doc)
    f = feature(part)
    for name, expr in values.items():
        v = None
        try:
            v = f.Variable(True, True, name)
        except Exception:
            v = None
        if v is None:
            for obj in variable_objects(part, True, True):
                if _first_attr(obj, ("Name",), "") == name:
                    v = obj
                    break
        if v is None:
            raise RuntimeError(f"Нет внешней переменной {name}")
        v = _wrap(v, api7.IVariable7)
        try:
            v.Expression = str(expr)
        except Exception as e:
            log(f"  {name}: Expression не записался ({e}), пробую Value")
            v.Value = float(expr)
    for how, call in (
        ("IPart7.RebuildModel(True)", lambda: part.RebuildModel(True)),
        ("IKompasDocument3D.RebuildDocument()", lambda: cast(doc, api7.IKompasDocument3D).RebuildDocument()),
    ):
        try:
            call()
            try:
                part.Update()
            except Exception:
                pass
            return how
        except Exception as e:
            log(f"  перестроение через {how} не удалось: {e}")
    raise RuntimeError("Модель не перестроилась")


def rebuild_3d(doc):
    cast(doc, api7.IKompasDocument3D).RebuildDocument()


# ---------- 2D: чертежи ----------

def association_views(doc):
    """Ассоциативные виды чертежа: список (вид, IAssociationView)."""
    doc2d = cast(doc, api7.IKompasDocument2D)
    views = doc2d.ViewsAndLayersManager.Views
    result = []
    for v in items(views, "View"):
        av = try_cast(v, api7.IAssociationView)
        if av is not None:
            result.append((v, av))
    return result


def stamp(doc):
    sheets = doc.LayoutSheets
    sheet = next(items(sheets, "Item"), None)
    if sheet is None:
        raise RuntimeError("В документе нет листов оформления")
    return sheet.Stamp


def stamp_values(doc):
    st = stamp(doc)
    return st.Text(STAMP_DESIGNATION).Str, st.Text(STAMP_NAME).Str


def write_stamp(doc, designation, name):
    st = stamp(doc)
    st.Text(STAMP_DESIGNATION).Str = designation
    st.Text(STAMP_NAME).Str = name
    st.Update()


def rebuild_2d(doc, app5=None):
    """Перестроить чертёж: сначала через API7, иначе через API5 (документ должен быть активным)."""
    d1 = try_cast(doc, api7.IKompasDocument2D1)
    if d1 is not None and hasattr(d1, "RebuildDocument"):
        d1.RebuildDocument()
        return "API7 IKompasDocument2D1.RebuildDocument"
    if app5 is None:
        app5 = connect5()
    doc.Active = True
    app5.ActiveDocument2D().ksRebuildDocument()
    return "API5 ksDocument2D.ksRebuildDocument"


# ---------- спецификации ----------

def spec_attached(doc):
    spec = try_cast(doc, api7.ISpecificationDocument)
    if spec is None:
        raise RuntimeError("Не удалось получить ISpecificationDocument")
    result = []
    for d in items(spec.AttachedDocuments, "Item"):
        for attr in ("Name", "FileName", "PathName"):
            value = getattr(d, attr, None)
            if value:
                result.append(value)
                break
    return result


# ---------- ссылки ----------

def references(doc, path):
    """Файлы, на которые ссылается документ."""
    ext = ext_of(path)
    if ext == ".a3d":
        return [c.FileName for c in components(doc)]
    if ext == ".cdw":
        return [av.SourceFileName for _v, av in association_views(doc)]
    if ext == ".spw":
        return spec_attached(doc)
    return []


def scan(app, folder, log=print):
    """Граф ссылок проекта: {файл: [файлы, на которые он ссылается]}."""
    graph = {}
    for path in list_kompas_files(folder):
        try:
            doc = open_doc(app, path, visible=False, readonly=True)
            try:
                graph[path] = references(doc, path)
            finally:
                close_doc(doc)
        except Exception as e:
            log(f"  не удалось прочитать ссылки {os.path.basename(path)}: {e}")
            graph[path] = []
    return graph
