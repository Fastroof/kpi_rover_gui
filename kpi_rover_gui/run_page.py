"""
The run page: what runs (the build, the simulation world, the robot, the
Gazebo window and RViz, robot control), each with its state and start/stop
button, and the log of the selected one. The robot and the objects are put
into the world on its map (RobotPanel, ObjectsPanel).
"""

import math
import random
import time

from PyQt5.QtCore import Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QGuiApplication
from PyQt5.QtWidgets import (QAbstractSpinBox, QCheckBox, QComboBox, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton,
                             QScrollArea, QSplitter, QVBoxLayout, QWidget)

from . import controls, theme
from .map_view import MapView
from .runner import Runner
from .widgets import Clickable, FlowLayout, LogView, clear_layout, set_flag


def _label(text, name=None, wrap=False):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


class ProcessCard(Clickable):
    """
    One thing that runs: its name and what it is, its state, a start/stop
    button and its output (shown in the log panel when the card is selected).
    'command' returns the shell command to run (or None if it can't run now).
    """
    state_changed = pyqtSignal()

    def __init__(self, title, description, command, shell, start_text='Start', stop_text='Stop', parent=None):
        super().__init__(parent)
        self.setObjectName('ProcessCard')
        self.title = title
        self.command = command
        self.shell = shell
        self.start_text = start_text
        self.stop_text = stop_text
        self.runner = Runner(self)
        self.log = LogView()
        self.started_at = None
        self.last_code = None
        self.stop_requested = False
        self.last_command = ''
        self.status_hook = None     # () -> (text, color token) to override the running state
        self.idle_hook = None       # () -> (text, color token) or None, for the state when not running
        self.runner.line.connect(self.log.add_line)
        self.runner.started.connect(self.state_changed)
        self.runner.finished.connect(self._finished)

        heading = _label(title)
        font = heading.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.05)
        heading.setFont(font)
        self.dot = _label('●')
        self.status = _label('', 'Muted')
        self.button = QPushButton(start_text or '')
        self.button.setCursor(Qt.PointingHandCursor)
        self.button.clicked.connect(self.toggle)
        self.button.setVisible(start_text is not None)
        top = QHBoxLayout()
        top.addWidget(heading, 1)
        top.addWidget(self.button)
        state = QHBoxLayout()
        state.setSpacing(6)
        state.addWidget(self.dot)
        state.addWidget(self.status, 1)
        self.body = QVBoxLayout(self)
        self.body.setContentsMargins(14, 12, 14, 12)
        self.body.setSpacing(6)
        self.body.addLayout(top)
        if description:
            self.body.addWidget(_label(description, 'Hint', wrap=True))
        self.body.addLayout(state)
        self.refresh()

    def running(self):
        return self.runner.running()

    def toggle(self):
        if self.running():
            self.stop()
        else:
            self.start()

    def start(self):
        if self.running():
            return False
        command = self.command()
        if not command:
            return False
        self.log.reset()
        self.log.add_line(f'--- {command} ---')
        self.last_command = command
        self.started_at = time.monotonic()
        self.last_code = None
        self.stop_requested = False
        self.runner.start(self.shell(command))
        self.refresh()
        return True

    def stop(self):
        if self.running():
            self.stop_requested = True
        self.runner.stop()
        self.refresh()

    def _finished(self, code):
        # Stopped on purpose: not an error, whatever the exit code.
        self.last_code = None if self.stop_requested else code
        self.log.add_line(f"--- Finished{'' if code == 0 else f' (exit code {code})'} ---")
        self.started_at = None
        self.refresh()
        self.state_changed.emit()

    def clock(self):
        seconds = int(time.monotonic() - (self.started_at or time.monotonic()))
        return f'{seconds // 60}:{seconds % 60:02d}'

    def refresh(self):
        t = theme.current()
        if self.running() and self.runner.stopping:
            text, color = 'Stopping…', 'warning'
        elif self.running():
            text, color = (self.status_hook() if self.status_hook else None) or (f'Running · {self.clock()}',
                                                                                 'success')
        elif self.last_code not in (None, 0):
            text, color = f'Ended with an error (exit code {self.last_code})', 'danger'
        else:
            text, color = (self.idle_hook() if self.idle_hook else None) or ('Not running', 'muted')
        self.dot.setStyleSheet(f'color: {t[color]};')
        self.status.setText(text)
        running = self.running()
        self.button.setText((self.stop_text if running else self.start_text) or '')
        self.button.setObjectName('DangerSmall' if running else 'PrimarySmall')
        self.button.style().unpolish(self.button)
        self.button.style().polish(self.button)


