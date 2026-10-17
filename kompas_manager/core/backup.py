"""Резервная копия перед переобозначением и откат.

Перед изменениями все затронутые файлы копируются в <проект>/_backup/<дата_время>/
с сохранением относительных путей. В manifest.json записываются созданные файлы.
Откат удаляет созданные файлы и возвращает исходные из копии.
"""
import datetime
import json
import os
import shutil

from .model import norm

BACKUP_DIR = "_backup"
MANIFEST = "manifest.json"


class Backup:
    def __init__(self, root, folder, manifest):
        self.root = root
        self.folder = folder
        self.manifest = manifest

    # ---------- создание ----------

    @classmethod
    def create(cls, root, paths, description=""):
        stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        folder = os.path.join(root, BACKUP_DIR, stamp)
        n = 1
        while os.path.exists(folder):
            n += 1
            folder = os.path.join(root, BACKUP_DIR, f"{stamp}_{n}")
        os.makedirs(folder)
        originals = []
        for path in dict.fromkeys(paths):
            rel = os.path.relpath(path, root)
            target = os.path.join(folder, rel)
            os.makedirs(os.path.dirname(target), exist_ok=True)
            shutil.copy2(path, target)
            originals.append(rel)
        b = cls(root, folder, {
            "time": stamp,
            "description": description,
            "originals": originals,
            "created": [],
            "removed": [],
            "rolled_back": False,
        })
        b.save()
        return b

    def save(self):
        with open(os.path.join(self.folder, MANIFEST), "w", encoding="utf-8") as f:
            json.dump(self.manifest, f, ensure_ascii=False, indent=2)

    def created(self, path):
        """Отметить файл, созданный при переобозначении (удаляется при откате)."""
        self.manifest["created"].append(os.path.relpath(path, self.root))
        self.save()

    def remove_original(self, path):
        """Удалить старый файл после переименования; его копия остаётся в резервной папке."""
        rel = os.path.relpath(path, self.root)
        if rel not in self.manifest["originals"] or not os.path.exists(os.path.join(self.folder, rel)):
            raise RuntimeError(f"Нет резервной копии, удаление отменено: {rel}")
        os.remove(path)
        self.manifest["removed"].append(rel)
        self.save()

    # ---------- откат ----------

    @classmethod
    def latest(cls, root):
        base = os.path.join(root, BACKUP_DIR)
        if not os.path.isdir(base):
            return None
        for name in sorted(os.listdir(base), reverse=True):
            path = os.path.join(base, name, MANIFEST)
            try:
                with open(path, encoding="utf-8") as f:
                    manifest = json.load(f)
            except (OSError, ValueError):
                continue
            if not manifest.get("rolled_back"):
                return cls(root, os.path.join(base, name), manifest)
        return None

    def rollback(self, log=print):
        """Вернуть проект к состоянию до переобозначения. Возвращает список ошибок."""
        errors = []
        originals = {norm(os.path.join(self.root, r)) for r in self.manifest["originals"]}
        for rel in self.manifest["created"]:
            path = os.path.join(self.root, rel)
            if norm(path) in originals or not os.path.exists(path):
                continue
            try:
                os.remove(path)
                log(f"удалён: {rel}")
            except OSError as e:
                errors.append(f"{rel}: {e}")
        for rel in self.manifest["originals"]:
            try:
                target = os.path.join(self.root, rel)
                os.makedirs(os.path.dirname(target), exist_ok=True)
                shutil.copy2(os.path.join(self.folder, rel), target)
                log(f"восстановлен: {rel}")
            except OSError as e:
                errors.append(f"{rel}: {e}")
        if not errors:
            self.manifest["rolled_back"] = True
            self.save()
        return errors
