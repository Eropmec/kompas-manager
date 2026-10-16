"""Данные о документах КОМПАСа и найденных проблемах."""
import json
import os
from dataclasses import asdict, dataclass, field

KIND_BY_EXT = {
    ".m3d": "part",
    ".a3d": "assembly",
    ".cdw": "drawing",
    ".spw": "spec",
}

KIND_TITLES = {
    "part": "Деталь",
    "assembly": "Сборка",
    "drawing": "Чертёж",
    "spec": "Спецификация",
}

ERROR = "error"
WARNING = "warning"
INFO = "info"

SEVERITY_ORDER = {ERROR: 0, WARNING: 1, INFO: 2}
SEVERITY_TITLES = {ERROR: "Ошибка", WARNING: "Предупреждение", INFO: "Замечание"}


def kind_of(path):
    return KIND_BY_EXT.get(os.path.splitext(path)[1].lower())


def norm(path):
    """Ключ пути для сравнения: абсолютный, нормализованный, без учёта регистра (в Windows)."""
    return os.path.normcase(os.path.normpath(os.path.abspath(path))) if path else ""


@dataclass
class DocInfo:
    """Что известно о файле КОМПАСа после чтения через API."""

    path: str
    kind: str
    designation: str = ""
    name: str = ""
    refs: list = field(default_factory=list)  # пути файлов, на которые ссылается документ
    error: str = ""  # что не удалось прочитать
    mtime: float = 0.0
    size: int = 0

    def to_json(self):
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_json(cls, text):
        return cls(**json.loads(text))


@dataclass
class Issue:
    severity: str
    key: str  # norm-путь файла, к которому относится проблема
    message: str
