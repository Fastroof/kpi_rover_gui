"""
The look of the application: light or dark like the system (GNOME
'color-scheme', followed live), a Fusion palette and one style sheet built
from a few color tokens.
"""

import os
import shutil
import subprocess

from PyQt5.QtCore import QObject, QProcess, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPalette
from PyQt5.QtWidgets import QStyleFactory

TOKENS = {
    'light': dict(
        window='#f3f4f6', surface='#ffffff', surface2='#eceef2', border='#d9dce3', text='#1b1d22',
        muted='#636a76', accent='#2f6fed', accent_text='#ffffff', accent_soft='#dce7fd', success='#1f9d55',
        warning='#b7791f', danger='#d64545', shadow='#00000018', image_bg='#e3e6eb'),
    'dark': dict(
        window='#17181c', surface='#202227', surface2='#2a2d33', border='#34373e', text='#e8eaee',
        muted='#9aa1ad', accent='#5b8def', accent_text='#ffffff', accent_soft='#26344f', success='#3ccf7a',
        warning='#e0a43a', danger='#f06464', shadow='#00000060', image_bg='#111215'),
}

STYLE = """
QWidget {{ color: {text}; font-size: 10pt; }}
QMainWindow, #Page, #Window {{ background: {window}; }}
QToolTip {{ background: {surface}; color: {text}; border: 1px solid {border}; padding: 6px; border-radius: 6px; }}
QScrollArea, QScrollArea > QWidget > QWidget {{ background: transparent; border: none; }}
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 2px; }}
QScrollBar::handle:vertical {{ background: {border}; border-radius: 4px; min-height: 30px; }}
QScrollBar::handle:vertical:hover {{ background: {muted}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 2px; }}
QScrollBar::handle:horizontal {{ background: {border}; border-radius: 4px; min-width: 30px; }}

#Header, #Footer {{ background: {surface}; border: none; }}
#Header {{ border-bottom: 1px solid {border}; }}
#Footer {{ border-top: 1px solid {border}; }}
#AppTitle {{ font-size: 13pt; font-weight: 600; }}
#PageTitle {{ font-size: 18pt; font-weight: 600; }}
#Muted, #Hint {{ color: {muted}; }}
#Hint {{ font-size: 9pt; }}
#Section {{ color: {muted}; font-size: 8.5pt; font-weight: 600; letter-spacing: 1px; }}
#Caption {{ color: {muted}; font-size: 9pt; }}

QPushButton {{ background: {surface2}; border: 1px solid {border}; border-radius: 8px; padding: 6px 14px; }}
QPushButton:hover {{ border-color: {muted}; }}
QPushButton:pressed {{ background: {border}; }}
QPushButton:disabled {{ color: {muted}; background: {surface2}; border-color: {surface2}; }}
QPushButton#Primary {{ background: {accent}; color: {accent_text}; border: none; font-weight: 600;
    padding: 9px 26px; font-size: 11pt; border-radius: 10px; }}
QPushButton#Primary:hover {{ background: {accent_hover}; }}
QPushButton#Primary:disabled {{ background: {border}; color: {muted}; }}
QPushButton#Flat, QToolButton#Flat {{ background: transparent; border: none; padding: 6px 10px; border-radius: 8px; }}
QPushButton#Flat:hover, QToolButton#Flat:hover {{ background: {surface2}; }}
QPushButton#Flat:checked {{ background: {accent_soft}; color: {accent}; }}
QToolButton#Reset {{ background: transparent; border: none; color: {muted}; padding: 0 4px; font-size: 11pt; }}
QToolButton#Reset:hover {{ color: {accent}; }}
QToolButton#Disclosure {{ background: transparent; border: none; color: {accent}; font-weight: 600; padding: 6px 0; }}

QPushButton#Chip {{ background: {surface}; border: 1px solid {border}; border-radius: 15px; padding: 5px 14px; }}
QPushButton#Chip:hover {{ border-color: {accent}; }}
QPushButton#Chip:checked {{ background: {accent_soft}; border-color: {accent}; color: {accent}; }}
QPushButton#AddChip {{ background: transparent; border: 1px dashed {border}; border-radius: 15px; padding: 5px 14px;
    color: {muted}; }}
QPushButton#AddChip:hover {{ border-color: {accent}; color: {accent}; }}

QPushButton#Segment {{ background: {surface2}; border: 1px solid {border}; border-radius: 0; padding: 6px 14px; }}
QPushButton#Segment[first="true"] {{ border-top-left-radius: 8px; border-bottom-left-radius: 8px; }}
QPushButton#Segment[last="true"] {{ border-top-right-radius: 8px; border-bottom-right-radius: 8px; }}
QPushButton#Segment:checked {{ background: {accent}; color: {accent_text}; border-color: {accent}; font-weight: 600; }}

QFrame#Card, QFrame#Panel {{ background: {surface}; border: 1px solid {border}; border-radius: 14px; }}
QFrame#Card:hover {{ border-color: {accent}; }}
QFrame#Option {{ background: transparent; border: none; border-left: 3px solid transparent; }}
QFrame#Option[changed="true"] {{ border-left: 3px solid {accent}; }}
QFrame#Option:hover {{ background: {surface2}; border-radius: 8px; }}
QFrame#ProcessCard {{ background: {surface}; border: 1px solid {border}; border-radius: 12px; }}
QFrame#ProcessCard:hover {{ border-color: {muted}; }}
QFrame#ProcessCard[selected="true"] {{ border: 2px solid {accent}; }}
QPushButton#PrimarySmall {{ background: {accent}; color: {accent_text}; border: none; font-weight: 600;
    padding: 6px 16px; border-radius: 8px; }}
QPushButton#PrimarySmall:hover {{ background: {accent_hover}; }}
QPushButton#PrimarySmall:disabled {{ background: {surface2}; color: {muted}; }}
QPushButton#Chip:disabled {{ color: {muted}; border-color: {surface2}; }}
QPushButton#DangerSmall {{ background: transparent; color: {danger}; border: 1px solid {danger}; font-weight: 600;
    padding: 5px 15px; border-radius: 8px; }}
QPushButton#DangerSmall:hover {{ background: {danger}; color: #ffffff; }}
QPushButton#Pill {{ background: {accent_soft}; color: {accent}; border: none; border-radius: 14px; padding: 5px 14px;
    font-weight: 600; }}
QCheckBox {{ spacing: 8px; }}
QCheckBox::indicator {{ width: 16px; height: 16px; border: 1px solid {border}; border-radius: 4px;
    background: {surface}; }}
QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent}; }}
QFrame#Thumb {{ border: 2px solid transparent; border-radius: 8px; }}
QFrame#Thumb[selected="true"] {{ border-color: {accent}; }}
QFrame#Thumb:hover {{ border-color: {muted}; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {{ background: {surface}; border: 1px solid {border}; border-radius: 8px;
    padding: 5px 8px; selection-background-color: {accent}; }}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {{ border-color: {accent}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{ background: {surface}; border: 1px solid {border}; selection-background-color: {accent_soft};
    selection-color: {text}; outline: none; }}
QSpinBox::up-button, QSpinBox::down-button, QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {{ width: 0; border: none; }}

QSlider::groove:horizontal {{ height: 4px; background: {border}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {accent}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {surface}; border: 2px solid {accent}; width: 14px; height: 14px;
    margin: -7px 0; border-radius: 9px; }}
QSlider::handle:horizontal:hover {{ background: {accent_soft}; }}

QTabWidget::pane {{ border: none; background: {surface}; }}
QTabBar::tab {{ background: transparent; padding: 6px 14px; border: none; color: {muted}; }}
QTabBar::tab:selected {{ color: {text}; border-bottom: 2px solid {accent}; }}
QPlainTextEdit {{ background: {image_bg}; border: none; border-radius: 8px; padding: 6px; }}
QSplitter::handle {{ background: {border}; }}
QMenu {{ background: {surface}; border: 1px solid {border}; padding: 6px; border-radius: 8px; }}
QMenu::item {{ padding: 6px 18px; border-radius: 6px; }}
QMenu::item:selected {{ background: {accent_soft}; color: {text}; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 4px 8px; }}
QDialog {{ background: {window}; }}
QMessageBox {{ background: {window}; }}
"""


