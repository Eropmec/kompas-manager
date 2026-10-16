"""Отчёт прототипа: пишет в файл, в консоль (если она есть) и в окно программы."""
import sys
import traceback
from contextlib import contextmanager


class Report:
    def __init__(self, path, on_line=None):
        self.path = path
        self.on_line = on_line
        self.f = open(path, "w", encoding="utf-8")
        self.results = []

    def line(self, text=""):
        if sys.stdout is not None:  # в exe без консоли stdout отсутствует
            try:
                print(text)
            except Exception:
                pass
        if self.on_line is not None:
            self.on_line(text)
        self.f.write(text + "\n")
        self.f.flush()

    @contextmanager
    def step(self, title):
        """Шаг проверки: ошибка записывается в отчёт, работа идёт дальше."""
        self.line(f"\n== {title}")
        try:
            yield
            self.results.append((title, "OK", ""))
        except Exception as e:
            msg = f"{type(e).__name__}: {e}"
            self.line(f"  ОШИБКА: {msg}")
            self.line(traceback.format_exc())
            self.results.append((title, "ОШИБКА", msg))

    def check(self, title, ok, detail=""):
        status = "OK" if ok else "НЕ ВЫПОЛНЕНО"
        self.line(f"  [{status}] {title}" + (f" — {detail}" if detail else ""))
        self.results.append((title, status, detail))

    def summary(self):
        self.line("\n========== ИТОГ ==========")
        for title, status, detail in self.results:
            self.line(f"{status:13} {title}" + (f" — {detail}" if detail else ""))
        self.line(f"\nОтчёт сохранён: {self.path}")
        self.f.close()
