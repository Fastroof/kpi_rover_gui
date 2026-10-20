"""
Editors of world arguments, one per argument type, all with the same
interface: 'changed' signal, value() as the string passed in world_args and
set_value(value) returning False for a value the argument can't have.
"""

import math
import random

from PyQt5.QtCore import QEvent, QObject, QPropertyAnimation, QRectF, QRegExp, QSize, Qt, pyqtProperty, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QRegExpValidator
from PyQt5.QtWidgets import (QAbstractButton, QAbstractSpinBox, QButtonGroup, QComboBox, QDoubleSpinBox, QHBoxLayout,
                             QLineEdit, QPushButton, QSlider, QSpinBox, QWidget)

from . import theme

INT_LIMIT = 2 ** 31 - 1
# Choices shown as segmented buttons instead of a drop-down list.
SEGMENTS_MAX = 4
SEGMENT_TEXT_MAX = 12


def decimals(spec):
    step = spec.get('step')
    if not step:
        return 3 if spec.get('type') == 'float' else 0
    return max(0, -math.floor(math.log10(step) + 1e-9))


def format_value(spec, value):
    """The string form of a value, as in world_args and in world_info.format_value."""
    kind = spec.get('type')
    if kind == 'bool':
        if isinstance(value, str):
            return 'true' if value.lower() in ('true', '1') else 'false'
        return 'true' if value else 'false'
    if kind == 'float':
        return f'{round(float(value), decimals(spec)):g}'
    if kind == 'int':
        return str(int(value))
    return str(value)


def display_value(spec, text):
    """A value as shown to people: On/Off for switches, 'empty' for an empty string."""
    if spec.get('type') == 'bool':
        return 'On' if text == 'true' else 'Off'
    return text if text != '' else 'empty'


class NoWheel(QObject):
    """Event filter: the mouse wheel scrolls the page instead of changing a control it passes over."""

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Wheel and not obj.hasFocus():
            event.ignore()
            return True
        return False


_no_wheel = NoWheel()


def no_wheel(widget):
    widget.setFocusPolicy(Qt.StrongFocus)
    widget.installEventFilter(_no_wheel)
    return widget


