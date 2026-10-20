"""
The map of a world seen from above (map.jpg and map.json of
render_previews.py) with the robot and the objects on it.

In 'robot' mode a press puts the robot there and dragging turns it; a press
near a start point takes that start point. In 'objects' mode a click asks to
put an object there.
"""

import math

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QPainter, QPainterPath, QPen, QPolygonF
from PyQt5.QtWidgets import QWidget

from . import theme
from .widgets import pixmap

# Robot footprint (m) drawn on the map, and the smallest size it is drawn with (px).
ROBOT_SIZE = 0.27
MARKER_MIN = 18
# A press this close to a start point (px) takes it; a drag longer than this (px) turns the robot.
PICK_RADIUS = 18
DRAG_MIN = 8
# Robot footprint checked for a place to put it (m, with some room around), and the largest
# height difference under it (m): more is a wall, an object or an edge it would be put into.
CHECK_LENGTH = 0.32
CHECK_WIDTH = 0.30
CHECK_STEP = 0.04


class MapView(QWidget):
    robot_moved = pyqtSignal(float, float, float, str)     # x, y, yaw, start point name or ''
    object_requested = pyqtSignal(float, float)            # x, y

    def __init__(self, parent=None):
        super().__init__(parent)
        self.map = None
        self.image = None
        self.mode = 'robot'
        self.robot = None           # (x, y, yaw)
        self.start = ''             # start point the robot is at, or ''
        self.robot_live = False     # the robot is in the simulation
        self.objects = []           # [(x, y, yaw, size x, size y, top z)]
        self.robot_ok = True        # the robot can be put where it is drawn
        self.placeholder = 'No map'
        self._press = None
        self.setMinimumSize(240, 240)
        self.setMouseTracking(False)

    # --- data ---

    def set_map(self, world_map, placeholder='No map'):
        self.map = world_map
        self.image = pixmap(world_map.get('image')) if world_map else None
        self.placeholder = placeholder
        self.update()

    def points(self):
        return (self.map or {}).get('start_points', {})

    def set_mode(self, mode):
        self.mode = mode
        self.setCursor(Qt.CrossCursor if self.map else Qt.ArrowCursor)
        self.update()

    def set_robot(self, x, y, yaw, start='', live=False):
        self.robot = (x, y, yaw)
        self.start = start
        self.robot_live = live
        self.update()

    def set_objects(self, objects):
        self.objects = list(objects)
        self.update()

    def _grid_value(self, grid, x, y):
        """A value of a north-to-south grid over the map at (x, y), or None outside the map."""
        n = len(grid)
        cx, cy = self.map.get('center', [0, 0])
        size = self.map['size']
        col, row = (x - cx) / size + 0.5, 0.5 - (y - cy) / size
        if not (0 <= col < 1 and 0 <= row < 1):
            return None
        return grid[int(row * n)][int(col * n)]

    def surface(self, x, y):
        """Height of the top surface at (x, y): the ground, the structures and the objects on it; None outside."""
        grid = (self.map or {}).get('surface')
        z = self._grid_value(grid, x, y) if grid else (self.ground_height(x, y) if self.map else 0.0)
        if z is None:
            return None
        for ox, oy, oyaw, sx, sy, top in self.objects:
            dx, dy = x - ox, y - oy
            u = dx * math.cos(oyaw) + dy * math.sin(oyaw)
            v = -dx * math.sin(oyaw) + dy * math.cos(oyaw)
            if abs(u) <= sx / 2 and abs(v) <= sy / 2:
                z = max(z, top)
        return z

    def footprint(self, x, y, yaw, length, width):
        """Surface heights under a length x width rectangle at (x, y) turned by yaw (None where off the map)."""
        heights = []
        cell = (self.map['size'] / len(self.map['surface'])) if (self.map or {}).get('surface') else 0.05
        nu, nv = max(2, int(length / cell) + 1), max(2, int(width / cell) + 1)
        for i in range(nu):
            for j in range(nv):
                u = (i / (nu - 1) - 0.5) * length
                v = (j / (nv - 1) - 0.5) * width
                heights.append(self.surface(x + u * math.cos(yaw) - v * math.sin(yaw),
                                            y + u * math.sin(yaw) + v * math.cos(yaw)))
        return heights

    def place_check(self, x, y, yaw):
        """(the robot can be put at (x, y, yaw), the height to put it at, why not) from the surface under it."""
        if not self.map:
            return True, 0.0, ''
        heights = self.footprint(x, y, yaw, CHECK_LENGTH, CHECK_WIDTH)
        if any(h is None for h in heights):
            return False, 0.0, 'This place is outside the map.'
        if max(heights) - min(heights) > CHECK_STEP:
            return False, max(heights), 'There is a wall, an object or an edge here: the robot would be put into it.'
        return True, max(heights), ''

    def ground_height(self, x, y):
        """The ground height at (x, y) from the map heights, or 0."""
        heights = (self.map or {}).get('heights')
        if not heights:
            return 0.0
        n = len(heights) - 1
        cx, cy = self.map.get('center', [0, 0])
        size = self.map['size']
        col = min(max((x - cx) / size + 0.5, 0), 1) * n
        row = min(max(0.5 - (y - cy) / size, 0), 1) * n
        c0, r0 = min(int(col), n - 1), min(int(row), n - 1)
        fc, fr = col - c0, row - r0
        top = heights[r0][c0] * (1 - fc) + heights[r0][c0 + 1] * fc
        bottom = heights[r0 + 1][c0] * (1 - fc) + heights[r0 + 1][c0 + 1] * fc
        return top * (1 - fr) + bottom * fr

    # --- geometry ---

    def _area(self):
        side = min(self.width(), self.height())
        return QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

    def _to_screen(self, x, y):
        area, m = self._area(), self.map
        cx, cy = m.get('center', [0, 0])
        return QPointF(area.left() + (x - cx + m['size'] / 2) / m['size'] * area.width(),
                       area.top() + (cy + m['size'] / 2 - y) / m['size'] * area.height())

    def _to_world(self, point):
        area, m = self._area(), self.map
        cx, cy = m.get('center', [0, 0])
        return (cx - m['size'] / 2 + (point.x() - area.left()) / area.width() * m['size'],
                cy + m['size'] / 2 - (point.y() - area.top()) / area.height() * m['size'])

    def _nearest_start(self, pos):
        best, distance = '', PICK_RADIUS
        for name, (x, y, _) in self.points().items():
            p = self._to_screen(x, y)
            d = math.hypot(p.x() - pos.x(), p.y() - pos.y())
            if d < distance:
                best, distance = name, d
        return best

    # --- mouse ---

    def mousePressEvent(self, event):
        if not self.map or event.button() != Qt.LeftButton or not self._area().contains(event.pos()):
            return
        if self.mode == 'objects':
            self.object_requested.emit(*self._to_world(event.pos()))
            return
        if self.robot_live:
            return
        start = self._nearest_start(event.pos())
        if start:
            x, y, yaw = self.points()[start]
            self._press = None
        else:
            x, y = self._to_world(event.pos())
            yaw = self.robot[2] if self.robot else 0.0
            self._press = event.pos()
        self.robot_moved.emit(x, y, yaw, start)

    def mouseMoveEvent(self, event):
        if self._press is None or not self.robot:
            return
        dx, dy = event.pos().x() - self._press.x(), event.pos().y() - self._press.y()
        if math.hypot(dx, dy) >= DRAG_MIN:
            x, y, _ = self.robot
            self.robot_moved.emit(x, y, math.atan2(-dy, dx), '')

    def mouseReleaseEvent(self, event):
        self._press = None

    # --- painting ---

    def paintEvent(self, event):
        t = theme.current()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        area = self._area()
        clip = QPainterPath()
        clip.addRoundedRect(area, 10, 10)
        p.setClipPath(clip)
        p.fillRect(area, QColor(t['image_bg']))
        if not self.image:
            p.setPen(QColor(t['muted']))
            p.drawText(area.adjusted(20, 20, -20, -20), Qt.AlignCenter | Qt.TextWordWrap, self.placeholder)
            return
        p.drawPixmap(area.toRect(), self.image)
        scale = area.width() / self.map['size']
        for x, y, yaw, sx, sy, _ in self.objects:
            p.save()
            p.translate(self._to_screen(x, y))
            p.rotate(-math.degrees(yaw))
            w, h = max(6, sx * scale), max(6, sy * scale)
            p.setPen(QPen(QColor(0, 0, 0, 170), 3))
            p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(-w / 2, -h / 2, w, h))
            p.setPen(QPen(QColor(t['warning']), 2))
            p.drawRect(QRectF(-w / 2, -h / 2, w, h))
            p.restore()
        side = max(MARKER_MIN, ROBOT_SIZE * scale)
        for name, (x, y, yaw) in self.points().items():
            if name != self.start:
                self._marker(p, self._to_screen(x, y), yaw, side * 0.8, QColor(255, 255, 255, 170), False)
        if self.robot:
            x, y, yaw = self.robot
            color = QColor(t['success'] if self.robot_live else t['accent'] if self.robot_ok else t['danger'])
            self._marker(p, self._to_screen(x, y), yaw, side, color, True)

    @staticmethod
    def _marker(p, center, yaw, side, color, arrow):
        """The robot: a square turned by yaw, with an arrow pointing where it heads."""
        p.save()
        p.translate(center)
        p.rotate(-math.degrees(yaw))       # screen y points down: counterclockwise yaw turns left on screen
        outline = QPen(QColor(0, 0, 0, 160), 4)
        body = QRectF(-side / 2, -side / 2, side, side)
        for pen in (outline, QPen(color, 2.5)):
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawRect(body)
        if arrow:
            length = side * 1.6
            head = QPolygonF([QPointF(length, 0), QPointF(length - side * 0.5, -side * 0.35),
                              QPointF(length - side * 0.5, side * 0.35)])
            for pen, brush in ((outline, QColor(0, 0, 0, 160)), (QPen(color, 2.5), color)):
                p.setPen(pen)
                p.drawLine(QPointF(side / 2, 0), QPointF(length - side * 0.4, 0))
                p.setBrush(brush)
                p.drawPolygon(head)
        p.restore()