class RunPage(QWidget):
    """What runs, and the log of the selected process."""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('Page')
        self.cards = []
        self.selected = None
        self.world_title = _label('', 'PageTitle')
        self.world_summary = _label('', 'Muted', wrap=True)
        self.list = QVBoxLayout()
        self.list.setSpacing(10)
        left_widget = QWidget()
        left = QVBoxLayout(left_widget)
        left.setContentsMargins(0, 0, 8, 0)
        left.setSpacing(8)
        left.addWidget(self.world_title)
        left.addWidget(self.world_summary)
        left.addSpacing(6)
        left.addLayout(self.list)
        left.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(left_widget)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFixedWidth(380)

        self.log_title = _label('')
        font = self.log_title.font()
        font.setBold(True)
        self.log_title.setFont(font)
        copy = QPushButton('Copy command')
        copy.setObjectName('Flat')
        copy.setToolTip('Copy the command of this process, to run it in a terminal')
        copy.clicked.connect(self._copy)
        clear = QPushButton('Clear')
        clear.setObjectName('Flat')
        clear.clicked.connect(lambda: self.selected and self.selected.log.reset())
        head = QHBoxLayout()
        head.addWidget(self.log_title, 1)
        head.addWidget(copy)
        head.addWidget(clear)
        self.detail_area = QWidget()
        self.detail_layout = QVBoxLayout(self.detail_area)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        log_widget = QWidget()
        log_layout = QVBoxLayout(log_widget)
        log_layout.setContentsMargins(0, 0, 0, 0)
        log_layout.setSpacing(8)
        log_layout.addLayout(head)
        self.log_area = QVBoxLayout()
        self.log_area.setContentsMargins(0, 0, 0, 0)
        log_layout.addLayout(self.log_area, 1)
        self.split = QSplitter(Qt.Vertical)
        self.split.addWidget(self.detail_area)
        self.split.addWidget(log_widget)
        self.split.setStretchFactor(0, 3)
        self.split.setStretchFactor(1, 1)
        self.split.setChildrenCollapsible(False)
        right = QVBoxLayout()
        right.addWidget(self.split, 1)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(16)
        layout.addWidget(scroll)
        layout.addLayout(right, 1)

        self.clock = QTimer(self)
        self.clock.timeout.connect(self.refresh)
        self.clock.start(1000)

    def add(self, card, extra=None, detail=None):
        """
        Add a process card, with an extra widget (options) under its
        description, and a detail widget shown above its log when selected.
        """
        if extra is not None:
            card.body.insertWidget(card.body.count() - 1, extra)
        card.detail = detail
        if detail is not None:
            self.detail_layout.addWidget(detail)
            detail.hide()
        card.clicked.connect(lambda: self.select(card))
        card.state_changed.connect(self.refresh)
        self.list.addWidget(card)
        self.log_area.addWidget(card.log)
        card.log.hide()
        self.cards.append(card)
        if self.selected is None:
            self.select(card)
        return card

    def select(self, card):
        self.selected = card
        for c in self.cards:
            set_flag(c, 'selected', c is card)
            c.log.setVisible(c is card)
            if c.detail is not None:
                c.detail.setVisible(c is card)
        self.detail_area.setVisible(card.detail is not None)
        if card.detail is not None:
            total = sum(self.split.sizes()) or 800
            self.split.setSizes([int(total * 0.72), int(total * 0.28)])
        self.log_title.setText(f'{card.title} — log')

    def set_world(self, title, summary):
        self.world_title.setText(title)
        self.world_summary.setText(summary)

    def refresh(self):
        for card in self.cards:
            card.refresh()

    def _copy(self):
        if self.selected and (self.selected.last_command or self.selected.command()):
            QGuiApplication.clipboard().setText(self.selected.last_command or self.selected.command())


