"""
The settings of one world: on the left a big picture of what is being set
(example pictures of an option), on the right presets and the world options
(main ones first, the rest under 'More settings'). Where the robot starts is
chosen after the start, on the map of the generated world (run page).

The picture follows the setting you click, or the one you keep the mouse on
for HOVER_DELAY ms.
"""

from PyQt5.QtCore import QEvent, QObject, Qt, QTimer, pyqtSignal
from PyQt5.QtWidgets import (QFrame, QHBoxLayout, QLabel, QMenu, QPushButton, QScrollArea, QSizePolicy, QToolButton,
                             QVBoxLayout, QWidget)

from . import controls
from .widgets import Clickable, FlowLayout, ImageView, clear_layout, set_flag

HOVER_DELAY = 3000


def label(text, name=None, wrap=False):
    widget = QLabel(text)
    if name:
        widget.setObjectName(name)
    widget.setWordWrap(wrap)
    return widget


def section(text):
    return label(text.upper(), 'Section')


def example_index(spec, images, value):
    """Index of the example picture of a value: the same value, or the closest one of a bounded number; or None."""
    texts = [controls.format_value(spec, i['value']) for i in images]
    if value in texts:
        return texts.index(value)
    if spec.get('type') in ('int', 'float') and 'min' in spec and 'max' in spec:
        try:
            number = float(value)
        except ValueError:
            return None
        return min(range(len(images)), key=lambda i: abs(float(images[i]['value']) - number))
    return None


class Activation(QObject):
    """
    Calls 'activate' when a widget (or anything in it) is clicked, or when the
    mouse stays on it for HOVER_DELAY ms.
    """

    def __init__(self, widget, activate):
        super().__init__(widget)
        self.widget = widget
        self.activate = activate
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(HOVER_DELAY)
        self.timer.timeout.connect(activate)
        widget.installEventFilter(self)
        for child in widget.findChildren(QWidget):
            child.installEventFilter(self)

    def eventFilter(self, obj, event):
        kind = event.type()
        if kind == QEvent.MouseButtonPress:
            self.timer.stop()
            self.activate()
        elif obj is self.widget and kind == QEvent.Enter:
            self.timer.start()
        elif obj is self.widget and kind == QEvent.Leave:
            self.timer.stop()
        return False


class Thumb(Clickable):
    def __init__(self, image, text, parent=None):
        super().__init__(parent)
        self.setObjectName('Thumb')
        layout = QVBoxLayout(self)
        layout.setContentsMargins(3, 3, 3, 3)
        layout.setSpacing(3)
        view = ImageView(cover=True, radius=6)
        view.set_image(image)
        view.setFixedSize(128, 80)
        layout.addWidget(view)
        caption = label(text, 'Caption')
        caption.setAlignment(Qt.AlignCenter)
        layout.addWidget(caption)


class PicturePanel(QFrame):
    """The big picture: the world, or example pictures of the option being set."""
    example_chosen = pyqtSignal(str, str)       # argument, value

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('Panel')
        self.world_image = None
        self.view = ImageView(radius=10)
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view.setMinimumHeight(260)

        self.title = label('', wrap=True)
        font = self.title.font()
        font.setBold(True)
        font.setPointSizeF(font.pointSizeF() * 1.1)
        self.title.setFont(font)
        self.caption = label('', 'Muted', wrap=True)
        # The example pictures scroll sideways, so however many there are, the columns keep their widths.
        strip_widget = QWidget()
        self.strip = QHBoxLayout(strip_widget)
        self.strip.setContentsMargins(0, 0, 0, 0)
        self.strip.setSpacing(6)
        self.strip_area = QScrollArea()
        self.strip_area.setWidget(strip_widget)
        self.strip_area.setWidgetResizable(True)
        self.strip_area.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.strip_area.setFixedHeight(124)
        self.strip_area.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        self.strip_area.hide()
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Expanding)
        self.setMinimumWidth(320)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        layout.addWidget(self.view, 1)
        layout.addWidget(self.title)
        layout.addWidget(self.caption)
        layout.addWidget(self.strip_area)

    def _set(self, image, title, caption, placeholder='No picture'):
        self.view.set_image(image, placeholder)
        self.title.setText(title)
        self.caption.setText(caption)
        self.caption.setVisible(bool(caption))

    def show_world(self, info, image=None):
        """The world; 'image' replaces its picture (e.g. made of layers for the current settings)."""
        self.world_image = image or info.get('image')
        self._clear_strip()
        self._set(self.world_image, info['title'],
                  'Click a setting, or keep the mouse on it for a few seconds, to see what it changes.',
                  'No picture of this world yet')

    def show_preset(self, title, description, image):
        self._clear_strip()
        self._set(image or self.world_image, title, description or '', 'No picture of this preset')

    def _clear_strip(self):
        clear_layout(self.strip)
        self.strip_area.hide()

    def show_option(self, name, spec, value):
        self._clear_strip()
        images = spec.get('images') or []
        title = spec.get('label', name)
        if not images:
            self._set(self.world_image, title, ' '.join(filter(None, (
                spec.get('description'), 'There is no example picture of this setting.'))))
            return
        index = example_index(spec, images, value)
        shown = images[index if index is not None else 0]
        shown_text = controls.format_value(spec, shown['value'])
        shown_display, yours = controls.display_value(spec, shown_text), controls.display_value(spec, value)
        if index is None:
            note = f'Example of another value: {shown_display}. Yours: {yours}.'
        elif shown_text == value:
            note = f'Your value: {yours}.'
        else:
            note = f'Closest example: {shown_display}. Yours: {yours}.'
        self._set(shown['image'], title, ' '.join(filter(None, (spec.get('description'), note))))
        if len(images) > 1:
            for i, item in enumerate(images):
                text = controls.format_value(spec, item['value'])
                thumb = Thumb(item['image'], controls.display_value(spec, text))
                set_flag(thumb, 'selected', i == index)
                thumb.setToolTip(f'Set {title} to {controls.display_value(spec, text)}')
                thumb.clicked.connect(lambda t=text: self.example_chosen.emit(name, t))
                self.strip.addWidget(thumb)
            self.strip.addStretch(1)
            self.strip_area.show()


