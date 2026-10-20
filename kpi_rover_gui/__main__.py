"""Start the KPI Rover GUI: python3 -m kpi_rover_gui"""

import signal
import sys

from PyQt5.QtCore import QTimer
from PyQt5.QtWidgets import QApplication

from . import theme
from .main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('KPI Rover')
    theme.install(app)
    window = MainWindow()
    window.show()
    # Ctrl+C in the terminal closes the window (and stops what runs) instead of being ignored.
    signal.signal(signal.SIGINT, lambda *_: window.close())
    timer = QTimer()
    timer.timeout.connect(lambda: None)
    timer.start(300)
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