def system_scheme():
    """'dark' or 'light', from the GNOME color scheme (or the GTK theme name); KPI_ROVER_GUI_THEME overrides it."""
    forced = os.environ.get('KPI_ROVER_GUI_THEME')
    if forced in TOKENS:
        return forced
    if not shutil.which('gsettings'):
        return 'light'
    for key in ('color-scheme', 'gtk-theme'):
        try:
            value = subprocess.run(['gsettings', 'get', 'org.gnome.desktop.interface', key],
                                   capture_output=True, text=True, timeout=2).stdout
        except (OSError, subprocess.TimeoutExpired):
            continue
        if 'dark' in value.lower():
            return 'dark'
    return 'light'


def _mix(a, b, t):
    a, b = QColor(a), QColor(b)
    return QColor(round(a.red() + (b.red() - a.red()) * t), round(a.green() + (b.green() - a.green()) * t),
                  round(a.blue() + (b.blue() - a.blue()) * t)).name()


class Theme(QObject):
    """The current colors; 'changed' when the system switches between light and dark."""
    changed = pyqtSignal()

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.scheme = None
        app.setStyle(QStyleFactory.create('Fusion'))
        font = QFont(app.font())
        font.setPointSizeF(10)
        app.setFont(font)
        self.apply(system_scheme())
        # Follow the system setting while running.
        self.monitor = None
        if shutil.which('gsettings'):
            self.monitor = QProcess(self)
            self.monitor.readyReadStandardOutput.connect(self._system_changed)
            self.monitor.start('gsettings', ['monitor', 'org.gnome.desktop.interface', 'color-scheme'])
            app.aboutToQuit.connect(self.monitor.kill)

    def _system_changed(self):
        self.monitor.readAllStandardOutput()
        scheme = system_scheme()
        if scheme != self.scheme:
            self.apply(scheme)

    def __getitem__(self, token):
        return self.colors[token]

    @property
    def dark(self):
        return self.scheme == 'dark'

    def apply(self, scheme):
        self.scheme = scheme
        c = dict(TOKENS[scheme])
        c['accent_hover'] = _mix(c['accent'], '#ffffff' if scheme == 'dark' else '#000000', 0.12)
        self.colors = c
        palette = QPalette()
        for role, token in ((QPalette.Window, 'window'), (QPalette.WindowText, 'text'), (QPalette.Base, 'surface'),
                            (QPalette.AlternateBase, 'surface2'), (QPalette.Text, 'text'), (QPalette.Button, 'surface2'),
                            (QPalette.ButtonText, 'text'), (QPalette.Highlight, 'accent'),
                            (QPalette.HighlightedText, 'accent_text'), (QPalette.ToolTipBase, 'surface'),
                            (QPalette.ToolTipText, 'text'), (QPalette.PlaceholderText, 'muted'),
                            (QPalette.Link, 'accent')):
            palette.setColor(role, QColor(c[token]))
        for role in (QPalette.WindowText, QPalette.Text, QPalette.ButtonText):
            palette.setColor(QPalette.Disabled, role, QColor(c['muted']))
        self.app.setPalette(palette)
        self.app.setStyleSheet(STYLE.format(**c))
        self.changed.emit()


_theme = None


def install(app):
    global _theme
    _theme = Theme(app)
    return _theme


def current():
    return _theme