class OptionRow(QFrame):
    """One option: its name, its editor, a hint, and a reset button when changed."""
    activated = pyqtSignal(str)
    edited = pyqtSignal(str)

    def __init__(self, name, spec, parent=None):
        super().__init__(parent)
        self.setObjectName('Option')
        self.name = name
        self.spec = spec
        self.editor = controls.editor(spec)
        title = label(spec.get('label', name))
        font = title.font()
        font.setWeight(600)
        title.setFont(font)
        self.reset_button = QToolButton()
        self.reset_button.setObjectName('Reset')
        self.reset_button.setText('↺')
        self.reset_button.setToolTip(f'Back to the default: '
                                     f'{controls.display_value(spec, self.editor.default())}')
        self.reset_button.setCursor(Qt.PointingHandCursor)
        self.reset_button.clicked.connect(self.editor.reset)
        head = QHBoxLayout()
        head.addWidget(title)
        head.addStretch(1)
        head.addWidget(self.reset_button)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 6, 8, 8)
        layout.setSpacing(4)
        layout.addLayout(head)
        layout.addWidget(self.editor)
        if spec.get('description'):
            layout.addWidget(label(spec['description'], 'Hint', wrap=True))
        self.editor.changed.connect(self._edited)
        self.update_mark()
        Activation(self, lambda: self.activated.emit(self.name))

    def _edited(self):
        self.update_mark()
        self.edited.emit(self.name)

    def update_mark(self):
        changed = self.editor.value() != self.editor.default()
        self.reset_button.setVisible(changed)
        set_flag(self, 'changed', changed)


