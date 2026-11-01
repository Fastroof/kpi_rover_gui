# KPI Rover GUI

A desktop application for everyday work with the kpi_rover simulation: pick a
world, set it up while looking at pictures of what each option does, and start
or stop the simulation.

It is an optional add-on. kpi_rover works fully without it, and the GUI runs
the same commands you would type in a terminal. You can copy that command
from the log panel.

## Requirements

- ROS 2 Jazzy and the [kpi_rover](https://github.com/KPI-Rover/ros_sw) workspace
  on this machine (not in Docker), in a version that has the world manifests
  (`worlds/<world>.world.yaml`) and their tools (`world_info.py`,
  `render_previews.py`, `spawn_object.py`, the `gazebo` argument of `launch_sim.launch.py`).
- Python 3 with PyQt5 and PyYAML. Both come with ROS (`python3-pyqt5`,
  `python3-yaml`).

## Run

```bash
git clone <this repository> kpi_rover_gui
cd kpi_rover_gui
./kpi-rover-gui            # or: python3 -m kpi_rover_gui
```

The defaults are the workspace `~/ros_ws` and the ROS setup script
`/opt/ros/jazzy/setup.bash`. To change them, open **Preferences**. Light or dark
follows the system setting, and the GUI follows it live when you switch it.

## How it works

1. **Choose a world.** All worlds are shown as cards with their pictures
   (on the hub the shared arena first, see below).
2. **Set it up.**
   - **Presets** (chips) come with the world, and choosing one shows a picture
     of the world with it. You can also save your own; to delete one, right
     click it. The chip of the current settings is lit.
   - **Settings**: the main ones are shown first, the rest are under
     *More settings*. Settings that only matter for some choice (e.g. the
     random maze variant) are shown only then. A changed setting gets a mark
     and a ↺ button that resets it.
   - **The big picture on the left** shows the setting you click, or the one
     you keep the mouse on for 3 seconds. Its example pictures are listed
     below it, and clicking one sets that value. Where a world has picture
     layers (the test square: floors and markings), the pictures show your
     floor with your marking.
3. **Next** (F5) opens the run page with these settings. Nothing starts by
   itself; each card has its state, a button and its log:
   - **Build**: colcon build of kpi_rover, of one package or of all. It says
     when a build is needed because the worlds changed.
   - **Simulation**: Gazebo with the world, without the robot. While it starts,
     the GUI makes the map of exactly this generated world (in a hidden Gazebo
     of its own; the maps are cached).
   - **Robot**: on the map, press where the robot should stand and drag to
     turn it, or take a start point. The place is checked against the
     surface heights of the generated world (walls, objects, decks): where the
     robot would be put into something, its square turns red and it can't be
     put in. Otherwise it is put on the surface there. Then *Put the robot here* starts the
     robot with its controllers, localization, mapping and navigation
     (`launch_sim.launch.py gazebo:=false`). *Take out* removes it, so you can put it
     somewhere else.
   - **Objects**: choose a box, a crate, a cone, a low object or the flat
     board and click the map to put it into the running world (in the garden
     they are scaled down with the world). You can remove the last one or all of them.
     Objects can also be scattered at random by the world settings
     (garden, maze, overpass).
   - **RViz** and **Gazebo window**: opened by hand, or with the simulation if
     you tick its *Open with the simulation* box (off by default). You can close
     them while the simulation keeps running. The Gazebo window costs much CPU;
     on a shared server keep it closed unless you need it.
   - **Keyboard control** opens teleop_twist_keyboard in a terminal window.
     **Gamepad control** runs joystick.launch.py.

   **Stop** sends Ctrl+C to everything the card started; anything still
   running after that gets SIGTERM and then SIGKILL, so no Gazebo is left
   behind. *Copy command* gives the command of the selected card, to run it
   in a terminal. **← World settings** goes back while everything keeps
   running, and a pill in the header leads back to the run page.

Settings and your presets are stored in `~/.config/kpi_rover_gui/`.

## Shared arena (KPI Rover hub)

On the [KPI Rover hub](https://github.com/Fastroof/kpi-rover-hub) the first
card among the worlds is **Shared arena**: one Gazebo world on the server that
robots from all sessions join. The card shows the world the arena runs and a
ribbon: *JOIN*, or *OFFLINE* when the arena is not running (click to look again). It is
there only when the hub's `kpi-arena` command is (the admin starts the arena
with `./run.sh arena start <world>`).

Clicking the card opens the run page of the arena. There **Join** takes the
place of starting the simulation: the GUI downloads the map the arena made of
its world when it started (nothing is built in your session). Then you put
the robot in anywhere on the map as usual. Its navigation runs in your
session. RViz, the Gazebo window and robot control talk to the arena.
**Leave** takes your robot out of the arena.

For now there is one robot at a time in the arena; if another one is there,
the Robot card says so. Objects can't be put into the arena.

## Where the world information comes from

Everything about the worlds comes from the kpi_rover world manifests
(`worlds/<world>.world.yaml`, read with `world_info.py --json`):

- the options and their types, ranges, groups and descriptions;
- the *More settings* (`advanced: true`);
- the world presets;
- the start points;
- the pictures in `worlds/<world>/previews/`, rendered with
  `worlds/tools/render_previews.py <world>`. With `--sdf` the same tool makes the
  map of a generated world, and `worlds/tools/spawn_object.py` puts objects into
  the running world.

A new world or option shows up in the GUI without changing the GUI.

## Code

| File | What |
|---|---|
| `kpi_rover_gui/main_window.py` | the window and the flow: worlds → settings → run; starting the simulation |
| `kpi_rover_gui/home_page.py` | the world cards and the shared arena |
| `kpi_rover_gui/world_page.py` | the settings page: picture, presets, settings |
| `kpi_rover_gui/run_page.py` | the run page: process cards, their logs, the robot and objects panels |
| `kpi_rover_gui/map_view.py` | the world map with the robot and the objects on it |
| `kpi_rover_gui/controls.py` | option editors (switch, segments, slider, variant number), no-wheel filter |
| `kpi_rover_gui/theme.py` | light/dark colors and the style sheet |
| `kpi_rover_gui/widgets.py` | images, flow layout, log view |
| `kpi_rover_gui/workspace.py` | workspace paths, packages, worlds, the shell commands (also of the arena) |
| `kpi_rover_gui/runner.py` | a command in its own process group: output lines, graceful stop |
| `kpi_rover_gui/storage.py` | your presets and the last used options (JSON) |
