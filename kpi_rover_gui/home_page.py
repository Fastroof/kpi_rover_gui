"""The first page: all worlds as cards with their pictures."""

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import QGridLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from .widgets import Clickable, ImageView, clear_layout

CARD_WIDTH = 300


class WorldCard(Clickable):
    """A world: its picture and its name."""

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.setObjectName('Card')
        self.name = info['name']
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 12)
        layout.setSpacing(10)
        image = ImageView(cover=True, radius=13, ratio=0.6)
        image.set_image(info.get('image'), info['title'])
        layout.addWidget(image)
        title = QLabel(info['title'])
        font = title.font()
        font.setPointSizeF(font.pointSizeF() * 1.15)
        font.setBold(True)
        title.setFont(font)
        title.setContentsMargins(14, 0, 14, 0)
        layout.addWidget(title)


class HomePage(QWidget):
    chosen = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('Page')
        self.cards = []
        self.message = QLabel()
        self.message.setObjectName('Muted')
        self.message.setWordWrap(True)
        self.grid = QGridLayout()
        self.grid.setSpacing(18)
        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(24, 20, 24, 24)
        heading = QLabel('Choose a world')
        heading.setObjectName('PageTitle')
        inner_layout.addWidget(heading)
        inner_layout.addWidget(self.message)
        inner_layout.addSpacing(8)
        inner_layout.addLayout(self.grid)
        inner_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(inner)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)
        self.columns = 0

    def set_worlds(self, worlds, message=''):
        self.message.setText(message)
        self.message.setVisible(bool(message))
        clear_layout(self.grid)
        self.cards = []
        for info in worlds:
            card = WorldCard(info)
            card.clicked.connect(lambda c=card: self.chosen.emit(c.name))
            self.cards.append(card)
        self.columns = 0
        self._arrange()

    def _arrange(self):
        columns = max(1, (self.width() - 48 + 18) // (CARD_WIDTH + 18))
        if columns == self.columns:
            return
        self.columns = columns
        for card in self.cards:
            self.grid.removeWidget(card)
        for i, card in enumerate(self.cards):
            self.grid.addWidget(card, i // columns, i % columns)
        for c in range(self.grid.columnCount()):
            self.grid.setColumnStretch(c, 1 if c < columns else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._arrange()
