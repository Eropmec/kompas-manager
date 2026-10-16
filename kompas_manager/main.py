"""Точка входа приложения."""
import sys

from PySide6.QtWidgets import QApplication

from kompas_manager.ui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("KompasManager")
    app.setOrganizationName("KompasManager")
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