class ToggleSwitch(QAbstractButton):
    """An on/off switch."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 0.0
        self.animation = QPropertyAnimation(self, b'pos', self)
        self.animation.setDuration(120)
        self.toggled.connect(self._animate)

    def sizeHint(self):
        return QSize(44, 24)

    def _animate(self, checked):
        self.animation.stop()
        self.animation.setStartValue(self._pos)
        self.animation.setEndValue(1.0 if checked else 0.0)
        self.animation.start()

    def get_pos(self):
        return self._pos

    def set_pos(self, value):
        self._pos = value
        self.update()

    pos = pyqtProperty(float, get_pos, set_pos)

    def setChecked(self, checked):
        super().setChecked(checked)
        self.animation.stop()
        self._pos = 1.0 if checked else 0.0
        self.update()

    def paintEvent(self, event):
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rect = QRectF(1, (self.height() - 22) / 2, 42, 22)
        off, on = QColor(t['border']), QColor(t['accent'])
        track = QColor(round(off.red() + (on.red() - off.red()) * self._pos),
                       round(off.green() + (on.green() - off.green()) * self._pos),
                       round(off.blue() + (on.blue() - off.blue()) * self._pos))
        p.setPen(Qt.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(rect, 11, 11)
        p.setBrush(QColor('#ffffff'))
        x = rect.left() + 3 + self._pos * (rect.width() - 22)
        p.drawEllipse(QRectF(x, rect.top() + 3, 16, 16))


class Editor(QWidget):
    """Base of the argument editors."""
    changed = pyqtSignal()

    def __init__(self, spec, parent=None):
        super().__init__(parent)
        self.spec = spec
        self.layout_ = QHBoxLayout(self)
        self.layout_.setContentsMargins(0, 0, 0, 0)
        self.layout_.setSpacing(8)

    def default(self):
        default = self.spec.get('default', '')
        return '' if default == '' else format_value(self.spec, default)

    def reset(self):
        self.set_value(self.default())


class BoolEditor(Editor):
    def __init__(self, spec, parent=None):
        super().__init__(spec, parent)
        self.switch = ToggleSwitch()
        self.switch.toggled.connect(self.changed)
        self.layout_.addWidget(self.switch)
        self.layout_.addStretch(1)

    def value(self):
        return format_value(self.spec, self.switch.isChecked())

    def set_value(self, value):
        text = str(value).lower() if not isinstance(value, bool) else ('true' if value else 'false')
        if text not in ('true', 'false', '1', '0'):
            return False
        self.switch.setChecked(text in ('true', '1'))
        return True


class ChoiceEditor(Editor):
    """Segmented buttons for a few short choices, a drop-down list otherwise."""

    def __init__(self, spec, parent=None):
        super().__init__(spec, parent)
        self.items = [('(default)', '')] if spec.get('default', '') == '' else []
        self.items += [(str(c), str(c)) for c in spec.get('choices', [])]
        segmented = len(self.items) <= SEGMENTS_MAX and all(len(text) <= SEGMENT_TEXT_MAX for text, _ in self.items)
        self.group = None
        self.combo = None
        if segmented:
            self.group = QButtonGroup(self)
            self.group.setExclusive(True)
            row = QHBoxLayout()
            row.setSpacing(0)
            for i, (text, data) in enumerate(self.items):
                button = QPushButton(text)
                button.setObjectName('Segment')
                button.setCheckable(True)
                button.setCursor(Qt.PointingHandCursor)
                button.setProperty('first', i == 0)
                button.setProperty('last', i == len(self.items) - 1)
                self.group.addButton(button, i)
                row.addWidget(button)
            self.group.buttonClicked.connect(lambda _: self.changed.emit())
            self.layout_.addLayout(row)
            self.layout_.addStretch(1)
        else:
            self.combo = no_wheel(QComboBox())
            for text, data in self.items:
                self.combo.addItem(text, data)
            self.combo.currentIndexChanged.connect(self.changed)
            self.layout_.addWidget(self.combo, 1)

    def value(self):
        if self.group:
            index = self.group.checkedId()
            return self.items[index][1] if index >= 0 else self.default()
        return self.combo.currentData()

    def set_value(self, value):
        datas = [data for _, data in self.items]
        if str(value) not in datas:
            return False
        index = datas.index(str(value))
        if self.group:
            if self.group.checkedId() != index:
                self.group.button(index).setChecked(True)
                self.changed.emit()
        else:
            self.combo.setCurrentIndex(index)
        return True


class NumberEditor(Editor):
    """A slider with the value next to it for bounded numbers; a number field otherwise."""

    def __init__(self, spec, parent=None):
        super().__init__(spec, parent)
        self.kind = spec.get('type')
        self.step = float(spec.get('step', 1 if self.kind == 'int' else 0.1))
        if self.kind == 'int':
            self.box = QSpinBox()
            self.box.setRange(int(spec.get('min', -INT_LIMIT)), int(spec.get('max', INT_LIMIT)))
            self.box.setSingleStep(int(self.step))
        else:
            self.box = QDoubleSpinBox()
            self.box.setDecimals(decimals(spec))
            self.box.setRange(float(spec.get('min', -1e9)), float(spec.get('max', 1e9)))
            self.box.setSingleStep(self.step)
        no_wheel(self.box)
        self.box.setButtonSymbols(QAbstractSpinBox.NoButtons)
        self.box.setAlignment(Qt.AlignRight)
        self.box.setFixedWidth(76)
        self.box.valueChanged.connect(self._box_changed)
        self.slider = None
        if 'min' in spec and 'max' in spec:
            self.slider = no_wheel(QSlider(Qt.Horizontal))
            self.slider.setRange(0, round((spec['max'] - spec['min']) / self.step))
            self.slider.setCursor(Qt.PointingHandCursor)
            self.slider.valueChanged.connect(self._slider_changed)
            self.layout_.addWidget(self.slider, 1)
            self.layout_.addWidget(self.box)
        else:
            self.layout_.addWidget(self.box)
            if self.kind == 'int':
                # An unbounded integer is a variant number (a seed): offer a random one.
                dice = QPushButton('🎲  Random')
                dice.setObjectName('Flat')
                dice.setCursor(Qt.PointingHandCursor)
                dice.setToolTip('Another random variant')
                dice.clicked.connect(lambda: self.box.setValue(random.randint(max(0, self.box.minimum()), 9999)))
                self.layout_.addWidget(dice)
            self.layout_.addStretch(1)

    def _slider_changed(self, index):
        value = self.spec['min'] + index * self.step
        # A QSpinBox takes only integers: a float from the slider would be refused.
        self.box.setValue(int(round(value)) if self.kind == 'int' else value)

    def _box_changed(self, value):
        if self.slider:
            self.slider.blockSignals(True)
            self.slider.setValue(round((value - self.spec['min']) / self.step))
            self.slider.blockSignals(False)
        self.changed.emit()

    def value(self):
        return format_value(self.spec, self.box.value())

    def set_value(self, value):
        try:
            number = int(value) if self.kind == 'int' else float(value)
        except (TypeError, ValueError):
            return False
        if not self.box.minimum() <= number <= self.box.maximum():
            return False
        self.box.setValue(int(number) if self.kind == 'int' else number)
        self._box_changed(self.box.value())
        return True


class TextEditor(Editor):
    def __init__(self, spec, parent=None):
        super().__init__(spec, parent)
        self.edit = QLineEdit()
        # world_args are split at spaces, so a value can't have any.
        self.edit.setValidator(QRegExpValidator(QRegExp(r'\S*')))
        self.edit.setPlaceholderText('empty')
        self.edit.textChanged.connect(self.changed)
        self.layout_.addWidget(self.edit, 1)

    def value(self):
        return self.edit.text()

    def set_value(self, value):
        if any(c.isspace() for c in str(value)):
            return False
        self.edit.setText(str(value))
        return True


def editor(spec):
    kind = spec.get('type', 'string')
    editor = {'bool': BoolEditor, 'choice': ChoiceEditor, 'int': NumberEditor, 'float': NumberEditor}.get(
        kind, TextEditor)(spec)
    editor.blockSignals(True)
    editor.reset()
    editor.blockSignals(False)
    return editor
