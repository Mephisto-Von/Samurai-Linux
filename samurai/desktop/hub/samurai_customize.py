#!/usr/bin/env python3
"""Samurai Customization Hub - the window.

Run with no arguments to open the Hub. Every heavy decision lives in
``samurai_hub_core`` so it stays testable without Qt; this file only draws and
wires. Anything that talks to Plasma runs on a worker thread, because a
plasmashell script call can wait up to two minutes on a cold session and the
window must not freeze while it does.

Design notes:

* The Hub restyles itself from the draft palette, so picking colours changes
  the thing you are looking at, not only the desktop behind it.
* Nothing is permanent until Apply: every change re-applies a throwaway
  ``samurai-preview`` scheme, and Cancel re-applies the scheme that was in use
  when the Hub opened.
* A theme package is validated by the core before a byte is written, and its
  contents are never executed.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    from PySide6.QtCore import QSize, Qt, QThread, QTimer, Signal
    from PySide6.QtGui import QColor, QGuiApplication, QImageReader, QKeySequence, QPixmap, QShortcut
    from PySide6.QtWidgets import (
        QApplication,
        QCheckBox,
        QColorDialog,
        QComboBox,
        QDialog,
        QFileDialog,
        QFrame,
        QGridLayout,
        QHBoxLayout,
        QLabel,
        QLineEdit,
        QListWidget,
        QMainWindow,
        QMessageBox,
        QPushButton,
        QScrollArea,
        QSizePolicy,
        QSpinBox,
        QStackedWidget,
        QVBoxLayout,
        QWidget,
    )
except ImportError as error:  # pragma: no cover - only on a system without PySide6
    sys.stderr.write(
        "The Samurai Customization Hub needs PySide6, which is not installed:\n"
        f"  {error}\n"
        "Install it with: sudo apt install python3-pyside6.qtwidgets\n"
    )
    raise SystemExit(1)

import samurai_hub_core as core

CARD_WIDTH = 232
THUMB = QSize(320, 180)
FACE_ROLES = (
    ("background", "Background"),
    ("panel", "Panels"),
    ("surface", "Surfaces"),
    ("text", "Text"),
    ("text_dim", "Secondary text"),
    ("accent", "Accent"),
    ("gold", "Highlight"),
    ("border", "Borders"),
)
PRESET_HINTS = {"kuro": "Dark", "shiro": "Light"}


# --------------------------------------------------------------------- helpers


def thumbnail(path: Path) -> QPixmap:
    """Load a wallpaper scaled during decode: a 4K JPEG must not be decoded whole."""
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    size = reader.size()
    if size.isValid() and size.width() > 0:
        reader.setScaledSize(size.scaled(THUMB, Qt.KeepAspectRatio))
    image = reader.read()
    if image.isNull():
        return QPixmap()
    return QPixmap.fromImage(image)


def swatch(color: str, size: int = 18) -> QLabel:
    label = QLabel()
    label.setFixedSize(size, size)
    label.setStyleSheet(f"background:{color}; border:1px solid rgba(0,0,0,0.35); border-radius:3px;")
    return label


def hub_stylesheet(palette: core.Palette) -> str:
    return f"""
    QWidget {{ background: {palette.background}; color: {palette.text}; font-size: 10pt; }}
    QMainWindow, QScrollArea, QStackedWidget {{ background: {palette.background}; }}
    QScrollArea > QWidget > QWidget {{ background: transparent; }}
    #Header {{ background: {palette.panel}; border-bottom: 1px solid {palette.border}; }}
    #Title {{ font-size: 15pt; font-weight: 600; }}
    #Tagline {{ color: {palette.text_dim}; }}
    #Section {{ font-size: 12pt; font-weight: 600; padding-top: 4px; }}
    #Muted {{ color: {palette.text_dim}; }}
    #Warning {{ color: {palette.gold}; }}
    #Card {{ background: {palette.panel}; border: 1px solid {palette.border}; border-radius: 10px; }}
    #Card[selected="true"] {{ border: 2px solid {palette.accent}; background: {palette.surface}; }}
    #Nav {{ text-align: left; padding: 10px 14px; border: none; border-radius: 8px;
            background: transparent; color: {palette.text_dim}; }}
    #Nav:hover {{ background: {palette.panel}; color: {palette.text}; }}
    #Nav[active="true"] {{ background: {palette.surface}; color: {palette.text};
                           border-left: 3px solid {palette.accent}; }}
    QPushButton {{ background: {palette.surface}; color: {palette.text};
                   border: 1px solid {palette.border}; border-radius: 8px; padding: 7px 14px; }}
    QPushButton:hover {{ border-color: {palette.accent}; }}
    QPushButton:disabled {{ color: {palette.text_dim}; border-color: {palette.border}; }}
    QPushButton#Primary {{ background: {palette.accent};
                           color: {core.readable_text(palette.accent)};
                           border: none; font-weight: 600; }}
    QPushButton#Star {{ border: none; background: transparent; font-size: 14pt; padding: 0; }}
    QPushButton#Colour {{ border: 1px solid {palette.border}; border-radius: 6px; min-width: 92px; }}
    QComboBox, QLineEdit, QSpinBox {{ background: {palette.surface}; color: {palette.text};
                                      border: 1px solid {palette.border}; border-radius: 6px; padding: 4px 6px; }}
    QComboBox QAbstractItemView {{ background: {palette.surface}; color: {palette.text};
                                   selection-background-color: {palette.accent}; }}
    QListWidget {{ background: {palette.panel}; border: 1px solid {palette.border}; border-radius: 8px; }}
    QCheckBox {{ color: {palette.text}; }}
    QStatusBar {{ background: {palette.panel}; color: {palette.text_dim};
                  border-top: 1px solid {palette.border}; }}
    QToolTip {{ background: {palette.surface}; color: {palette.text}; border: 1px solid {palette.border}; }}
    """


class Worker(QThread):
    """Run one blocking call off the UI thread."""

    done = Signal(object)

    def __init__(self, function) -> None:
        super().__init__()
        self._function = function

    def run(self) -> None:  # pragma: no cover - exercised on a desktop
        try:
            result = self._function()
        except Exception as error:  # never let a worker crash the process
            result = (False, f"{type(error).__name__}: {error}")
        self.done.emit(result)


class WallpaperDialog(QDialog):
    """Fullscreen-ish preview of one wallpaper."""

    def __init__(self, wallpaper: core.Wallpaper, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(wallpaper.label)
        layout = QVBoxLayout(self)
        picture = QLabel()
        picture.setAlignment(Qt.AlignCenter)
        reader = QImageReader(str(wallpaper.path))
        reader.setAutoTransform(True)
        size = reader.size()
        if size.isValid():
            reader.setScaledSize(size.scaled(QSize(1400, 800), Qt.KeepAspectRatio))
        image = reader.read()
        if not image.isNull():
            picture.setPixmap(QPixmap.fromImage(image))
        layout.addWidget(picture)
        caption = QLabel(f"{wallpaper.label} — {wallpaper.category}")
        caption.setObjectName("Muted")
        layout.addWidget(caption)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addLayout(buttons)


# --------------------------------------------------------------------- cards


class ThemeCard(QFrame):
    chosen = Signal(str)

    def __init__(self, preset: core.Preset, parent=None) -> None:
        super().__init__(parent)
        self.preset = preset
        self.setObjectName("Card")
        self.setProperty("selected", "false")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(CARD_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        strip = QHBoxLayout()
        strip.setSpacing(4)
        for role in ("background", "panel", "surface", "accent", "gold", "text"):
            strip.addWidget(swatch(getattr(preset.palette, role), 22))
        strip.addStretch(1)
        layout.addLayout(strip)

        name = QLabel(preset.name)
        name.setStyleSheet("font-weight: 600;")
        layout.addWidget(name)

        tagline = QLabel(preset.tagline)
        tagline.setObjectName("Muted")
        tagline.setWordWrap(True)
        layout.addWidget(tagline)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.LeftButton:
            self.chosen.emit(self.preset.slug)
        super().mouseReleaseEvent(event)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)


class WallpaperCard(QFrame):
    chosen = Signal(str)
    starred = Signal(str)
    previewed = Signal(str)

    def __init__(self, wallpaper: core.Wallpaper, favourite: bool, parent=None) -> None:
        super().__init__(parent)
        self.wallpaper = wallpaper
        self.setObjectName("Card")
        self.setProperty("selected", "false")
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedWidth(CARD_WIDTH)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        picture = QLabel()
        pixmap = thumbnail(wallpaper.path)
        if not pixmap.isNull():
            picture.setFixedSize(THUMB.width() // 2, THUMB.height() // 2)
        picture.setAlignment(Qt.AlignCenter)
        if not pixmap.isNull():
            # Keep the aspect ratio: an imported picture need not be 16:9.
            picture.setPixmap(
                pixmap.scaled(
                    picture.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation
                )
            )
        layout.addWidget(picture)

        row = QHBoxLayout()
        title = QLabel(wallpaper.label)
        title.setStyleSheet("font-weight: 600;")
        row.addWidget(title)
        row.addStretch(1)
        self.star = QPushButton("★" if favourite else "☆")
        self.star.setObjectName("Star")
        self.star.setToolTip("Favourite")
        self.star.clicked.connect(lambda: self.starred.emit(self.wallpaper.stem))
        row.addWidget(self.star)
        layout.addLayout(row)

        meta = QLabel(wallpaper.category)
        meta.setObjectName("Muted")
        layout.addWidget(meta)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.LeftButton:
            self.chosen.emit(self.wallpaper.stem)
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.button() == Qt.LeftButton:
            self.previewed.emit(self.wallpaper.stem)
        super().mouseDoubleClickEvent(event)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", "true" if selected else "false")
        self.style().unpolish(self)
        self.style().polish(self)


# --------------------------------------------------------------------- window


class Hub(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.paths = core.core_paths()
        self.presets = core.load_presets(self.paths)
        self.wallpapers = core.list_wallpapers(self.paths)
        self.state = core.load_state(self.paths)
        self.preset = core.load_preset(self.state.get("preset") or "kuro", self.presets)
        self.draft = self.preset.palette
        self.history: list[core.Palette] = [self.draft]
        self.history_index = 0
        self.wallpaper_stem = self.state.get("last_wallpaper") or self.preset.wallpaper
        self.selected_wallpaper: core.Wallpaper | None = core.find_wallpaper(self.paths, self.wallpaper_stem)
        self.screen_choices: dict[int, str] = {}
        self.baseline_scheme = core.current_scheme() or self.preset.scheme_id
        self.apply_all_screens = True
        self._workers: list[Worker] = []
        self._theme_cards: list[ThemeCard] = []
        self._wallpaper_cards: list[WallpaperCard] = []
        self._preview_timer = QTimer(self)
        self._preview_timer.setSingleShot(True)
        self._preview_timer.setInterval(320)
        self._preview_timer.timeout.connect(self.preview)

        self.setWindowTitle("Samurai Customization Hub")
        self.setAcceptDrops(True)
        self.resize(1180, 760)
        self._build()
        self._restyle()
        self._select_preset(self.preset.slug, preview=False)
        # The first layout pass happens after construction; reflow once it has,
        # so the opening window already has the right number of columns.
        QTimer.singleShot(0, self._refresh_layouts)

    # -- construction ---------------------------------------------------

    def _build(self) -> None:
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        header = QFrame()
        header.setObjectName("Header")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(20, 14, 20, 14)
        title_box = QVBoxLayout()
        title = QLabel("Samurai Customization Hub")
        title.setObjectName("Title")
        self.subtitle = QLabel("")
        self.subtitle.setObjectName("Tagline")
        title_box.addWidget(title)
        title_box.addWidget(self.subtitle)
        header_layout.addLayout(title_box)
        header_layout.addStretch(1)

        self.undo_button = QPushButton("Undo")
        self.undo_button.clicked.connect(self.undo)
        self.redo_button = QPushButton("Redo")
        self.redo_button.clicked.connect(self.redo)
        self.reset_button = QPushButton("Reset")
        self.reset_button.setToolTip("Back to the Kuro default appearance")
        self.reset_button.clicked.connect(self.reset)
        self.cancel_button = QPushButton("Cancel")
        self.cancel_button.setToolTip("Discard changes and restore the appearance in use")
        self.cancel_button.clicked.connect(self.cancel)
        self.apply_button = QPushButton("Apply")
        self.apply_button.setObjectName("Primary")
        self.apply_button.clicked.connect(self.apply)
        for button in (
            self.undo_button,
            self.redo_button,
            self.reset_button,
            self.cancel_button,
            self.apply_button,
        ):
            header_layout.addWidget(button)
        outer.addWidget(header)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        nav_box = QFrame()
        nav_layout = QVBoxLayout(nav_box)
        nav_layout.setContentsMargins(12, 16, 12, 16)
        nav_layout.setSpacing(4)
        self.nav_buttons = {}
        for index, name in enumerate(("Themes", "Wallpapers", "Colours", "Desktop", "Share")):
            button = QPushButton(name)
            button.setObjectName("Nav")
            button.setProperty("active", "true" if index == 0 else "false")
            button.setCursor(Qt.PointingHandCursor)
            button.clicked.connect(lambda _=False, i=index: self.go(i))
            nav_layout.addWidget(button)
            self.nav_buttons[name] = button
        nav_layout.addStretch(1)
        self.theme_label = QLabel("")
        self.theme_label.setObjectName("Muted")
        self.theme_label.setWordWrap(True)
        nav_layout.addWidget(self.theme_label)
        nav_box.setFixedWidth(190)
        body.addWidget(nav_box)

        self.pages = QStackedWidget()
        self.pages.addWidget(self._themes_page())
        self.pages.addWidget(self._wallpapers_page())
        self.pages.addWidget(self._colours_page())
        self.pages.addWidget(self._desktop_page())
        self.pages.addWidget(self._share_page())
        body.addWidget(self.pages, 1)
        outer.addLayout(body, 1)
        self.setCentralWidget(central)
        self.statusBar().showMessage("Ready")

        QShortcut(QKeySequence.Undo, self, activated=self.undo)
        QShortcut(QKeySequence.Redo, self, activated=self.redo)

    def _scrolled(self, inner: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setWidget(inner)
        return area

    def _themes_page(self) -> QWidget:
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        heading = QLabel("Themes")
        heading.setObjectName("Section")
        layout.addWidget(heading)
        hint = QLabel(
            "Every theme is a complete appearance: colours, panels and a matching wallpaper. "
            "Selecting one previews it immediately."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)
        self.themes_grid = QGridLayout()
        self.themes_grid.setSpacing(12)
        layout.addLayout(self.themes_grid)
        self.themes_inner = inner
        self.theme_cards_holder = layout
        for preset in self.presets:
            card = ThemeCard(preset)
            card.chosen.connect(self._select_preset)
            self._theme_cards.append(card)
        self._reflow_themes()
        self.themes_contrast = QLabel("")
        self.themes_contrast.setObjectName("Warning")
        self.themes_contrast.setWordWrap(True)
        layout.addWidget(self.themes_contrast)
        layout.addStretch(1)
        return self._scrolled(inner)

    def _wallpapers_page(self) -> QWidget:
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        heading = QLabel("Wallpapers")
        heading.setObjectName("Section")
        layout.addWidget(heading)

        # Two rows rather than one: with a long theme name and a wide screen
        # label the single row clipped its last button off the page.
        filters = QHBoxLayout()
        self.category = QComboBox()
        self.category.addItems(core.categories(self.wallpapers))
        self.category.currentTextChanged.connect(self._fill_wallpapers)
        filters.addWidget(QLabel("Category"))
        filters.addWidget(self.category)
        self.favourites_only = QCheckBox("Favourites only")
        self.favourites_only.toggled.connect(self._fill_wallpapers)
        filters.addWidget(self.favourites_only)
        filters.addStretch(1)
        layout.addLayout(filters)

        actions = QHBoxLayout()
        preview_button = QPushButton("Preview")
        preview_button.clicked.connect(self._preview_wallpaper)
        actions.addWidget(preview_button)
        import_button = QPushButton("Add image…")
        import_button.setToolTip("Import your own picture as a wallpaper")
        import_button.clicked.connect(self._import_wallpaper)
        actions.addWidget(import_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.wallpaper_grid = QGridLayout()
        self.wallpaper_grid.setSpacing(12)
        layout.addLayout(self.wallpaper_grid)
        self.wallpapers_inner = inner
        self._fill_wallpapers()

        screens = QFrame()
        screens.setObjectName("Card")
        screen_layout = QVBoxLayout(screens)
        screen_layout.setContentsMargins(14, 12, 14, 12)
        screen_layout.addWidget(QLabel("Screens"))
        self.screen_rows = QVBoxLayout()
        screen_layout.addLayout(self.screen_rows)
        self.screen_hint = QLabel("")
        self.screen_hint.setObjectName("Muted")
        self.screen_hint.setWordWrap(True)
        screen_layout.addWidget(self.screen_hint)
        layout.addWidget(screens)
        self._fill_screens()

        rotation = QFrame()
        rotation.setObjectName("Card")
        rotation_layout = QHBoxLayout(rotation)
        rotation_layout.setContentsMargins(14, 12, 14, 12)
        rotation_layout.addWidget(QLabel("Rotate every"))
        self.rotation_minutes = QSpinBox()
        self.rotation_minutes.setRange(1, 1440)
        self.rotation_minutes.setSuffix(" min")
        self.rotation_minutes.setValue(int(self.state.get("rotation_minutes", 60)))
        rotation_layout.addWidget(self.rotation_minutes)
        self.rotation_shuffle = QCheckBox("In random order")
        self.rotation_shuffle.setChecked(bool(self.state.get("rotation_shuffle", True)))
        rotation_layout.addWidget(self.rotation_shuffle)
        self.rotation_toggle = QPushButton(
            "Stop rotation" if core.rotation_enabled(self.paths) else "Start rotation"
        )
        self.rotation_toggle.clicked.connect(self._toggle_rotation)
        rotation_layout.addWidget(self.rotation_toggle)
        rotation_layout.addStretch(1)
        lock = QPushButton("Use for lock screen")
        lock.clicked.connect(self._lock_screen_wallpaper)
        rotation_layout.addWidget(lock)
        layout.addWidget(rotation)
        layout.addStretch(1)
        return self._scrolled(inner)

    def _colours_page(self) -> QWidget:
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        heading = QLabel("Colours")
        heading.setObjectName("Section")
        layout.addWidget(heading)
        hint = QLabel(
            "Change any role on its own. The Hub and the desktop update as you pick, "
            "and nothing is saved until Apply."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        grid = QGridLayout()
        grid.setSpacing(10)
        self.colour_buttons: dict[str, QPushButton] = {}
        for row, (role, label) in enumerate(FACE_ROLES):
            grid.addWidget(QLabel(label), row, 0)
            button = QPushButton()
            button.setObjectName("Colour")
            button.clicked.connect(lambda _=False, r=role: self._pick_colour(r))
            grid.addWidget(button, row, 1)
            self.colour_buttons[role] = button
        grid.setColumnStretch(2, 1)
        layout.addLayout(grid)

        actions = QHBoxLayout()
        accent_button = QPushButton("Accent from selected wallpaper")
        accent_button.clicked.connect(self._accent_from_wallpaper)
        actions.addWidget(accent_button)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.contrast_label = QLabel("")
        self.contrast_label.setObjectName("Warning")
        self.contrast_label.setWordWrap(True)
        layout.addWidget(self.contrast_label)

        save_box = QFrame()
        save_box.setObjectName("Card")
        save_layout = QHBoxLayout(save_box)
        save_layout.setContentsMargins(14, 12, 14, 12)
        save_layout.addWidget(QLabel("Theme name"))
        self.custom_name = QLineEdit(str(self.state.get("custom_name") or "Custom"))
        self.custom_name.setFixedWidth(220)
        save_layout.addWidget(self.custom_name)
        save = QPushButton("Save as theme")
        save.clicked.connect(self._save_custom_theme)
        save_layout.addWidget(save)
        save_layout.addStretch(1)
        layout.addWidget(save_box)
        layout.addStretch(1)
        return self._scrolled(inner)

    def _desktop_page(self) -> QWidget:
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        heading = QLabel("Desktop")
        heading.setObjectName("Section")
        layout.addWidget(heading)

        form = QGridLayout()
        form.setSpacing(10)
        self.icon_combo = QComboBox()
        themes = core.installed_icon_themes() or ["breeze"]
        self.icon_combo.addItems(themes)
        current_icons = core.read_config("--file", "kdeglobals", "--group", "Icons", "--key", "Theme")
        if current_icons in themes:
            self.icon_combo.setCurrentText(current_icons)
        form.addWidget(QLabel("Icon theme"), 0, 0)
        form.addWidget(self.icon_combo, 0, 1)

        self.decoration_combo = QComboBox()
        decorations = core.installed_decorations() or ["Breeze"]
        self.decoration_combo.addItems(decorations)
        current_decoration = core.read_config(
            "--file", "kwinrc", "--group", "org.kde.kdecoration2", "--key", "theme"
        )
        if current_decoration in decorations:
            self.decoration_combo.setCurrentText(current_decoration)
        form.addWidget(QLabel("Window decoration"), 1, 0)
        form.addWidget(self.decoration_combo, 1, 1)

        self.animation_combo = QComboBox()
        for label, value in (("Off", 0.0), ("Fast", 0.5), ("Normal", 1.0), ("Slow", 2.0)):
            self.animation_combo.addItem(label, value)
        form.addWidget(QLabel("Animations"), 2, 0)
        form.addWidget(self.animation_combo, 2, 1)

        self.blur_check = QCheckBox("Blur behind transparent surfaces")
        self.blur_check.setChecked(True)
        form.addWidget(self.blur_check, 3, 0, 1, 2)

        self.blur_strength = QSpinBox()
        self.blur_strength.setRange(1, 20)
        self.blur_strength.setValue(8)
        form.addWidget(QLabel("Blur strength"), 4, 0)
        form.addWidget(self.blur_strength, 4, 1)

        self.panel_height = QSpinBox()
        self.panel_height.setRange(24, 120)
        self.panel_height.setValue(44)
        form.addWidget(QLabel("Panel height"), 5, 0)
        form.addWidget(self.panel_height, 5, 1)

        self.panel_alignment = QComboBox()
        self.panel_alignment.addItems(["left", "center", "right"])
        self.panel_alignment.setCurrentText("center")
        form.addWidget(QLabel("Panel alignment"), 6, 0)
        form.addWidget(self.panel_alignment, 6, 1)

        self.panel_hiding = QComboBox()
        self.panel_hiding.addItems(["none", "autohide", "dodge"])
        form.addWidget(QLabel("Panel visibility"), 7, 0)
        form.addWidget(self.panel_hiding, 7, 1)
        form.setColumnStretch(2, 1)
        layout.addLayout(form)

        apply_desktop = QPushButton("Apply desktop settings")
        apply_desktop.setObjectName("Primary")
        apply_desktop.clicked.connect(self._apply_desktop)
        layout.addWidget(apply_desktop, alignment=Qt.AlignLeft)

        note = QLabel(
            "Icons, decorations, blur and panel geometry are written with KDE's own tools "
            "and apply to the running session. Icon sets and cursor sets are not shipped by "
            "Samurai Linux yet, so those lists show what the system has installed."
        )
        note.setObjectName("Muted")
        note.setWordWrap(True)
        layout.addWidget(note)
        layout.addStretch(1)
        return self._scrolled(inner)

    def _share_page(self) -> QWidget:
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(20, 18, 20, 18)
        layout.setSpacing(12)
        heading = QLabel("Share")
        heading.setObjectName("Section")
        layout.addWidget(heading)
        hint = QLabel(
            "A theme package is a .zip holding one theme.json and, optionally, one wallpaper. "
            "Imports are checked before anything is written: no scripts, no links, no paths "
            "outside the package, no executable bits."
        )
        hint.setObjectName("Muted")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        layout.addWidget(QLabel("Your themes"))
        self.library_list = QListWidget()
        self.library_list.setMinimumHeight(180)
        layout.addWidget(self.library_list)

        buttons = QGridLayout()
        export_button = QPushButton("Export current theme…")
        export_button.clicked.connect(self._export_theme)
        buttons.addWidget(export_button, 0, 0)
        import_button = QPushButton("Import theme…")
        import_button.clicked.connect(self._import_theme)
        buttons.addWidget(import_button, 0, 1)
        apply_button = QPushButton("Apply selected")
        apply_button.clicked.connect(self._apply_library_theme)
        buttons.addWidget(apply_button, 1, 0)
        remove_button = QPushButton("Remove selected")
        remove_button.clicked.connect(self._remove_library_theme)
        buttons.addWidget(remove_button, 1, 1)
        buttons.setColumnStretch(2, 1)
        layout.addLayout(buttons)

        open_folder = QPushButton("Open theme folder")
        open_folder.clicked.connect(self._open_library)
        layout.addWidget(open_folder, alignment=Qt.AlignLeft)
        layout.addStretch(1)
        self._fill_library()
        return self._scrolled(inner)

    # -- layout helpers --------------------------------------------------

    def _reflow(self, grid: QGridLayout, cards: list[QWidget], container: QWidget) -> None:
        for card in cards:
            grid.removeWidget(card)
        # Measure the page this grid lives on, not the stack: until the window
        # has been laid out, the stack still has its default size.
        width = max(container.width(), CARD_WIDTH)
        columns = max(1, (width - 60) // (CARD_WIDTH + 12))
        for index, card in enumerate(cards):
            grid.addWidget(card, index // columns, index % columns)
        # A grid hands leftover width to its columns, which pushes the fixed
        # width cards apart (they drifted 70 px from each other at 1180 px).
        # Give the empty column after the last card all of the slack instead.
        for column in range(max(columns, grid.columnCount()) + 1):
            grid.setColumnStretch(column, 1 if column == columns else 0)

    def _reflow_themes(self) -> None:
        self._reflow(self.themes_grid, list(self._theme_cards), self.themes_inner)

    def _fill_wallpapers(self) -> None:
        for card in getattr(self, "_wallpaper_cards", []):
            card.setParent(None)
            card.deleteLater()
        self._wallpaper_cards = []
        favourites = set(self.state.get("favourites") or ())
        category = self.category.currentText() if hasattr(self, "category") else "All"
        only_favourites = self.favourites_only.isChecked() if hasattr(self, "favourites_only") else False
        shown = []
        for wallpaper in self.wallpapers:
            if category not in {"", "All"} and wallpaper.category != category:
                continue
            if only_favourites and wallpaper.stem not in favourites:
                continue
            card = WallpaperCard(wallpaper, wallpaper.stem in favourites)
            card.chosen.connect(self._select_wallpaper)
            card.starred.connect(self._toggle_favourite)
            card.previewed.connect(self._preview_wallpaper_by_stem)
            self._wallpaper_cards.append(card)
            shown.append(card)
        self._reflow(self.wallpaper_grid, shown, self.wallpapers_inner)
        for card in shown:
            card.set_selected(
                self.selected_wallpaper is not None
                and card.wallpaper.stem == self.selected_wallpaper.stem
            )

    def _fill_screens(self) -> None:
        while self.screen_rows.count():
            item = self.screen_rows.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        screens = QGuiApplication.screens()
        if not screens:
            self.screen_hint.setText("No screens were reported; the wallpaper will be applied to all of them.")
            return
        for index, screen in enumerate(screens):
            row = QHBoxLayout()
            name = QLabel(f"{index + 1}. {screen.name()} ({screen.size().width()}x{screen.size().height()})")
            name.setObjectName("Muted")
            row.addWidget(name)
            combo = QComboBox()
            combo.addItem("Same as main", "")
            for wallpaper in self.wallpapers:
                combo.addItem(wallpaper.label, wallpaper.stem)
            combo.currentIndexChanged.connect(
                lambda _=0, i=index, c=combo: self.screen_choices.__setitem__(i, c.currentData())
            )
            row.addWidget(combo)
            row.addStretch(1)
            holder = QWidget()
            holder.setLayout(row)
            self.screen_rows.addWidget(holder)
        self.screen_hint.setText(
            "Leave a screen on “Same as main” to use one wallpaper everywhere."
        )

    def _fill_library(self) -> None:
        self.library_list.clear()
        for preset in core.library_themes(self.paths):
            self.library_list.addItem(f"{preset.name} ({preset.slug})")

    # -- preview / apply -------------------------------------------------

    def _restyle(self) -> None:
        self.setStyleSheet(hub_stylesheet(self.draft))
        self.subtitle.setText(f"{self.preset.name} — {self.preset.tagline}")
        self.theme_label.setText(
            "Custom colours" if self.draft != self.preset.palette else "Built-in theme"
        )
        if hasattr(self, "colour_buttons"):
            for role, button in self.colour_buttons.items():
                colour = getattr(self.draft, role)
                button.setText(colour)
                button.setStyleSheet(
                    f"background:{colour}; color:{core.readable_text(colour)}; "
                    f"border:1px solid {self.draft.border}; border-radius:6px; padding:5px 8px;"
                )
        problems = self.draft.contrast_problems()
        message = "" if not problems else "Readability: " + "; ".join(problems)
        if hasattr(self, "contrast_label"):
            self.contrast_label.setText(message)
        if hasattr(self, "themes_contrast"):
            self.themes_contrast.setText(message)

    def _push_history(self) -> None:
        if self.history[self.history_index] == self.draft:
            return
        del self.history[self.history_index + 1 :]
        self.history.append(self.draft)
        self.history_index = len(self.history) - 1
        self._update_history_buttons()

    def _update_history_buttons(self) -> None:
        self.undo_button.setEnabled(self.history_index > 0)
        self.redo_button.setEnabled(self.history_index < len(self.history) - 1)

    def _set_draft(self, palette: core.Palette, preview: bool = True) -> None:
        self.draft = palette
        self._push_history()
        self._restyle()
        if preview:
            self._preview_timer.start()

    def preview(self) -> None:
        palette = self.draft
        text = core.render_scheme(core.PREVIEW_SCHEME, "Samurai Preview", palette)
        core.write_user_scheme(self.paths, core.PREVIEW_SCHEME, text)
        self._run(core.apply_scheme, core.PREVIEW_SCHEME, on_done=self._preview_done)

    def _preview_done(self, result) -> None:
        ok, message = result if isinstance(result, tuple) else (False, str(result))
        self.statusBar().showMessage(message)

    def _run(self, function, *args, on_done=None) -> None:
        worker = Worker(lambda: function(*args))
        worker.done.connect(on_done or (lambda result: self.statusBar().showMessage(str(result))))
        worker.finished.connect(lambda w=worker: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(worker)
        worker.start()

    def _select_preset(self, slug: str, preview: bool = True) -> None:
        try:
            preset = core.load_preset(slug, self.presets)
        except KeyError:
            return
        self.preset = preset
        self.state["preset"] = slug
        for card in self._theme_cards:
            card.set_selected(card.preset.slug == slug)
        if preset.wallpaper:
            wallpaper = core.find_wallpaper(self.paths, preset.wallpaper)
            if wallpaper is not None:
                self.selected_wallpaper = wallpaper
                self.wallpaper_stem = wallpaper.stem
        self.draft = preset.palette
        self.history = [self.draft]
        self.history_index = 0
        self._update_history_buttons()
        self._restyle()
        if preview:
            self._preview_timer.start()

    def _select_wallpaper(self, stem: str) -> None:
        wallpaper = core.find_wallpaper(self.paths, stem)
        if wallpaper is None:
            return
        self.selected_wallpaper = wallpaper
        self.wallpaper_stem = stem
        for card in self._wallpaper_cards:
            card.set_selected(card.wallpaper.stem == stem)
        self.statusBar().showMessage(
            f"{wallpaper.label} selected — press Apply to use it, or double-click to preview it"
        )

    def _preview_wallpaper_by_stem(self, stem: str) -> None:
        wallpaper = core.find_wallpaper(self.paths, stem)
        if wallpaper is not None:
            WallpaperDialog(wallpaper, self).exec()

    def _preview_wallpaper(self) -> None:
        if self.selected_wallpaper is None:
            self.statusBar().showMessage("Select a wallpaper first")
            return
        WallpaperDialog(self.selected_wallpaper, self).exec()

    def _toggle_favourite(self, stem: str) -> None:
        favourites = list(self.state.get("favourites") or ())
        if stem in favourites:
            favourites.remove(stem)
        else:
            favourites.append(stem)
        self.state["favourites"] = favourites
        core.save_state(self.paths, self.state)
        self._fill_wallpapers()

    def _pick_colour(self, role: str) -> None:
        current = QColor(getattr(self.draft, role))
        chosen = QColorDialog.getColor(current, self, f"Choose {role.replace('_', ' ')}")
        if chosen.isValid():
            self._set_draft(self.draft.with_role(role, chosen.name().upper()))

    def _accent_from_wallpaper(self) -> None:
        if self.selected_wallpaper is None:
            self.statusBar().showMessage("Select a wallpaper first")
            return
        accent = core.extract_accent(self.paths, self.selected_wallpaper.path)
        if not accent:
            self.statusBar().showMessage(
                "Could not read an accent colour from that image (Pillow is not installed?)"
            )
            return
        self._set_draft(core.palette_from_wallpaper(self.draft, accent))
        self.statusBar().showMessage(f"Accent taken from {self.selected_wallpaper.label}: {accent}")

    def _custom_scheme_id(self) -> str:
        slug = re_slug(self.custom_name.text()) or "custom"
        return f"{core.CUSTOM_SCHEME}-{slug}" if slug != "custom" else core.CUSTOM_SCHEME

    def apply(self) -> None:
        preset_colours = self.draft == self.preset.palette
        shipped = core.theme_scheme_text(self.paths, self.preset.slug) if preset_colours else None
        if shipped is not None:
            # Untouched preset: activate the scheme the image already installs
            # instead of writing a duplicate of it into the user's directory.
            scheme_id = self.preset.scheme_id
            title = self.preset.name
        else:
            scheme_id = self._custom_scheme_id()
            title = self.custom_name.text().strip() or "Custom"
            text = core.render_scheme(scheme_id, f"Samurai {title}", self.draft)
            problems = core.scheme_problems(text, scheme_id)
            if problems:
                self.statusBar().showMessage("The scheme is not valid: " + "; ".join(problems))
                return
            core.write_user_scheme(self.paths, scheme_id, text)
            self.state["custom_palette"] = self.draft.as_dict()
        self.state["custom_name"] = title
        self.state["last_wallpaper"] = self.wallpaper_stem
        core.save_state(self.paths, self.state)
        core.write_theme_marker(self.paths, self.preset.slug)
        self.baseline_scheme = scheme_id

        def work():
            messages = []
            ok, message = core.apply_scheme(scheme_id)
            messages.append(message)
            if self.selected_wallpaper is not None:
                per_screen = {}
                if not self.apply_all_screens:
                    for screen, stem in self.screen_choices.items():
                        if not stem:
                            continue
                        wallpaper = core.find_wallpaper(self.paths, stem)
                        if wallpaper is not None:
                            per_screen[screen] = wallpaper.path
                ok, message = core.apply_wallpaper(self.selected_wallpaper.path, per_screen or None)
                messages.append(message)
            return "\n".join(messages)

        self._run(lambda: work(), on_done=self._applied)

    def _applied(self, result) -> None:
        message = result if isinstance(result, str) else str(result)
        self.statusBar().showMessage(message.replace("\n", " · "))

    def cancel(self) -> None:
        scheme_id = self.baseline_scheme or "samurai-kuro"
        self._run(core.apply_scheme, scheme_id, on_done=lambda r: self.statusBar().showMessage(
            f"Changes discarded; {scheme_id} restored"
        ))
        self.draft = self.preset.palette
        self.history = [self.draft]
        self.history_index = 0
        self._update_history_buttons()
        self._restyle()

    def reset(self) -> None:
        self._select_preset("kuro")

    def undo(self) -> None:
        if self.history_index > 0:
            self.history_index -= 1
            self.draft = self.history[self.history_index]
            self._restyle()
            self._preview_timer.start()
            self._update_history_buttons()

    def redo(self) -> None:
        if self.history_index < len(self.history) - 1:
            self.history_index += 1
            self.draft = self.history[self.history_index]
            self._restyle()
            self._preview_timer.start()
            self._update_history_buttons()

    # -- secondary actions ------------------------------------------------

    def _save_custom_theme(self) -> None:
        self.apply()
        self.statusBar().showMessage("Saved as a user color scheme; it is listed under System Settings → Colours")

    def _import_wallpaper(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Add a wallpaper", str(Path.home()), "Pictures (*.jpg *.jpeg *.png)"
        )
        if chosen:
            self._adopt_wallpaper(Path(chosen))

    def _adopt_wallpaper(self, source: Path) -> None:
        """Copy a picture the user chose or dropped into their own wallpaper folder."""
        if source.suffix.lower() not in {".jpg", ".jpeg", ".png"} or not source.is_file():
            self.statusBar().showMessage(f"{source.name} is not a JPEG or PNG picture")
            return
        target = self.paths.user_wallpapers / (
            f"user-{re_slug(source.stem) or 'image'}{source.suffix.lower()}"
        )
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil_copy(source, target)
        except OSError as error:
            self.statusBar().showMessage(f"Could not copy the image: {error}")
            return
        self.wallpapers = core.list_wallpapers(self.paths)
        self.category.blockSignals(True)
        self.category.clear()
        self.category.addItems(core.categories(self.wallpapers))
        self.category.blockSignals(False)
        self._fill_wallpapers()
        self._fill_screens()
        self._select_wallpaper(target.stem)

    def _lock_screen_wallpaper(self) -> None:
        if self.selected_wallpaper is None:
            self.statusBar().showMessage("Select a wallpaper first")
            return
        ok, message = core.apply_lockscreen_wallpaper(self.selected_wallpaper.path)
        self.statusBar().showMessage(message)

    def _toggle_rotation(self) -> None:
        if core.rotation_enabled(self.paths):
            ok, message = core.disable_rotation(self.paths)
            self.rotation_toggle.setText("Start rotation")
        else:
            exec_line = f'"{sys.executable}" "{Path(__file__).resolve()}"'
            ok, message = core.install_rotation(
                self.paths,
                exec_line,
                self.rotation_minutes.value(),
                self.rotation_shuffle.isChecked(),
            )
            self.rotation_toggle.setText("Stop rotation")
        self.state["rotation_minutes"] = self.rotation_minutes.value()
        self.state["rotation_shuffle"] = self.rotation_shuffle.isChecked()
        core.save_state(self.paths, self.state)
        self.statusBar().showMessage(message)

    def _apply_desktop(self) -> None:
        settings = {
            "icon_theme": self.icon_combo.currentText(),
            "decoration": self.decoration_combo.currentText(),
            "animations": self.animation_combo.currentData(),
            "blur": self.blur_check.isChecked(),
            "blur_strength": self.blur_strength.value(),
        }
        messages = core.apply_desktop_settings(settings)
        ok, panel_message = core.apply_panel(
            self.panel_height.value(),
            self.panel_alignment.currentText(),
            self.panel_hiding.currentText(),
        )
        messages.append(panel_message)
        self.statusBar().showMessage(" · ".join(messages))

    def _export_theme(self) -> None:
        suggested = f"samurai-{self.preset.slug}.zip"
        chosen, _ = QFileDialog.getSaveFileName(
            self, "Export theme", str(Path.home() / suggested), "Theme package (*.zip)"
        )
        if not chosen:
            return
        preset = core.Preset(
            slug=self.preset.slug,
            name=self.custom_name.text().strip() or self.preset.name,
            tagline=self.preset.tagline,
            dark=self.draft.is_dark(),
            wallpaper=self.wallpaper_stem,
            palette=self.draft,
        )
        wallpaper = self.selected_wallpaper.path if self.selected_wallpaper else None
        try:
            target = core.export_package(chosen, preset, wallpaper)
        except OSError as error:
            self.statusBar().showMessage(f"Could not export: {error}")
            return
        self.statusBar().showMessage(f"Exported {target.name}")

    def _import_theme(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(
            self, "Import theme", str(Path.home()), "Theme package (*.zip)"
        )
        if not chosen:
            return
        try:
            directory = core.import_package(self.paths, chosen)
        except core.InvalidPackage as error:
            QMessageBox.warning(self, "Theme not imported", str(error))
            return
        except OSError as error:
            QMessageBox.warning(self, "Theme not imported", f"Could not write the theme: {error}")
            return
        self._fill_library()
        self.statusBar().showMessage(f"Imported into {directory}")

    def _library_preset(self) -> core.Preset | None:
        item = self.library_list.currentItem()
        if item is None:
            self.statusBar().showMessage("Select one of your themes first")
            return None
        slug = item.text().rsplit("(", 1)[-1].rstrip(")")
        for preset in core.library_themes(self.paths):
            if preset.slug == slug:
                return preset
        return None

    def _apply_library_theme(self) -> None:
        preset = self._library_preset()
        if preset is None:
            return
        self.custom_name.setText(preset.name)
        self._set_draft(preset.palette)

    def _remove_library_theme(self) -> None:
        preset = self._library_preset()
        if preset is None:
            return
        target = self.paths.library / preset.slug
        if QMessageBox.question(self, "Remove theme", f"Delete {preset.name} from your themes?") != QMessageBox.Yes:
            return
        shutil_rmtree(target)
        self._fill_library()

    def _open_library(self) -> None:
        self.paths.library.mkdir(parents=True, exist_ok=True)
        core.run(["xdg-open", str(self.paths.library)], timeout=10)
        self.statusBar().showMessage(str(self.paths.library))

    def go(self, index: int) -> None:
        self.pages.setCurrentIndex(index)
        # A page that has just become visible may have been measured while the
        # stack was still at its default size, so lay it out again now.
        self._refresh_layouts()
        for position, name in enumerate(("Themes", "Wallpapers", "Colours", "Desktop", "Share")):
            button = self.nav_buttons[name]
            button.setProperty("active", "true" if position == index else "false")
            button.style().unpolish(button)
            button.style().polish(button)

    # -- drag and drop --------------------------------------------------

    def dragEnterEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._dropped_pictures(event.mimeData()):
            event.acceptProposedAction()

    def dragMoveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self._dropped_pictures(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802 - Qt naming
        pictures = self._dropped_pictures(event.mimeData())
        if not pictures:
            return
        event.acceptProposedAction()
        for picture in pictures:
            self._adopt_wallpaper(picture)
        self.go(1)
        self.statusBar().showMessage(
            f"Added {pictures[0].name} — press Apply to use it"
        )

    @staticmethod
    def _dropped_pictures(mime) -> list[Path]:
        if not mime.hasUrls():
            return []
        return [
            Path(url.toLocalFile())
            for url in mime.urls()
            if url.isLocalFile() and Path(url.toLocalFile()).suffix.lower() in {".jpg", ".jpeg", ".png"}
        ]

    def _refresh_layouts(self) -> None:
        if hasattr(self, "themes_grid"):
            self._reflow_themes()
        if hasattr(self, "wallpaper_grid") and self._wallpaper_cards:
            self._reflow(self.wallpaper_grid, list(self._wallpaper_cards), self.wallpapers_inner)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        super().resizeEvent(event)
        self._refresh_layouts()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt naming
        core.save_state(self.paths, self.state)
        super().closeEvent(event)


# --------------------------------------------------------------------- helpers


def re_slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").strip().lower()).strip("-")[:32]


def shutil_copy(source: Path, target: Path) -> None:
    import shutil

    shutil.copy2(source, target)


def shutil_rmtree(target: Path) -> None:
    import shutil

    shutil.rmtree(target, ignore_errors=True)


def main(argv: list[str]) -> int:
    if argv:
        # --verify, --list-*, --next-wallpaper and --help belong to the core.
        return core.main(argv)
    app = QApplication(sys.argv)
    app.setApplicationName("Samurai Customization Hub")
    app.setApplicationDisplayName("Samurai Customization Hub")
    hub = Hub()
    hub.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
