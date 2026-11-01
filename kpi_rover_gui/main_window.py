"""
The main window and its flow: worlds → the settings of one world → Next →
the run page. There everything is started by hand: the build, the
simulation world, then the robot at a place chosen on the map of the
generated world, objects put on the map, the Gazebo window and RViz, robot
control. Nothing starts by itself.

On the hub there is also the shared arena (kpi-arena): a world on the server
that robots from all sessions join. Joining it takes the place of starting the
simulation; the robot, RViz, the Gazebo window and robot control then talk to
the arena instead of a simulation of this session.
"""

import hashlib
import json
import os
import re
import signal
import time

from PyQt5.QtCore import QProcess, QSettings, Qt, QTimer
from PyQt5.QtGui import QGuiApplication, QKeySequence
from PyQt5.QtWidgets import (QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout, QInputDialog,
                             QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QShortcut, QStackedWidget,
                             QVBoxLayout, QWidget)

from . import theme
from . import workspace as ws_module
from .home_page import HomePage
from .run_page import ObjectsPanel, ProcessCard, RobotPanel, RunPage, option_check, package_box
from .runner import Runner
from .storage import LastUsed, Presets
from .world_page import WorldPage

DEFAULTS = {
    'workspace': '~/ros_ws',
    'ros_setup': '/opt/ros/jazzy/setup.bash',
}
# Lines of the logs: the generated world file, the world is up, the robot is ready, its controller failed.
WORLD_FILE_LINE = re.compile(r'World file: (\S+)')
WORLD_READY_LINE = re.compile(r'Serving world controls on \[/world/([^/\]]+)/control\]')
READY_LINE = 'diff_drive_controller into state active'
CONTROLLER_FAILED_LINE = 'Error activating controller'
# Maps of generated worlds, by the hash of the world file.
MAPS_DIR = os.path.join(os.path.expanduser('~'), '.cache', 'kpi_rover_gui', 'maps')
MAPS_KEEP = 20
# Height above the ground the robot and the objects are put at (m).
ROBOT_LIFT = 0.05
OBJECT_LIFT = 0.02


class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Preferences')
        self.settings = settings
        self.fields = {}
        form = QFormLayout()
        form.setSpacing(10)
        for key, text, is_dir in (('workspace', 'ROS workspace', True), ('ros_setup', 'ROS setup script', False)):
            edit = QLineEdit(settings.value(key, DEFAULTS[key]))
            edit.setMinimumWidth(380)
            browse = QPushButton('Browse…')
            browse.clicked.connect(lambda _, e=edit, d=is_dir: self._browse(e, d))
            row = QHBoxLayout()
            row.addWidget(edit, 1)
            row.addWidget(browse)
            form.addRow(text, row)
            self.fields[key] = edit
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.RestoreDefaults)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        buttons.button(QDialogButtonBox.RestoreDefaults).clicked.connect(
            lambda: [self.fields[k].setText(v) for k, v in DEFAULTS.items()])
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.addLayout(form)
        layout.addSpacing(8)
        layout.addWidget(buttons)

    def _browse(self, edit, is_dir):
        start = os.path.expanduser(edit.text())
        path = (QFileDialog.getExistingDirectory(self, 'Select folder', start) if is_dir
                else QFileDialog.getOpenFileName(self, 'Select file', start)[0])
        if path:
            edit.setText(path)

    def accept(self):
        for key, edit in self.fields.items():
            self.settings.setValue(key, edit.text().strip() or DEFAULTS[key])
        super().accept()