class OptionsPanel(QWidget):
    """The options of a world: the main ones by group, the advanced ones under 'More settings'."""
    changed = pyqtSignal()
    focused = pyqtSignal(str)       # an option clicked, pointed at or edited

    def __init__(self, info, parent=None):
        super().__init__(parent)
        self.rows = {}
        self.more = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)
        args = info.get('args', {})
        if not args:
            layout.addSpacing(10)
            layout.addWidget(section('World'))
            layout.addWidget(label('This world has no settings.', 'Muted'))
            return
        basic = {n: s for n, s in args.items() if not s.get('advanced')}
        advanced = {n: s for n, s in args.items() if s.get('advanced')}
        self._add_groups(layout, info, basic)
        if advanced:
            self.more = QWidget()
            more_layout = QVBoxLayout(self.more)
            more_layout.setContentsMargins(0, 0, 0, 0)
            more_layout.setSpacing(2)
            self._add_groups(more_layout, info, advanced)
            self.more_button = QToolButton()
            self.more_button.setObjectName('Disclosure')
            self.more_button.setCursor(Qt.PointingHandCursor)
            self.more_button.clicked.connect(lambda: self.show_more(not self.more.isVisible()))
            layout.addSpacing(8)
            layout.addWidget(self.more_button)
            layout.addWidget(self.more)
            self.advanced_count = len(advanced)
            self.show_more(False)

    def show_more(self, visible):
        if self.more is None:
            return
        self.more.setVisible(visible)
        self.more_button.setText(f"{'▾' if visible else '▸'}  More settings ({self.advanced_count})")

    def _add_groups(self, layout, info, args):
        groups = dict(info.get('groups') or {})
        order = [None] + list(groups) + sorted({s.get('group') for s in args.values()} - set(groups) - {None})
        for group in order:
            names = [n for n, s in args.items() if s.get('group') == group]
            if not names:
                continue
            layout.addSpacing(10)
            layout.addWidget(section(groups.get(group, group) if group else 'World'))
            for name in names:
                row = OptionRow(name, args[name])
                row.activated.connect(self.focused)
                row.edited.connect(self._edited)
                self.rows[name] = row
                layout.addWidget(row)

    def _edited(self, name):
        self.update_shown()
        self.focused.emit(name)
        self.changed.emit()

    def value(self, name):
        return self.rows[name].editor.value()

    def changed_values(self):
        return {n: r.editor.value() for n, r in self.rows.items()
                if r.editor.value() != r.editor.default() and self.shown(n)}

    def shown(self, name):
        """Whether an option applies now: its 'show_if' other options have those values."""
        for other, value in (self.rows[name].spec.get('show_if') or {}).items():
            row = self.rows.get(other)
            if row and row.editor.value() != controls.format_value(row.spec, value):
                return False
        return True

    def update_shown(self):
        for name, row in self.rows.items():
            row.setVisible(self.shown(name))

    def normalize(self, args):
        """{name: value} as the editors would give them, without the default values; None if not valid."""
        result = {}
        for name, value in args.items():
            row = self.rows.get(name)
            if row is None:
                return None
            text = controls.format_value(row.spec, value) if row.spec.get('type') in ('int', 'float', 'bool') \
                else str(value)
            if text != row.editor.default():
                result[name] = text
        return result

    def set_values(self, values, reveal=True):
        """Set {name: value}, others to the defaults; return the names not applied."""
        rejected = [name for name in values if name not in self.rows]
        for name, row in self.rows.items():
            row.editor.blockSignals(True)
            row.editor.reset()
            if name in values and not row.editor.set_value(values[name]):
                rejected.append(name)
            row.editor.blockSignals(False)
            row.update_mark()
        if reveal and any(self.rows[n].spec.get('advanced') for n in self.changed_values()):
            self.show_more(True)
        self.update_shown()
        self.changed.emit()
        return rejected

    def set_value(self, name, value):
        self.rows[name].editor.set_value(value)


class PresetBar(QWidget):
    """Presets as chips: Default, the world's presets and your own; the chip of the current options is lit."""
    chosen = pyqtSignal(dict)       # the preset: {label, description, args, image}
    save_requested = pyqtSignal()
    delete_requested = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.flow = FlowLayout(self)
        self.chips = []

    def set_presets(self, world_presets, own_presets):
        """world_presets: [{name, label, description, args}]; own_presets: {name: args}."""
        clear_layout(self.flow)
        self.chips = []
        self._chip(dict(label='Default', description='The world as it is by default.', args={}), None)
        for preset in world_presets:
            self._chip(preset, None)
        for name, args in own_presets.items():
            self._chip(dict(label=f'★ {name}', description='Your preset. Right click to delete it.', args=args), name)
        self.save = QPushButton('+  Save as preset')
        self.save.setObjectName('AddChip')
        self.save.setCursor(Qt.PointingHandCursor)
        self.save.setToolTip('Save the current settings as your preset')
        self.save.clicked.connect(self.save_requested)
        self.flow.addWidget(self.save)

    def _chip(self, preset, own):
        chip = QPushButton(preset['label'])
        chip.setObjectName('Chip')
        chip.setCheckable(True)
        chip.setCursor(Qt.PointingHandCursor)
        chip.setToolTip(preset.get('description', ''))
        chip.args = preset['args']
        chip.own = own
        chip.clicked.connect(lambda: self.chosen.emit(dict(preset)))
        if own:
            chip.setContextMenuPolicy(Qt.CustomContextMenu)
            chip.customContextMenuRequested.connect(lambda pos: self._menu(chip, pos))
        self.flow.addWidget(chip)
        self.chips.append(chip)

    def _menu(self, chip, pos):
        menu = QMenu(self)
        menu.addAction(f'Delete «{chip.own}»', lambda: self.delete_requested.emit(chip.own))
        menu.exec_(chip.mapToGlobal(pos))

    def select(self, current, normalize):
        """Light the chip whose options are the current ones (normalized by 'normalize')."""
        matched = False
        for chip in self.chips:
            match = not matched and normalize(chip.args) == current
            chip.setChecked(match)
            matched = matched or match
        self.save.setVisible(not matched)