def package_box(packages, current):
    box = QComboBox()
    box.addItem('All packages', None)
    for package in packages:
        box.addItem(package, package)
    index = box.findData(current)
    box.setCurrentIndex(index if index >= 0 else 0)
    return box


def option_check(text, checked):
    check = QCheckBox(text)
    check.setChecked(checked)
    return check


def _pose_box(limit, decimals, unit, tip):
    box = controls.no_wheel(QDoubleSpinBox())
    box.setRange(-limit, limit)
    box.setDecimals(decimals)
    box.setSingleStep(0.1)
    box.setButtonSymbols(QAbstractSpinBox.NoButtons)
    box.setSuffix(f' {unit}')
    box.setFixedWidth(86)
    box.setToolTip(tip)
    return box


class RobotPanel(QWidget):
    """Where the robot starts: the map of the running world, its start points and the pose."""
    spawn = pyqtSignal()
    pose_changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.map = MapView()
        self.map.robot_moved.connect(self._moved)
        self.hint = _label('', 'Muted', wrap=True)
        self.points = QWidget()
        self.points_flow = FlowLayout(self.points)
        self.boxes = [_pose_box(1000, 2, 'm', 'East'), _pose_box(1000, 2, 'm', 'North'),
                      _pose_box(math.pi, 2, 'rad', 'Heading: 0 — east, 1.57 — north')]
        pose = QHBoxLayout()
        for name, box in zip(('x', 'y', 'heading'), self.boxes):
            box.valueChanged.connect(self._typed)
            pose.addWidget(_label(name, 'Muted'))
            pose.addWidget(box)
        pose.addStretch(1)
        self.spawn_button = QPushButton('Put the robot here')
        self.spawn_button.setObjectName('PrimarySmall')
        self.spawn_button.setCursor(Qt.PointingHandCursor)
        self.spawn_button.clicked.connect(self.spawn)
        pose.addWidget(self.spawn_button)
        side = QVBoxLayout()
        side.setSpacing(10)
        side.addWidget(_label('START POINTS', 'Section'))
        side.addWidget(self.points)
        side.addWidget(self.hint)
        side.addStretch(1)
        side_widget = QWidget()
        side_widget.setLayout(side)
        side_widget.setFixedWidth(230)
        top = QHBoxLayout()
        top.setSpacing(14)
        top.addWidget(self.map, 1)
        top.addWidget(side_widget)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        layout.addLayout(top, 1)
        layout.addLayout(pose)
        self.start = ''
        self.problem = ''
        self.set_map(None, 'Start the simulation: its map appears here.')

    def set_map(self, world_map, placeholder='', labels=None):
        """The map of the world; labels {start point name: label} name the start points."""
        self.map.set_map(world_map, placeholder)
        self.map.set_mode('robot')
        clear_layout(self.points_flow)
        for name in self.map.points():
            chip = QPushButton((labels or {}).get(name, name))
            chip.setToolTip(f'start:={name}')
            chip.setObjectName('Chip')
            chip.setCheckable(True)
            chip.setCursor(Qt.PointingHandCursor)
            chip.clicked.connect(lambda _, n=name: self.choose_start(n))
            chip.start_name = name
            self.points_flow.addWidget(chip)
        self._update_chips()

    def choose_start(self, name):
        x, y, yaw = self.map.points()[name]
        self.set_pose(x, y, yaw, name)

    def set_pose(self, x, y, yaw, start=''):
        self.start = start
        for box, v in zip(self.boxes, (x, y, yaw)):
            box.blockSignals(True)
            box.setValue(v)
            box.blockSignals(False)
        self.map.set_robot(x, y, yaw, start, self.map.robot_live)
        self._update_chips()
        self.check()
        self.pose_changed.emit()

    def check(self):
        """Whether the robot can be put where it is: (ok, height to put it at, why not)."""
        x, y, yaw, _ = self.pose()
        ok, z, reason = self.map.place_check(x, y, yaw)
        self.map.robot_ok = ok
        self.map.update()
        self.problem = reason
        return ok, z, reason

    def pose(self):
        """(x, y, yaw, start point name or '')."""
        return self.boxes[0].value(), self.boxes[1].value(), self.boxes[2].value(), self.start

    def set_live(self, live, hint):
        """The robot is (or is not) in the simulation: then its place can't be changed."""
        self.map.robot_live = live
        self.map.update()
        for box in self.boxes:
            box.setEnabled(not live)
        for i in range(self.points_flow.count()):
            self.points_flow.itemAt(i).widget().setEnabled(not live)
        self.hint.setText(hint)

    def _moved(self, x, y, yaw, start):
        self.set_pose(x, y, math.atan2(math.sin(yaw), math.cos(yaw)), start)

    def _typed(self):
        x, y, yaw = (b.value() for b in self.boxes)
        self.start = ''
        self.map.set_robot(x, y, yaw, '', self.map.robot_live)
        self._update_chips()
        self.check()
        self.pose_changed.emit()

    def _update_chips(self):
        for i in range(self.points_flow.count()):
            chip = self.points_flow.itemAt(i).widget()
            chip.setChecked(chip.start_name == self.start)


