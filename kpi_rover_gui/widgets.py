"""Small building blocks: images, flow layout, process log."""

import re

from PyQt5.QtCore import QPoint, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFontDatabase, QPainter, QPainterPath, QPixmap, QTextCharFormat
from PyQt5.QtWidgets import QFrame, QLayout, QPlainTextEdit, QSizePolicy, QWidget

from . import theme

_pixmaps = {}


def pixmap(source):
    """
    A cached image of a file path, or of (base path, overlay path): the
    overlay (a transparent PNG of the same size) drawn over the base; or None.
    """
    if not source:
        return None
    if source not in _pixmaps:
        if isinstance(source, tuple):
            base, overlay = (pixmap(s) for s in source)
            image = None
            if base and overlay:
                image = QPixmap(base)
                painter = QPainter(image)
                painter.setRenderHint(QPainter.SmoothPixmapTransform)
                painter.drawPixmap(image.rect(), overlay)
                painter.end()
            elif base:
                image = base
        else:
            image = QPixmap(source)
            image = None if image.isNull() else image
        _pixmaps[source] = image
    return _pixmaps[source]


class ImageView(QWidget):
    """An image with rounded corners: 'cover' fills the widget (cropping), otherwise the whole image is shown."""

    def __init__(self, cover=False, radius=12, ratio=None, parent=None):
        super().__init__(parent)
        self.cover = cover
        self.radius = radius
        self.ratio = ratio          # height / width for heightForWidth
        self.image = None
        self.placeholder = ''
        if ratio:
            policy = QSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
            policy.setHeightForWidth(True)
            self.setSizePolicy(policy)

    def hasHeightForWidth(self):
        return bool(self.ratio)

    def heightForWidth(self, width):
        return round(width * self.ratio) if self.ratio else super().heightForWidth(width)

    def sizeHint(self):
        return QSize(320, round(320 * self.ratio) if self.ratio else 200)

    def set_image(self, path, placeholder=''):
        self.image = pixmap(path)
        self.placeholder = placeholder
        self.update()

    def paintEvent(self, event):
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        rect = QRectF(self.rect())
        clip = QPainterPath()
        clip.addRoundedRect(rect, self.radius, self.radius)
        p.setClipPath(clip)
        p.fillRect(self.rect(), QColor(t['image_bg']))
        if self.image:
            size = self.image.size().scaled(self.size(), Qt.KeepAspectRatioByExpanding if self.cover
                                            else Qt.KeepAspectRatio)
            target = QRect(QPoint(0, 0), size)
            target.moveCenter(self.rect().center())
            p.drawPixmap(target, self.image)
        elif self.placeholder:
            p.setPen(QColor(t['muted']))
            p.drawText(self.rect().adjusted(12, 12, -12, -12), Qt.AlignCenter | Qt.TextWordWrap, self.placeholder)


class Clickable(QFrame):
    """A frame that is clicked as a whole."""
    clicked = pyqtSignal()
    hovered = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton and self.rect().contains(event.pos()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def enterEvent(self, event):
        self.hovered.emit()
        super().enterEvent(event)


def set_flag(widget, name, value):
    """Set a dynamic property used by the style sheet and restyle the widget."""
    if widget.property(name) != value:
        widget.setProperty(name, value)
        widget.style().unpolish(widget)
        widget.style().polish(widget)
        widget.update()


class FlowLayout(QLayout):
    """Lays its items out in rows, wrapping like words (for chips)."""

    def __init__(self, parent=None, spacing=8):
        super().__init__(parent)
        self.items = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)

    def addItem(self, item):
        self.items.append(item)

    def count(self):
        return len(self.items)

    def itemAt(self, index):
        return self.items[index] if 0 <= index < len(self.items) else None

    def takeAt(self, index):
        return self.items.pop(index) if 0 <= index < len(self.items) else None

    def expandingDirections(self):
        return Qt.Orientations()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._layout(QRect(0, 0, width, 0), True)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._layout(rect, False)

    def sizeHint(self):
        return self.minimumSize()

    def minimumSize(self):
        size = QSize()
        for item in self.items:
            size = size.expandedTo(item.minimumSize())
        return size

    def _layout(self, rect, test):
        x, y, line = rect.x(), rect.y(), 0
        space = self.spacing()
        for item in self.items:
            hint = item.sizeHint()
            if x + hint.width() > rect.right() + 1 and line > 0:
                x, y, line = rect.x(), y + line + space, 0
            if not test:
                item.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + space
            line = max(line, hint.height())
        return y + line - rect.y()


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        widget = item.widget()
        if widget:
            # Hidden at once, deleted by Qt later: it may be the widget whose click is being handled.
            widget.hide()
            widget.deleteLater()
        elif item.layout():
            clear_layout(item.layout())


class LogView(QPlainTextEdit):
    """Read-only process output with errors and warnings colored."""
    MAX_LINES = 20000
    PATTERNS = ((re.compile(r'\[ERROR\]|\[Err\]|\berror\b|Error:|Traceback|failed', re.IGNORECASE), 'danger'),
                (re.compile(r'\[WARN(ING)?\]|\[Wrn\]|\bwarning\b', re.IGNORECASE), 'warning'),
                (re.compile(r'^--- .* ---$'), 'accent'))

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setMaximumBlockCount(self.MAX_LINES)
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.setFont(QFontDatabase.systemFont(QFontDatabase.FixedFont))
        self.has_text = False

    def reset(self):
        self.clear()
        self.has_text = False

    def add_line(self, text):
        bar = self.verticalScrollBar()
        at_end = bar.value() >= bar.maximum() - 4
        fmt = QTextCharFormat()
        for pattern, token in self.PATTERNS:
            if pattern.search(text):
                fmt.setForeground(QColor(theme.current()[token]))
                break
        cursor = self.textCursor()
        cursor.movePosition(cursor.End)
        if self.has_text:
            cursor.insertText('\n', QTextCharFormat())
        cursor.insertText(text, fmt)
        self.has_text = True
        if at_end:
            bar.setValue(bar.maximum())