class WorldPage(QWidget):
    """Everything about the selected world before starting it."""
    changed = pyqtSignal()
    save_preset = pyqtSignal()
    delete_preset = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName('Page')
        self.info = None
        self.options = None

        self.picture = PicturePanel()
        self.picture.example_chosen.connect(self._example_chosen)

        self.title = label('', 'PageTitle')
        self.description = label('', 'Muted', wrap=True)
        self.presets = PresetBar()
        self.presets.chosen.connect(self._preset_chosen)
        self.presets.save_requested.connect(self.save_preset)
        self.presets.delete_requested.connect(self.delete_preset)
        self.options_holder = QVBoxLayout()
        right_widget = QWidget()
        right = QVBoxLayout(right_widget)
        right.setContentsMargins(4, 0, 12, 12)
        right.setSpacing(8)
        right.addWidget(self.title)
        right.addWidget(self.description)
        right.addSpacing(6)
        right.addWidget(section('Presets'))
        right.addWidget(self.presets)
        right.addLayout(self.options_holder)
        right.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(right_widget)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(420)
        scroll.setMaximumWidth(560)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 16, 8, 12)
        layout.setSpacing(16)
        layout.addWidget(self.picture, 3)
        layout.addWidget(scroll, 2)

    def set_world(self, info, settings, own_presets):
        self.info = info
        self.title.setText(info['title'])
        self.description.setText(info.get('description', ''))
        clear_layout(self.options_holder)
        self.options = OptionsPanel(info)
        self.options.changed.connect(self._options_changed)
        self.options.focused.connect(self._show_option)
        self.options_holder.addWidget(self.options)
        self.presets.set_presets(info.get('presets', []), own_presets)
        rejected = self.apply(settings or {})
        self.picture.show_world(info, self._world_image())
        return rejected

    def set_own_presets(self, own_presets):
        self.presets.set_presets(self.info.get('presets', []), own_presets)
        self._options_changed()

    def apply(self, settings):
        """Apply saved settings {args}; return what could not be applied."""
        return self.options.set_values(settings.get('args') or {})

    def settings(self):
        return dict(args=self.options.changed_values() if self.options else {})

    def summary(self):
        """A short text of the current settings, for the run page."""
        changed = len(self.options.changed_values()) if self.options else 0
        return f'{changed} changed settings' if changed else 'Default settings'

    # --- picture ---

    def _layers(self):
        """(base option, overlay option) whose pictures are put one over the other, or None."""
        layers = self.info.get('layers')
        args = self.info.get('args', {})
        if layers and layers['base'] in args and layers['overlay'] in args:
            return layers['base'], layers['overlay']
        return None

    def _example(self, name, value):
        """The example picture of an option value (a file or a (base, overlay) pair), or None."""
        spec = self.info['args'][name]
        for item in spec.get('images') or []:
            if controls.format_value(spec, item['value']) == value:
                return item['image']
        return None

    def _world_image(self):
        """The world picture for the current settings: the layers put together, or the world picture."""
        layers = self._layers()
        if layers:
            base, overlay = layers
            base_image = self._example(base, self.options.value(base))
            if base_image:
                return (base_image, self._example(overlay, self.options.value(overlay)))
        return self.info.get('image')

    def _show_option(self, name):
        spec = self.info['args'][name]
        layers = self._layers()
        if layers and name in layers:
            # Each example over (or under) the current value of the other layer.
            base, overlay = layers
            spec = dict(spec, images=[dict(item, image=(
                (item['image'], self._example(overlay, self.options.value(overlay))) if name == base else
                (self._example(base, self.options.value(base)), item['image'])))
                for item in spec.get('images') or []])
        self.picture.show_option(name, spec, self.options.value(name))

    def _options_changed(self):
        normalize = lambda args: self.options.normalize(args)   # noqa: E731
        self.presets.select(self.options.changed_values(), normalize)
        self.changed.emit()

    def _preset_chosen(self, preset):
        self.options.set_values(preset['args'])
        if preset.get('image'):
            self.picture.show_preset(preset['label'], preset.get('description'), preset['image'])
        else:
            self.picture.show_world(self.info, self._world_image())

    def _example_chosen(self, name, value):
        self.options.set_value(name, value)
        self._show_option(name)
