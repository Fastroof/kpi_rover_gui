"""
Saved world settings: named presets per world and the last used settings of
each world, in ~/.config/kpi_rover_gui (or $XDG_CONFIG_HOME/kpi_rover_gui).

A settings entry is {"args": {name: string value}, "start": start point name
or null, "pose": [x, y, z, yaw] or null}.
"""

import json
import os

CONFIG_DIR = os.path.join(os.environ.get('XDG_CONFIG_HOME') or os.path.expanduser('~/.config'), 'kpi_rover_gui')


class JsonStore:
    def __init__(self, filename):
        self.path = os.path.join(CONFIG_DIR, filename)
        try:
            with open(self.path) as f:
                self.data = json.load(f)
        except (OSError, ValueError):
            self.data = {}

    def save(self):
        os.makedirs(CONFIG_DIR, exist_ok=True)
        tmp = self.path + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(self.data, f, ensure_ascii=False, indent=1, sort_keys=True)
        os.replace(tmp, self.path)


class Presets(JsonStore):
    """{world: {preset name: settings}}."""

    def __init__(self):
        super().__init__('presets.json')

    def names(self, world):
        return sorted(self.data.get(world, {}), key=str.lower)

    def get(self, world, name):
        return self.data.get(world, {}).get(name)

    def put(self, world, name, settings):
        self.data.setdefault(world, {})[name] = settings
        self.save()

    def delete(self, world, name):
        self.data.get(world, {}).pop(name, None)
        if not self.data.get(world):
            self.data.pop(world, None)
        self.save()


class LastUsed(JsonStore):
    """{world: settings} last used for each world, and the last world."""

    def __init__(self):
        super().__init__('last_used.json')

    def get(self, world):
        return self.data.get('worlds', {}).get(world)

    def put(self, world, settings):
        self.data.setdefault('worlds', {})[world] = settings
        self.data['world'] = world
        self.save()

    def world(self):
        return self.data.get('world')
