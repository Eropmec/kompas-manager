"""Точка входа приложения."""
import os
import sys

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from kompas_manager.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("KompasManager")
    app.setOrganizationName("KompasManager")
    translator = QTranslator(app)  # русские надписи стандартных кнопок и диалогов Qt
    if translator.load(QLocale("ru_RU"), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(translator)
    base = getattr(sys, "_MEIPASS", os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
    icon = os.path.join(base, "assets", "app_256.png")
    if os.path.exists(icon):
        app.setWindowIcon(QIcon(icon))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
