"""
The ROS workspace the GUI works with: its packages, its worlds and the shell
commands to build it and to run the simulation.

The GUI never imports kpi_rover code: it runs the same commands a user would
type in a terminal. World descriptions come from
'python3 -m kpi_rover_worlds.world_info --json'.
"""

import filecmp
import glob
import json
import os
import shlex
import shutil
import subprocess
import xml.etree.ElementTree as ET

WORLDS = 'kpi_rover_worlds'
BRINGUP = 'kpi_rover_bringup'

# Files of kpi_rover_worlds whose difference between the sources and the install means a build is needed:
# (source folder, files in it, installed folder relative to the install prefix).
WORLD_FILES = (('worlds', '*/*.*', f'share/{WORLDS}/worlds'),
               ('common/config', '*.yaml', f'share/{WORLDS}/common/config'),
               ('common/python', '*.py', f'lib/python3*/site-packages/{WORLDS}'),
               ('tools', '*.py', f'lib/{WORLDS}'))


class WorkspaceError(Exception):
    pass


class Workspace:
    def __init__(self, path, ros_setup):
        self.path = os.path.abspath(os.path.expanduser(path))
        self.ros_setup = os.path.expanduser(ros_setup)

    @property
    def install_setup(self):
        return os.path.join(self.path, 'install', 'setup.bash')

    def package_dirs(self):
        """{name: source folder} of the packages in the workspace sources (like 'colcon list')."""
        found = {}
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
                    found[name.strip()] = root
                dirs[:] = []
            dirs[:] = [d for d in dirs if not d.startswith('.')]
        return found

    def packages(self):
        return sorted(self.package_dirs())

    def install_prefix(self, package):
        """Install prefix of a package: install/<package> (colcon default) or install (--merge-install)."""
        isolated = os.path.join(self.path, 'install', package)
        return isolated if os.path.isdir(isolated) else os.path.join(self.path, 'install')

    def is_built(self):
        return (os.path.isfile(self.install_setup)
                and os.path.isdir(os.path.join(self.install_prefix(WORLDS), 'share', WORLDS, 'worlds')))

    def problems(self):
        """What prevents using the workspace at all, as a list of messages."""
        problems = []
        if not os.path.isfile(self.ros_setup):
            problems.append(f'ROS setup script not found: {self.ros_setup}')
        if not os.path.isdir(os.path.join(self.path, 'src')):
            problems.append(f'Not a ROS workspace (no src folder): {self.path}')
        elif WORLDS not in self.package_dirs():
            problems.append(f'Package {WORLDS} not found in {self.path}/src')
        return problems

    # --- worlds ---

    def _run(self, command, timeout):
        return subprocess.run(self.shell(command), capture_output=True, text=True, timeout=timeout)

    def load_worlds(self):
        """Descriptions of the installed worlds, which the launch files use (see world_info.describe)."""
        if not self.is_built():
            raise WorkspaceError('The workspace is not built yet: run colcon build in it.')
        result = self._run(f'python3 -m {WORLDS}.world_info --json', 60)
        if result.returncode != 0:
            raise WorkspaceError(f'world_info failed:\n{result.stderr.strip()}')
        return json.loads(result.stdout)

    def map_command(self, world, sdf, out, partition):
        """The command making the map of a generated world file (render_previews.py --sdf)."""
        return shlex.join(['ros2', 'run', WORLDS, 'render_previews.py', world, '--sdf', sdf, '--out', out,
                           '--partition', partition])

    def spawn_object_command(self, world, name, kind, x, y, z, yaw, scale=1.0):
        return shlex.join(['ros2', 'run', WORLDS, 'spawn_object.py', '--world', world, '--name', name, '--type', kind,
                           '--x', f'{x:.3f}', '--y', f'{y:.3f}', '--z', f'{z:.3f}', '--yaw', f'{yaw:.3f}',
                           '--scale', f'{scale:g}'])

    def object_library(self):
        """[{name, kind, size}] of the object library, or [] if it can't be read."""
        if not self.is_built():
            return []
        result = self._run(f'ros2 run {WORLDS} spawn_object.py --list', 30)
        try:
            return json.loads(result.stdout) if result.returncode == 0 else []
        except ValueError:
            return []

    def worlds_outdated(self):
        """True if the world files in the sources differ from the installed ones (a build is needed)."""
        src = self.package_dirs().get(WORLDS)
        if not src or not self.is_built():
            return True
        prefix = self.install_prefix(WORLDS)
        for folder, files, installed in WORLD_FILES:
            targets = glob.glob(os.path.join(prefix, installed))
            if not targets:
                return True
            for path in glob.glob(os.path.join(src, folder, files)):
                target = os.path.join(targets[0], os.path.relpath(path, os.path.join(src, folder)))
                if not os.path.isfile(target) or not filecmp.cmp(path, target, shallow=False):
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


