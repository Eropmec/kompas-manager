"""Версии узлов: архив сборки (или детали) со всем составом, чертежами и спецификациями.

Архив — zip в <изделие>/_versions/ с manifest.json внутри. Пути в архиве — относительно папки
изделия, поэтому при распаковке файлы встают на свои места и связи между ними восстанавливаются.
"""
import datetime
import json
import os
import re
import shutil
import zipfile
from dataclasses import dataclass, field

from .model import norm
from .transfer import subtree_keys

VERSIONS_DIR = "_versions"
MANIFEST = "manifest.json"


@dataclass
class Version:
    path: str  # zip
    root_rel: str  # головной файл узла
    designation: str
    name: str
    comment: str
    time: str
    files: list = field(default_factory=list)  # отн. пути

    @property
    def title(self):
        return f"{self.designation} {self.name}".strip()


def _rel(root, path):
    return os.path.relpath(path, root).replace("\\", "/")


def save_version(project, key, comment=""):
    """Упаковать узел. Возвращает Version."""
    root = project.root
    models, docs = subtree_keys(project, key)
    paths = [project.raw_paths.get(k, k) for k in models + docs]
    d = project.doc(key)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe = re.sub(r'[<>:"/\\|?*]', "_", f"{d.designation} {d.name}".strip() or "узел")
    folder = os.path.join(root, VERSIONS_DIR)
    os.makedirs(folder, exist_ok=True)
    zpath = os.path.join(folder, f"{stamp} {safe}.zip")
    n = 1
    while os.path.exists(zpath):
        n += 1
        zpath = os.path.join(folder, f"{stamp}_{n} {safe}.zip")
    files = [_rel(root, p) for p in paths]
    manifest = {
        "root": _rel(root, project.raw_paths.get(key, key)),
        "designation": d.designation,
        "name": d.name,
        "comment": comment,
        "time": datetime.datetime.now().strftime("%d.%m.%Y %H:%M"),
        "files": files,
    }
    with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as z:
        for p, rel in zip(paths, files):
            z.write(p, rel)
        z.writestr(MANIFEST, json.dumps(manifest, ensure_ascii=False, indent=2))
    return _version(zpath, manifest)


def _version(zpath, m):
    return Version(zpath, m["root"], m.get("designation", ""), m.get("name", ""),
                   m.get("comment", ""), m.get("time", ""), list(m.get("files", [])))


def read_version(zpath):
    with zipfile.ZipFile(zpath) as z:
        return _version(zpath, json.loads(z.read(MANIFEST).decode("utf-8")))


def list_versions(root):
    folder = os.path.join(root, VERSIONS_DIR)
    out = []
    if os.path.isdir(folder):
        for name in sorted(os.listdir(folder), reverse=True):
            if name.lower().endswith(".zip"):
                try:
                    out.append(read_version(os.path.join(folder, name)))
                except (OSError, KeyError, ValueError, zipfile.BadZipFile):
                    continue
    return out


def related(version, project, key):
    """Версия относится к узлу: тот же головной файл или то же обозначение."""
    d = project.doc(key)
    same_file = norm(os.path.join(project.root, version.root_rel)) == key
    return same_file or (d is not None and d.designation and d.designation == version.designation)


@dataclass
class RestorePlan:
    version: Version
    current_key: str
    restore_root: str  # путь головного файла после распаковки
    orphans: list  # файлы текущего узла, которых нет в версии
    parents: list  # сборки, где нужно заменить текущий узел на восстановленный
    relink: dict  # norm-ключ текущего головного файла -> путь восстановленного


def plan_restore(project, version, current_key):
    root = project.root
    restore_root = os.path.join(root, version.root_rel.replace("/", os.sep))
    in_version = {norm(os.path.join(root, f)) for f in version.files}
    models, docs = subtree_keys(project, current_key)
    orphans = [project.raw_paths.get(k, k) for k in models + docs if k not in in_version]
    parents, relink = [], {}
    if norm(restore_root) != current_key:
        parents = [project.raw_paths.get(p, p) for p in sorted(project.parents.get(current_key, set()))
                   if project.inside(p) and p not in in_version]
        relink = {current_key: restore_root}
    return RestorePlan(version, current_key, restore_root, orphans, parents, relink)


def extract_version(version, root):
    """Распаковать файлы версии на их места (с перезаписью). Возвращает список путей."""
    out = []
    with zipfile.ZipFile(version.path) as z:
        for rel in version.files:
            target = os.path.join(root, rel.replace("/", os.sep))
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with z.open(rel) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            out.append(target)
    return out


def move_to_old(root, paths):
    """Убрать файлы в <изделие>/_old/<дата>/ с сохранением относительных путей."""
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    moved = []
    for p in paths:
        if not os.path.exists(p):
            continue
        target = os.path.join(root, "_old", stamp, os.path.relpath(p, root))
        os.makedirs(os.path.dirname(target), exist_ok=True)
        shutil.move(p, target)
        moved.append(target)
    return moved