class ObjectsPanel(QWidget):
    """Putting library objects into the running world: click the map where."""
    place = pyqtSignal(str, float, float, float)     # type, x, y, yaw
    remove_last = pyqtSignal()
    remove_all = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.library = {}
        self.map = MapView()
        self.map.set_mode('objects')
        self.map.object_requested.connect(self._clicked)
        self.kind = QComboBox()
        self.kind.setMinimumWidth(200)
        self.random_turn = QCheckBox('Turn it at random')
        self.random_turn.setChecked(True)
        self.count = _label('', 'Muted')
        undo = QPushButton('Remove the last one')
        undo.clicked.connect(self.remove_last)
        clear = QPushButton('Remove all placed')
        clear.clicked.connect(self.remove_all)
        side = QVBoxLayout()
        side.setSpacing(10)
        side.addWidget(_label('OBJECT', 'Section'))
        side.addWidget(self.kind)
        side.addWidget(self.random_turn)
        side.addWidget(_label('Click the map to put the object there. Objects scattered by the world settings '
                              'are already on the map.', 'Hint', wrap=True))
        side.addSpacing(6)
        side.addWidget(self.count)
        side.addWidget(undo)
        side.addWidget(clear)
        side.addStretch(1)
        side_widget = QWidget()
        side_widget.setLayout(side)
        side_widget.setFixedWidth(230)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(14)
        layout.addWidget(self.map, 1)
        layout.addWidget(side_widget)
        self.set_objects([])
        self.set_map(None, 'Start the simulation: its map appears here.')

    def set_library(self, library):
        """library: [{name, kind, size}]."""
        self.library = {o['name']: o for o in library}
        current = self.kind.currentData()
        self.kind.clear()
        for kind in ('item', 'cone'):
            for o in library:
                if o['kind'] == kind:
                    self.kind.addItem(o['name'].replace('_', ' '), o['name'])
        index = self.kind.findData(current)
        self.kind.setCurrentIndex(max(0, index))

    def set_map(self, world_map, placeholder=''):
        self.map.set_map(world_map, placeholder)
        self.map.set_mode('objects')

    def set_objects(self, objects):
        """objects: [(x, y, yaw, size x, size y, top z)] placed so far."""
        self.map.set_objects(objects)
        self.count.setText(f'{len(objects)} placed' if objects else 'None placed yet')

    def _clicked(self, x, y):
        kind = self.kind.currentData()
        if kind:
            yaw = random.uniform(-math.pi, math.pi) if self.random_turn.isChecked() else 0.0
            self.place.emit(kind, x, y, yaw)