def sim_command(world, world_args=None):
    """
    The command starting the world (world.launch.py, without its Gazebo window) built with
    its arguments {name: string value}; it prints the generated world file first.
    """
    build = shlex.join(['python3', '-m', f'{WORLDS}.world_info', '--build', world]
                       + [f'{k}:={v}' for k, v in (world_args or {}).items()])
    script = (f'world=$({build}) && echo "World file: $world" && '
              f'exec ros2 launch {BRINGUP} world.launch.py gui:=false "world:=$world"')
    return shlex.join(['bash', '-c', script])


def robot_command(x, y, z, yaw):
    """The command putting the robot with its navigation into the running world (sim_robot.launch.py)."""
    return shlex.join(['ros2', 'launch', BRINGUP, 'sim_robot.launch.py',
                       f'x_pose:={x:.3f}', f'y_pose:={y:.3f}', f'z_pose:={z:.3f}', f'yaw_pose:={yaw:.4f}'])


# Model name of the robot in Gazebo (sim_robot.launch.py).
ROBOT_MODEL = 'kpi_rover'


def remove_model_command(world, name):
    """The command taking a model out of a running world."""
    return shlex.join(['gz', 'service', '-s', f'/world/{world}/remove', '--reqtype', 'gz.msgs.Entity',
                       '--reptype', 'gz.msgs.Boolean', '--timeout', '5000', '--req', f'name: "{name}" type: MODEL'])


def gazebo_window_command():
    """The command starting the Gazebo GUI for a running simulation."""
    return shlex.join(['ros2', 'launch', 'ros_gz_sim', 'gz_sim.launch.py', 'gz_args:=-g -v4'])


def rviz_command():
    return shlex.join(['ros2', 'launch', BRINGUP, 'rviz.launch.py', 'use_sim_time:=true'])


def joystick_command():
    """Drive the robot with a gamepad (joystick.launch.py)."""
    return shlex.join(['ros2', 'launch', BRINGUP, 'joystick.launch.py', 'use_sim_time:=true'])


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


def keyboard_command(ws, arena=False):
    """Drive the robot with the keyboard: teleop_twist_keyboard in a terminal window; None without a terminal."""
    prefix = terminal()
    if not prefix:
        return None
    teleop = shlex.join(KEYBOARD_TELEOP)
    inner = (f'source {shlex.quote(ws.ros_setup)} && source {shlex.quote(ws.install_setup)} && '
             f'{in_arena(teleop) if arena else teleop}')
    return shlex.join(prefix + ['bash', '-c', inner])


# --- the shared arena of the KPI Rover hub: a Gazebo server that robots from the sessions join (kpi-arena) ---

ARENA = 'kpi-arena'
# Line of 'kpi-arena watch' with the folder of the downloaded map (map.json, map.jpg)
ARENA_MAP = 'Arena map: '


def arena_available():
    """True on the hub (the kpi-arena command is there)."""
    return shutil.which(ARENA) is not None


def in_arena(command):
    """The command run on the arena network instead of this machine's own."""
    return f'{ARENA} exec {command}'


def arena_watch_command():
    return shlex.join([ARENA, 'watch'])


def arena_gazebo_command():
    """The Gazebo window of the arena (kpi-arena downloads the meshes of its world first)."""
    return shlex.join([ARENA, 'gazebo'])


def arena_robot_command(x, y, z, yaw):
    """The robot with its navigation put into the arena world (kpi-arena takes it out when stopped)."""
    return shlex.join([ARENA, f'x_pose:={x:.3f}', f'y_pose:={y:.3f}', f'z_pose:={z:.3f}', f'yaw_pose:={yaw:.4f}'])


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
