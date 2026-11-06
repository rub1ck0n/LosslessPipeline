import sys
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow


def apply_dark_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.ColorRole.Window, QColor(10, 10, 13))
    palette.setColor(QPalette.ColorRole.WindowText, QColor(234, 234, 239))
    palette.setColor(QPalette.ColorRole.Base, QColor(12, 12, 15))
    palette.setColor(QPalette.ColorRole.AlternateBase, QColor(19, 19, 23))
    palette.setColor(QPalette.ColorRole.Text, QColor(234, 234, 239))
    palette.setColor(QPalette.ColorRole.Button, QColor(29, 29, 36))
    palette.setColor(QPalette.ColorRole.ButtonText, QColor(228, 228, 236))
    palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 42, 52))
    palette.setColor(QPalette.ColorRole.HighlightedText, QColor(255, 255, 255))
    app.setPalette(palette)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    apply_dark_theme(app)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())