def flat(text, tip=''):
    button = QPushButton(text)
    button.setObjectName('Flat')
    button.setCursor(Qt.PointingHandCursor)
    button.setToolTip(tip)
    return button


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('KPI Rover')
        self.settings = QSettings('kpi_rover_gui', 'kpi_rover_gui')
        self.presets = Presets()
        self.last_used = LastUsed()
        self.worlds = {}
        self.world = None               # the world whose settings are open
        self.sim_world = None           # the world of the run page
        self.sim_command = None
        self.world_file = None          # the generated world file of the running simulation
        self.world_name = None          # its <world name>, once it is up
        self.world_map = None
        self.robot_ready = False
        self.controller_failed = False
        self.start_after_build = False
        self.placed = []                # [(model name, x, y, yaw, size x, size y, top z)] objects put on the map
        self.oneshots = []
        self.library = []
        self.map_dir = None
        self.restart_after_stop = False
        self.arena = None               # {world, world_args, ...} of the shared arena while the run page is for it
        self.arena_check = None         # the running 'kpi-arena info'
        self.arena_enter = False        # open the arena when the check is done

        self._build_ui()
        theme.current().changed.connect(self._update)
        self.clock = QTimer(self)
        self.clock.timeout.connect(self._update)
        self.clock.start(1000)

        geometry = self.settings.value('geometry')
        if geometry:
            self.restoreGeometry(geometry)
        else:
            self.resize(1440, 900)
        self.reload()

    # --- layout ---

    def _build_ui(self):
        header = QFrame()
        header.setObjectName('Header')
        head = QHBoxLayout(header)
        head.setContentsMargins(12, 8, 12, 8)
        self.back_button = flat('←  Worlds')
        self.back_button.clicked.connect(self.back)
        title = QLabel('KPI Rover')
        title.setObjectName('AppTitle')
        self.running_pill = QPushButton()
        self.running_pill.setObjectName('Pill')
        self.running_pill.setCursor(Qt.PointingHandCursor)
        self.running_pill.setToolTip('Open the run page')
        self.running_pill.clicked.connect(self.show_run)
        settings_button = flat('⚙  Preferences', 'Workspace and ROS paths')
        settings_button.clicked.connect(self.edit_settings)
        head.addWidget(self.back_button)
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.running_pill)
        head.addWidget(settings_button)

        self.home = HomePage()
        self.home.chosen.connect(self.open_world)
        self.home.arena_chosen.connect(lambda: self.check_arena(enter=True))
        self.page = WorldPage()
        self.page.changed.connect(self._update)
        self.page.save_preset.connect(self.save_preset)
        self.page.delete_preset.connect(self.delete_preset)
        self.run = RunPage()
        self._add_processes()
        self.stack = QStackedWidget()
        for page in (self.home, self.page, self.run):
            self.stack.addWidget(page)

        # The footer of the settings page.
        self.footer = QFrame()
        self.footer.setObjectName('Footer')
        foot = QHBoxLayout(self.footer)
        foot.setContentsMargins(16, 10, 16, 10)
        foot.setSpacing(12)
        self.footer_text = QLabel()
        self.footer_text.setObjectName('Muted')
        self.next_button = QPushButton('Next  ▸')
        self.next_button.setObjectName('Primary')
        self.next_button.setCursor(Qt.PointingHandCursor)
        self.next_button.setToolTip('To the run page, where you start the simulation with these settings (F5)')
        self.next_button.clicked.connect(self.next)
        foot.addWidget(self.footer_text, 1)
        foot.addWidget(self.next_button)

        central = QWidget()
        central.setObjectName('Window')
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(header)
        layout.addWidget(self.stack, 1)
        layout.addWidget(self.footer)
        self.setCentralWidget(central)

        QShortcut(QKeySequence('F5'), self, self.next)
        QShortcut(QKeySequence('Esc'), self, self.back)
        QShortcut(QKeySequence('Ctrl+R'), self, self.reload)

    def _add_processes(self):
        # In the arena the commands talk to it; the build and the map always run here.
        shell = lambda command: self.ws.shell(ws_module.in_arena(command) if self.arena else command)  # noqa: E731

        self.build_card = ProcessCard('Build', 'colcon build of the workspace.', self._build_command,
                                      lambda command: self.ws.shell(command, with_install=False), 'Build', 'Stop')
        self.build_card.idle_hook = self._build_status
        self.package = package_box([], self.settings.value('package', ws_module.PACKAGE))
        self.package.currentIndexChanged.connect(lambda: self.settings.setValue('package', self.package.currentData()))
        self.build_card.runner.finished.connect(self._build_finished)
        self.run.add(self.build_card, self.package)

        self.sim = ProcessCard('Simulation', 'Gazebo with the world. The robot is added next, at the place you '
                               'choose on the map of this world.', self._sim_command, shell, 'Start', 'Stop')
        self.sim.status_hook = self._sim_status
        self.sim.idle_hook = lambda: ('Ready to join the arena' if self.arena else 'Ready to start', 'accent') \
            if self.sim_command else ('Choose a world and its settings first', 'muted')
        self.sim.runner.line.connect(self._sim_line)
        self.sim.runner.finished.connect(self._sim_finished)
        self.sim.button.clicked.disconnect()
        self.sim.button.clicked.connect(self._sim_button)
        self.run.add(self.sim)

        self.robot_panel = RobotPanel()
        self.robot_panel.spawn.connect(self._robot_button)
        self.robot_panel.pose_changed.connect(self._remember_robot)
        self.robot_panel.pose_changed.connect(self._update)
        self.robot = ProcessCard('Robot', 'The robot with its controllers, localization, mapping and navigation, '
                                 'at the place on the map.', self._robot_command, shell, 'Put in', 'Take out')
        self.robot.status_hook = self._robot_status
        self.robot.idle_hook = self._robot_idle
        self.robot.runner.line.connect(self._robot_line)
        self.robot.runner.finished.connect(self._robot_finished)
        self.robot.button.clicked.disconnect()
        self.robot.button.clicked.connect(self._robot_button)
        self.run.add(self.robot, detail=self.robot_panel)

        self.objects_panel = ObjectsPanel()
        self.objects_panel.place.connect(self._place_object)
        self.objects_panel.remove_last.connect(lambda: self._remove_objects(self.placed[-1:]))
        self.objects_panel.remove_all.connect(lambda: self._remove_objects(list(self.placed)))
        self.objects = ProcessCard('Objects', 'Put boxes, crates and cones into the running world on its map.',
                                   lambda: None, shell, None)
        self.objects.idle_hook = self._objects_status
        self.run.add(self.objects, detail=self.objects_panel)

        # RViz and the Gazebo window are separate: the Gazebo window costs much CPU on a shared server.
        self.rviz = ProcessCard('RViz', 'See the robot sensors, the map and the navigation.',
                                lambda: ws_module.rviz_command(self.ws), shell, 'Open', 'Close')
        self.rviz_with_sim = option_check('Open with the simulation', self.settings.value('sim_rviz', False, type=bool))
        self.rviz_with_sim.toggled.connect(lambda on: self.settings.setValue('sim_rviz', on))
        self.run.add(self.rviz, self.rviz_with_sim)

        self.gazebo_window = ProcessCard('Gazebo window', 'See the simulated world in 3D (heavy on CPU).',
                                         lambda: ws_module.arena_gazebo_command() if self.arena else
                                         ws_module.gazebo_window_command(), shell, 'Open', 'Close')
        self.gazebo_with_sim = option_check('Open with the simulation',
                                            self.settings.value('sim_gazebo_window', False, type=bool))
        self.gazebo_with_sim.toggled.connect(lambda on: self.settings.setValue('sim_gazebo_window', on))
        self.run.add(self.gazebo_window, self.gazebo_with_sim)
        self.ui_cards = ((self.rviz, self.rviz_with_sim), (self.gazebo_window, self.gazebo_with_sim))

        self.keyboard = ProcessCard('Keyboard control', 'Drive the robot with the keys, in a terminal window '
                                    '(close the window to stop).', lambda: ws_module.keyboard_command(self.ws, bool(self.arena)),
                                    shell, 'Open', 'Close')
        self.keyboard.button.setEnabled(ws_module.terminal() is not None)
        self.run.add(self.keyboard)

        self.joystick = ProcessCard('Gamepad control', 'Drive the robot with a gamepad (joystick.launch.py).',
                                    ws_module.joystick_command, shell)
        self.run.add(self.joystick)

        self.map_runner = Runner(self)
        self.map_runner.line.connect(self.robot.log.add_line)
        self.map_runner.finished.connect(self._map_finished)
        self.run.select(self.sim)

    @property
    def ws(self):
        return ws_module.Workspace(self.settings.value('workspace', DEFAULTS['workspace']),
                                   self.settings.value('ros_setup', DEFAULTS['ros_setup']))

    # --- navigation ---

    def reload(self):
        """Read the worlds, the packages and the object library of the workspace again."""
        ws = self.ws
        self.setWindowTitle(f'KPI Rover — {ws.path}')
        problems = ws.problems()
        self.worlds = {}
        message = '\n'.join(problems)
        if not problems:
            try:
                worlds, _ = ws.load_worlds()
                self.worlds = {w['name']: w for w in worlds}
            except (ws_module.WorkspaceError, OSError, ValueError) as e:
                message = str(e)
        if message:
            message += '\nCheck the paths in Preferences.'
        self.home.set_worlds(list(self.worlds.values()), message)
        if ws_module.arena_available() and not problems:
            self.check_arena()
        current = self.package.currentData() or self.settings.value('package', ws_module.PACKAGE)
        self.package.blockSignals(True)
        self.package.clear()
        self.package.addItem('All packages', None)
        for name in ([] if problems else ws.packages()):
            self.package.addItem(name, name)
        index = self.package.findData(current)
        self.package.setCurrentIndex(index if index >= 0 else 0)
        self.package.blockSignals(False)
        self.library = [] if problems else ws.object_library()
        self.objects_panel.set_library(self.library)
        if self.stack.currentWidget() is self.page and self.world in self.worlds:
            world, self.world = self.world, None
            self.open_world(world)
        elif self.stack.currentWidget() is not self.run:
            self.show_home()
        self._update()

    def back(self):
        if self.stack.currentWidget() is self.run and self.arena:
            self.show_home()
        elif self.stack.currentWidget() is self.run:
            self.open_world(self.sim_world or self.world)
        elif self.stack.currentWidget() is self.page:
            self.show_home()

    def show_home(self):
        self._remember()
        self.stack.setCurrentWidget(self.home)
        self._update()

    def open_world(self, name):
        if self.stack.currentWidget() is self.page and name == self.world:
            return
        self._remember()
        info = self.worlds.get(name)
        if not info:
            self.show_home()
            return
        self.world = name
        rejected = self.page.set_world(info, self.last_used.get(name), self._own_presets())
        self.stack.setCurrentWidget(self.page)
        self.footer_text.setText(f"Not restored (not valid any more): {', '.join(rejected)}" if rejected else '')
        self._update()

    def show_run(self):
        self._remember()
        self.stack.setCurrentWidget(self.run)
        self._update()

    def _remember(self):
        if self.world and self.stack.currentWidget() is self.page:
            settings = dict(self.last_used.get(self.world) or {}, **self.page.settings())
            self.last_used.put(self.world, settings)

    def _remember_robot(self):
        if self.sim_world and not self.robot.running():
            x, y, yaw, start = self.robot_panel.pose()
            settings = dict(self.last_used.get(self.sim_world) or {}, robot=[x, y, yaw, start])
            self.last_used.put(self.sim_world, settings)

    # --- presets ---

    def _own_presets(self):
        return {name: (self.presets.get(self.world, name) or {}).get('args', {})
                for name in self.presets.names(self.world)}

    def save_preset(self):
        name, ok = QInputDialog.getText(self, 'Save preset', 'Name of the preset:')
        name = name.strip()
        if not ok or not name:
            return
        if self.presets.get(self.world, name) is not None and QMessageBox.question(
                self, 'Save preset', f"Replace the preset «{name}»?") != QMessageBox.Yes:
            return
        self.presets.put(self.world, name, {'args': self.page.settings()['args']})
        self.page.set_own_presets(self._own_presets())

    def delete_preset(self, name):
        if QMessageBox.question(self, 'Delete preset', f"Delete the preset «{name}»?") == QMessageBox.Yes:
            self.presets.delete(self.world, name)
            self.page.set_own_presets(self._own_presets())

    # --- from the settings to the run page ---

    def _settings_command(self):
        return ws_module.sim_command(self.world, self.page.settings()['args'], ui=False, robot=False)

    def next(self):
        """Take the settings of the open world to the run page; start nothing."""
        if self.stack.currentWidget() is not self.page or not self.world:
            return
        command = self._settings_command()
        if self.sim.running() and (self.sim_world != self.world or command != self.sim_command):
            box = QMessageBox(QMessageBox.Question, 'Next', 'The simulation is running with other settings.',
                              parent=self)
            restart = box.addButton('Restart it with these settings', QMessageBox.AcceptRole)
            keep = box.addButton('Keep it running', QMessageBox.RejectRole)
            box.setDefaultButton(keep)
            box.exec_()
            if box.clickedButton() == restart:
                self._take_settings(command)
                self.restart_after_stop = True
                self.stop_sim()
            self.show_run()
            return
        if not self.sim.running():
            self._take_settings(command)
        self.show_run()

    def _take_settings(self, command):
        self._remember()
        self._set_arena(None)
        self.sim_world = self.world
        self.sim_command = command
        self.run.set_world(self.worlds[self.world]['title'], self.page.summary())
        self.run.select(self.sim)

    # --- the shared arena ---

    def check_arena(self, enter=False):
        """Ask the arena for its world (kpi-arena info) for its card; with 'enter' then open its run page."""
        self.arena_enter = self.arena_enter or enter
        if self.arena_check is not None:
            return
        process = QProcess(self)
        process.finished.connect(lambda *_: self._arena_checked(process))
        self.arena_check = process
        process.start(ws_module.ARENA, ['info'])

    def _arena_checked(self, process):
        self.arena_check = None
        output = bytes(process.readAllStandardOutput()).decode('utf-8', 'replace').strip()
        try:
            info = json.loads(output.splitlines()[-1]) if process.exitCode() == 0 and output else None
        except ValueError:
            info = None
        enter, self.arena_enter = self.arena_enter, False
        if not info or 'world' not in info:
            # Not running: clicking the card looks again
            self.home.set_arena(dict(title='Shared arena', ribbon='OFFLINE', ribbon_color='danger'))
            return
        world = self.worlds.get(info['world'], {})
        self.home.set_arena(dict(title=f"Shared arena ({world.get('title', info['world'])})", image=world.get('image'),
                                 ribbon='JOIN'))
        if enter:
            self.enter_arena(info)

    def enter_arena(self, info):
        if self.sim.running() and self.arena != info:
            box = QMessageBox(QMessageBox.Question, 'Shared arena', 'Your simulation is running. '
                              'Stop it to join the arena?', parent=self)
            stop = box.addButton('Stop it and join', QMessageBox.AcceptRole)
            box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(stop)
            box.exec_()
            if box.clickedButton() != stop:
                return
            self.stop_sim()
            self._set_arena(info)
            self.restart_after_stop = True
        elif not self.sim.running():
            self._set_arena(info)
        self.show_run()

    def _set_arena(self, info):
        """Make the run page the one of the arena ({world, world_args, ...}), or of this session's own simulation."""
        self.arena = info
        self.sim.start_text, self.sim.stop_text = ('Join', 'Leave') if info else ('Start', 'Stop')
        if not info:
            return
        self.sim_world = info['world']
        self.sim_command = ws_module.arena_watch_command()
        title = self.worlds.get(self.sim_world, {}).get('title', self.sim_world)
        details = ', '.join(f'{k} {info[k]}' for k in ('world_args', 'floor', 'marking') if info.get(k))
        self.run.set_world(f'Shared arena · {title}', 'One world on the server for everybody: join it, then put '
                           'your robot in at a free place. Your robot’s navigation runs in your session.'
                           + (f' World settings: {details}.' if details else ''))
        self.run.select(self.sim)

    # --- simulation ---

    def _sim_command(self):
        return self.sim_command

    def _sim_button(self):
        if self.sim.running():
            self.stop_sim()
        else:
            self.start_sim()

    def start_sim(self):
        if self.sim.running() or not self.sim_command:
            return
        ws = self.ws
        if not ws.is_built() or ws.worlds_outdated():
            box = QMessageBox(QMessageBox.Question, 'Start',
                              'The workspace is not built yet.' if not ws.is_built() else
                              'The worlds changed since the last build: the simulation would use the old ones.',
                              parent=self)
            build = box.addButton('Build first, then start', QMessageBox.AcceptRole)
            anyway = box.addButton('Start anyway', QMessageBox.DestructiveRole) if ws.is_built() else None
            box.addButton(QMessageBox.Cancel)
            box.setDefaultButton(build)
            box.exec_()
            if box.clickedButton() == build:
                self.package.setCurrentIndex(max(0, self.package.findData(ws_module.PACKAGE)) if ws.is_built()
                                             else 0)
                self.start_after_build = True
                self.run.select(self.build_card)
                self.build_card.start()
                return
            if anyway is None or box.clickedButton() != anyway:
                return
        stray = [] if self.arena else ws_module.running_gazebo()
        if stray:
            answer = QMessageBox.question(
                self, 'Start', f'Another Gazebo is running ({len(stray)} processes); two simulations would '
                'conflict.\n\nStop it?', QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
            if answer == QMessageBox.Cancel:
                return
            if answer == QMessageBox.Yes:
                self._kill_processes([pid for pid, _ in stray])
        self.world_file = self.world_name = self.world_map = None
        self.placed = []
        self._show_placed()
        self._set_maps(None, 'Getting the map of the arena…' if self.arena else 'Making the map of this world…')
        self.run.select(self.sim)
        if self.sim.start():
            for card, with_sim in self.ui_cards:
                if with_sim.isChecked():
                    card.start()
        self._update()

    def stop_sim(self):
        for card in (self.robot, self.joystick, self.rviz, self.gazebo_window, self.sim):
            card.stop()
        self.map_runner.stop()
        self._update()

    def _sim_status(self):
        title = self.worlds.get(self.sim_world, {}).get('title', self.sim_world or '')
        if self.arena:
            return ((f'In the arena · {title} · {self.sim.clock()}', 'success') if self.world_name else
                    (f'Getting the map of the arena… {self.sim.clock()}', 'warning'))
        if self.world_name:
            return f'{title} running · {self.sim.clock()}', 'success'
        return f'{title} starting… {self.sim.clock()}', 'warning'

    def _sim_line(self, text):
        match = WORLD_FILE_LINE.search(text)
        if match and not self.world_file:
            self.world_file = match.group(1)
            self._make_map()
        match = WORLD_READY_LINE.search(text)
        if match and not self.world_name:
            self.world_name = match.group(1)
            self._update()
        if text.startswith(ws_module.ARENA_MAP) and self.arena:
            # The map made by the arena; its Gazebo world is named as the arena world
            self.map_dir = text[len(ws_module.ARENA_MAP):].strip()
            self.world_name = self.arena['world']
            self._load_map()
            self._update()

    def _sim_finished(self, code):
        for card in (self.robot, self.joystick, self.rviz, self.gazebo_window):
            card.stop()
        self.map_runner.stop()
        self.world_file = self.world_name = None
        self.placed = []
        self._show_placed()
        self._set_maps(self.world_map, '')
        if self.restart_after_stop:
            self.restart_after_stop = False
            self.start_sim()
        self._update()

    # --- the map of the generated world ---

    def _make_map(self):
        """The map of the generated world: from the cache, or rendered by a hidden Gazebo of its own."""
        try:
            with open(self.world_file, 'rb') as f:
                key = hashlib.sha1(f.read()).hexdigest()[:16]
        except OSError:
            self._set_maps(None, f'The world file {self.world_file} is not readable.')
            return
        self.map_dir = os.path.join(MAPS_DIR, key)
        if os.path.isfile(os.path.join(self.map_dir, 'map.json')):
            self._load_map()
            return
        self._set_maps(None, 'Making the map of this world… (about half a minute)')
        self.robot.log.add_line('--- Making the map of the generated world ---')
        command = self.ws.map_command(self.sim_world, self.world_file, self.map_dir, f'kpi_rover_gui_map_{os.getpid()}')
        self.map_runner.start(self.ws.shell(command))

    def _map_finished(self, code):
        if code == 0 and os.path.isfile(os.path.join(self.map_dir, 'map.json')):
            self._load_map()
            self._clean_maps()
        elif self.sim.running():
            self._set_maps(None, 'The map could not be made — see the Robot log. You can still type the position.')

    def _load_map(self):
        with open(os.path.join(self.map_dir, 'map.json')) as f:
            world_map = dict(json.load(f), image=os.path.join(self.map_dir, 'map.jpg'))
        self.world_map = world_map
        self._set_maps(world_map, '')
        # The robot where it was last time in this world, or at the first start point.
        last = (self.last_used.get(self.sim_world) or {}).get('robot')
        points = world_map.get('start_points', {})
        if last and last[3] in points:
            self.robot_panel.choose_start(last[3])
        elif last and not last[3]:
            self.robot_panel.set_pose(last[0], last[1], last[2])
        elif points:
            self.robot_panel.choose_start(next(iter(points)))
        else:
            self.robot_panel.set_pose(*world_map.get('center', [0, 0]), 0.0)
        self._update()

    def _set_maps(self, world_map, placeholder):
        labels = {p['name']: p['label'] for p in self.worlds.get(self.sim_world, {}).get('start_points', [])}
        self.robot_panel.set_map(world_map, placeholder, labels)
        self.objects_panel.set_map(world_map, placeholder)
        self._update()

    @staticmethod
    def _clean_maps():
        maps = sorted((os.path.join(MAPS_DIR, d) for d in os.listdir(MAPS_DIR)), key=os.path.getmtime)
        for old in maps[:-MAPS_KEEP]:
            for f in os.listdir(old):
                os.remove(os.path.join(old, f))
            os.rmdir(old)

    # --- robot ---

    def _robot_command(self):
        x, y, yaw, _ = self.robot_panel.pose()
        ok, z, _ = self.robot_panel.check()
        if not ok:
            return None
        command = ws_module.arena_robot_command if self.arena else ws_module.robot_command
        return command(x, y, z + ROBOT_LIFT, yaw)

    def _robot_button(self):
        if self.robot.running():
            self.robot.stop()
        elif self.world_name:
            self.robot_ready = False
            self.controller_failed = False
            self._remember_robot()
            self.robot.start()
        self._update()

    def _robot_idle(self):
        if not self.sim.running():
            return ('Join the arena first' if self.arena else 'Start the simulation first'), 'muted'
        if not self.world_name:
            return 'Waiting for the world…', 'warning'
        return 'Choose the place on the map, then put the robot in', 'accent'

    def _robot_status(self):
        if self.controller_failed:
            return f'Controller did not start — the robot won’t drive · {self.robot.clock()}', 'danger'
        if self.robot_ready:
            return f'In the world · {self.robot.clock()}', 'success'
        return f'Starting… {self.robot.clock()}', 'warning'

    def _robot_line(self, text):
        if READY_LINE in text:
            self.robot_ready = True
            self._update()
        elif CONTROLLER_FAILED_LINE in text:
            self.controller_failed = True
            self._update()

    def _robot_finished(self, code):
        # Take the robot model out of the world, so it can be put in again.
        # In the arena kpi-arena does it, and only for the robot it put in.
        if self.world_name and self.sim.running() and not self.arena:
            self._oneshot(ws_module.remove_model_command(self.world_name, ws_module.ROBOT_MODEL), self.robot.log)
        self.robot_ready = False
        self._update()

    # --- objects ---

    def _objects_status(self):
        if self.arena:
            return 'Not in the shared arena', 'muted'
        if not self.world_name:
            return 'Start the simulation first', 'muted'
        return (f'{len(self.placed)} placed — click the map to add more', 'success') if self.placed else \
            ('Click the map to put an object', 'accent')

    def _place_object(self, kind, x, y, yaw):
        if not self.world_name or self.arena:
            return
        number = 1 + max([int(p[0].rsplit('_', 1)[1]) for p in self.placed] or [0])
        name = f'placed_{number}'
        scale = self.worlds.get(self.sim_world, {}).get('objects_scale', 1.0)
        sx, sy, sz = (s * scale for s in next((o['size'] for o in self.library if o['name'] == kind), [0.3] * 3))
        # On the highest surface under it (the ground, a deck, another object), so it never starts inside.
        heights = [h for h in self.objects_panel.map.footprint(x, y, yaw, sx, sy) if h is not None] or [0.0]
        z = max(heights) + OBJECT_LIFT
        self._oneshot(self.ws.spawn_object_command(self.world_name, name, kind, x, y, z, yaw, scale), self.objects.log)
        self.placed.append((name, x, y, yaw, sx, sy, z + sz))
        self._show_placed()
        self._update()

    def _show_placed(self):
        """The placed objects on both maps; the robot place is checked against them too."""
        shown = [p[1:] for p in self.placed]
        self.objects_panel.set_objects(shown)
        self.robot_panel.map.set_objects(shown)
        self.robot_panel.check()

    def _remove_objects(self, objects):
        if not self.world_name or self.arena:
            return
        for name, *_ in objects:
            self._oneshot(ws_module.remove_model_command(self.world_name, name), self.objects.log)
            self.placed = [p for p in self.placed if p[0] != name]
        self._show_placed()
        self._update()

    def _oneshot(self, command, log):
        """Run a short command (spawning or removing a model), its output in a log."""
        log.add_line(f'--- {command} ---')
        process = QProcess(self)
        process.setProcessChannelMode(QProcess.MergedChannels)
        process.readyReadStandardOutput.connect(
            lambda: [log.add_line(line) for line in
                     bytes(process.readAllStandardOutput()).decode('utf-8', 'replace').splitlines() if line.strip()])
        process.finished.connect(lambda *_: self.oneshots.remove(process) if process in self.oneshots else None)
        argv = self.ws.shell(command)
        self.oneshots.append(process)
        process.start(argv[0], argv[1:])

    # --- build ---

    def _build_command(self):
        package = self.package.currentData()
        return ws_module.build_command([package] if package else None)

    def _build_status(self):
        ws = self.ws
        if ws.problems():
            return 'The workspace is not found — see Preferences', 'danger'
        if not ws.is_built():
            return 'Not built yet', 'warning'
        if ws.worlds_outdated():
            return 'Build needed: the worlds changed since the last build', 'warning'
        return 'Up to date', 'muted'

    def _build_finished(self, code):
        start, self.start_after_build = self.start_after_build, False
        self.reload()
        if code == 0 and start:
            self.start_sim()
        self._update()

    @staticmethod
    def _kill_processes(pids):
        for sig in (signal.SIGINT, signal.SIGTERM, signal.SIGKILL):
            for pid in pids:
                try:
                    os.kill(pid, sig)
                except (ProcessLookupError, PermissionError):
                    pass
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline and any(os.path.exists(f'/proc/{pid}') for pid in pids):
                time.sleep(0.1)
            if not any(os.path.exists(f'/proc/{pid}') for pid in pids):
                return

    # --- state ---

    def _update(self):
        current = self.stack.currentWidget()
        self.back_button.setVisible(current is not self.home)
        self.back_button.setText('←  World settings' if current is self.run else '←  Worlds')
        self.footer.setVisible(current is self.page)
        running = [c for c in self.run.cards if c.running()]
        if running and current is not self.run:
            title = self.worlds.get(self.sim_world, {}).get('title', '')
            self.running_pill.setText(f'●  {title} running' if self.sim.running() else
                                      f'●  {running[0].title} running')
        self.running_pill.setVisible(bool(running) and current is not self.run)
        live = self.robot.running()
        place_ok = not self.robot_panel.problem
        self.robot.button.setEnabled((bool(self.world_name) and place_ok) or live)
        self.robot_panel.spawn_button.setEnabled(bool(self.world_name) and place_ok and not live)
        if live:
            hint = 'The robot is in the world. Take it out to put it somewhere else.'
        elif not place_ok:
            hint = self.robot_panel.problem + ' Choose another place.'
        else:
            hint = 'Press on the map to put the robot there, drag to turn it; or take a start point.'
        self.robot_panel.set_live(live, hint)
        self.sim.button.setEnabled(bool(self.sim_command) or self.sim.running())
        self.run.refresh()

    def edit_settings(self):
        if SettingsDialog(self.settings, self).exec_() == QDialog.Accepted:
            self._remember()
            self.reload()

    def closeEvent(self, event):
        running = [c for c in self.run.cards if c.running()]
        if running:
            answer = QMessageBox.question(self, 'Quit', f"Still running: {', '.join(c.title for c in running)}.\n\n"
                                          'Stop everything and quit?')
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            QGuiApplication.processEvents()
            for card in running:
                card.runner.stop_and_wait()
        self.map_runner.stop_and_wait()
        self._remember()
        self.settings.setValue('geometry', self.saveGeometry())
        event.accept()
