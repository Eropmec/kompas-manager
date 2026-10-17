"""Точка входа приложения."""
import sys

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtWidgets import QApplication

from kompas_manager.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("KompasManager")
    app.setOrganizationName("KompasManager")
    translator = QTranslator(app)  # русские надписи стандартных кнопок и диалогов Qt
    if translator.load(QLocale("ru_RU"), "qtbase", "_", QLibraryInfo.path(QLibraryInfo.TranslationsPath)):
        app.installTranslator(translator)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
