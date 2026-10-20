"""
The ROS workspace the GUI works with: its packages, its worlds and the shell
commands to build it and to run the simulation.

The GUI never imports kpi_rover code: it runs the same commands a user would
type in a terminal. World descriptions come from 'world_info.py --json' of
the kpi_rover package (see kpi_rover/worlds/lib/world_info.py).
"""

import filecmp
import glob
import json
import os
import shlex
import shutil
import subprocess
import xml.etree.ElementTree as ET

PACKAGE = 'kpi_rover'

# Files of the worlds folder whose difference between the sources and the
# installed package means the installed worlds are outdated.
WORLD_FILE_PATTERNS = ('*.world.yaml', '*.sdf.xacro', '*.sdf', '*.world', 'lib/*.py', 'tools/*.py', '*/generator.py')


class WorkspaceError(Exception):
    pass


class Workspace:
    def __init__(self, path, ros_setup):
        self.path = os.path.abspath(os.path.expanduser(path))
        self.ros_setup = os.path.expanduser(ros_setup)

    @property
    def install_setup(self):
        return os.path.join(self.path, 'install', 'setup.bash')

    @property
    def src_worlds(self):
        return os.path.join(self.path, 'src', PACKAGE, 'worlds')

    @property
    def installed_worlds(self):
        return os.path.join(self.path, 'install', PACKAGE, 'share', PACKAGE, 'worlds')

    def is_built(self):
        return os.path.isfile(self.install_setup) and os.path.isdir(self.installed_worlds)

    def problems(self):
        """What prevents using the workspace at all, as a list of messages."""
        problems = []
        if not os.path.isfile(self.ros_setup):
            problems.append(f'ROS setup script not found: {self.ros_setup}')
        if not os.path.isdir(os.path.join(self.path, 'src')):
            problems.append(f'Not a ROS workspace (no src folder): {self.path}')
        elif not os.path.isdir(self.src_worlds):
            problems.append(f'Package {PACKAGE} not found in {self.path}/src')
        return problems

    # --- packages ---

    def packages(self):
        """Names of the packages in the workspace sources (like 'colcon list -n')."""
        names = []
        for root, dirs, files in os.walk(os.path.join(self.path, 'src')):
            if 'COLCON_IGNORE' in files:
                dirs[:] = []
                continue
            if 'package.xml' in files:
                try:
                    name = ET.parse(os.path.join(root, 'package.xml')).getroot().findtext('name')
                except ET.ParseError:
                    name = None
                if name:
                    names.append(name.strip())
                dirs[:] = []
            dirs[:] = [d for d in dirs if not d.startswith('.')]
        return sorted(names)

    # --- worlds ---

    def load_worlds(self):
        """
        (worlds, from_install): descriptions of the worlds (see world_info.describe)
        of the installed package, which the launch files use, or of the sources
        if the workspace is not built yet.
        """
        from_install = os.path.isfile(os.path.join(self.installed_worlds, 'lib', 'world_info.py'))
        folder = self.installed_worlds if from_install else self.src_worlds
        script = os.path.join(folder, 'lib', 'world_info.py')
        if not os.path.isfile(script):
            raise WorkspaceError(f'{script} not found')
        result = subprocess.run(['python3', script, '--json'], capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            raise WorkspaceError(f'world_info.py failed:\n{result.stderr.strip()}')
        worlds = json.loads(result.stdout)
        for world in worlds:
            # Older world_info.py versions list start points as plain names.
            world['start_points'] = [p if isinstance(p, dict) else dict(name=str(p), label=str(p))
                                     for p in world.get('start_points') or []]
        return worlds, from_install

    def tool(self, name):
        """Path of a tool script of the installed worlds folder (render_previews.py, spawn_object.py)."""
        return os.path.join(self.installed_worlds, 'tools', name)

    def map_command(self, world, sdf, out, partition):
        """The command making the map of a generated world file (render_previews.py --sdf)."""
        return shlex.join(['python3', self.tool('render_previews.py'), world, '--sdf', sdf, '--out', out,
                           '--partition', partition])

    def spawn_object_command(self, world, name, kind, x, y, z, yaw, scale=1.0):
        return shlex.join(['python3', self.tool('spawn_object.py'), '--world', world, '--name', name, '--type', kind,
                           '--x', f'{x:.3f}', '--y', f'{y:.3f}', '--z', f'{z:.3f}', '--yaw', f'{yaw:.3f}',
                           '--scale', f'{scale:g}'])

    def object_library(self):
        """[{name, kind, size}] of the object library, or [] if the tool isn't installed."""
        if not os.path.isfile(self.tool('spawn_object.py')):
            return []
        result = subprocess.run(['python3', self.tool('spawn_object.py'), '--list'], capture_output=True, text=True,
                                timeout=30)
        try:
            return json.loads(result.stdout) if result.returncode == 0 else []
        except ValueError:
            return []

    def worlds_outdated(self):
        """True if the world files in the sources differ from the installed ones (a build is needed)."""
        if not os.path.isdir(self.installed_worlds):
            return True
        for pattern in WORLD_FILE_PATTERNS:
            for src in glob.glob(os.path.join(self.src_worlds, pattern)):
                installed = os.path.join(self.installed_worlds, os.path.relpath(src, self.src_worlds))
                if not os.path.isfile(installed) or not filecmp.cmp(src, installed, shallow=False):
                    return True
        return False

    # --- commands ---

    def shell(self, command, with_install=True):
        """
        argv running a shell command in the workspace with ROS (and the workspace
        install, if built) sourced. The command runs in a new process group
        (setsid), so stopping it stops every process it started.
        """
        sources = [f'source {shlex.quote(self.ros_setup)}']
        if with_install:
            sources.append('if [ -f install/setup.bash ]; then source install/setup.bash; fi')
        script = f'cd {shlex.quote(self.path)} && ' + ' && '.join(sources) + f' && exec {command}'
        return ['setsid', 'bash', '-c', script]


def build_command(packages=None):
    """The colcon build command, for all packages or the given ones."""
    command = ['colcon', 'build']
    if packages:
        command += ['--packages-select'] + list(packages)
    return shlex.join(command)


def sim_command(world, world_args=None, start=None, pose=None, ui=True, robot=True):
    """
    The command starting the simulation (launch_sim.launch.py) with a world,
    its arguments {name: string value}, and a start point or a pose (x, y, z, yaw).
    Without 'ui' it starts no Gazebo GUI and RViz (the GUI runs them separately);
    without 'robot' only the world (the robot is added with robot_command).
    """
    command = ['ros2', 'launch', PACKAGE, 'launch_sim.launch.py', f'world:={world}']
    if not robot:
        command.append('robot:=false')
    if not ui:
        command.append('ui:=false')
    if start:
        command.append(f'start:={start}')
    elif pose and any(pose):
        command += [f'{k}:={v:g}' for k, v in zip(('x_pose', 'y_pose', 'z_pose', 'yaw_pose'), pose)]
    if world_args:
        command.append('world_args:=' + ' '.join(f'{k}:={v}' for k, v in world_args.items()))
    return shlex.join(command)


def robot_command(x, y, z, yaw):
    """The command putting the robot with its navigation into the running world (launch_sim.launch.py gazebo:=false)."""
    return shlex.join(['ros2', 'launch', PACKAGE, 'launch_sim.launch.py', 'gazebo:=false', 'ui:=false',
                       f'x_pose:={x:.3f}', f'y_pose:={y:.3f}', f'z_pose:={z:.3f}', f'yaw_pose:={yaw:.4f}'])


# Model name of the robot in Gazebo (spawn_robot.launch.py).
ROBOT_MODEL = 'my_bot'


def remove_model_command(world, name):
    """The command taking a model out of a running world."""
    return shlex.join(['gz', 'service', '-s', f'/world/{world}/remove', '--reqtype', 'gz.msgs.Entity',
                       '--reptype', 'gz.msgs.Boolean', '--timeout', '5000', '--req', f'name: "{name}" type: MODEL'])


def sim_ui_command():
    """The command starting the Gazebo GUI and RViz for a running simulation."""
    return shlex.join(['ros2', 'launch', PACKAGE, 'launch_sim_ui.launch.py'])


def joystick_command():
    """Drive the robot with a gamepad (joystick.launch.py)."""
    return shlex.join(['ros2', 'launch', PACKAGE, 'joystick.launch.py'])


# The keyboard teleop reads keys from a terminal, so it runs in a terminal window of its own.
KEYBOARD_TELEOP = ['ros2', 'run', 'teleop_twist_keyboard', 'teleop_twist_keyboard', '--ros-args',
                   '-r', '/cmd_vel:=/diff_drive_controller/cmd_vel', '-p', 'stamped:=True', '-p', 'frame_id:=base_link']


def terminal():
    """argv prefix of a terminal window that runs a command and stays until it ends, or None."""
    if shutil.which('gnome-terminal'):
        return ['gnome-terminal', '--wait', '--title=KPI Rover keyboard', '--']
    if shutil.which('x-terminal-emulator'):
        return ['x-terminal-emulator', '-e']
    return None


def keyboard_command(ws):
    """Drive the robot with the keyboard: teleop_twist_keyboard in a terminal window; None without a terminal."""
    prefix = terminal()
    if not prefix:
        return None
    inner = (f'source {shlex.quote(ws.ros_setup)} && source {shlex.quote(ws.install_setup)} && '
             f'{shlex.join(KEYBOARD_TELEOP)}')
    return shlex.join(prefix + ['bash', '-c', inner])


def running_gazebo():
    """[(pid, command line)] of the Gazebo processes running on the machine."""
    result = subprocess.run(['pgrep', '-af', r'[g]z sim'], capture_output=True, text=True)
    processes = []
    for line in result.stdout.splitlines():
        pid, _, cmd = line.partition(' ')
        # Only Gazebo itself ('gz sim ...', or 'ruby .../gz sim ...'), not shells or tools whose command lines mention it.
        program = os.path.basename(cmd.split()[0]) if cmd.split() else ''
        if pid.isdigit() and program in ('gz', 'ruby'):
            processes.append((int(pid), cmd))
    return processes

