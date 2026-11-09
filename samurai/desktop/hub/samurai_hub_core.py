"""Logic for the Samurai Customization Hub, with no Qt in it.

The Hub window (``samurai_customize.py``) is a thin layer over this module, so
everything that can be checked without a running desktop - colour maths, KDE
color-scheme rendering, theme packages, rotation units, wallpaper metadata -
lives here and is exercised by ``tests/smoke.sh``.

Design rules that matter for safety:

* A theme package is never extracted with anything but an allowlist of known
  members, and nothing inside a package is ever executed. ``inspect_package``
  rejects traversal, absolute paths, links and executable bits before a byte is
  written.
* Applying appearance goes through KDE's own tools (``plasma-apply-colorscheme``,
  plasmashell scripting via D-Bus, ``kwriteconfig6``); nothing here patches
  files owned by another package.
* Every failure returns a message instead of raising into the UI, because a
  customization tool that dies while the user is trying a theme is worse than
  one that says what went wrong.
"""

from __future__ import annotations

import colorsys
import configparser
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from dataclasses import dataclass, field, replace
from pathlib import Path

# ---------------------------------------------------------------- constants

SCHEME_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,30}$")
HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

PALETTE_ROLES = (
    "background",
    "panel",
    "surface",
    "text",
    "text_dim",
    "accent",
    "gold",
    "border",
)

#: Members a theme package may contain. Anything else fails the import.
PACKAGE_MEMBERS = ("theme.json", "wallpaper.jpg", "wallpaper.png", "README.txt")
PACKAGE_MAX_BYTES = 32 * 1024 * 1024
PACKAGE_MAX_MEMBERS = 16

PREVIEW_SCHEME = "samurai-preview"
CUSTOM_SCHEME = "samurai-custom"

ROTATION_SERVICE = "samurai-wallpaper-rotation.service"
ROTATION_TIMER = "samurai-wallpaper-rotation.timer"

HUB_DIR = Path(__file__).resolve().parent


class InvalidPackage(Exception):
    """A theme package that must not be imported."""


# ---------------------------------------------------------------- filesystem


@dataclass(frozen=True)
class Paths:
    hub: Path
    themes: Path
    wallpapers: Path
    user_schemes: Path
    config: Path
    library: Path
    cache: Path
    #: Where an imported picture goes. /usr/share belongs to root, so a normal
    #: user's own wallpapers live under XDG_DATA_HOME and are listed after the
    #: shipped ones.
    user_wallpapers: Path = Path()

    @property
    def state_file(self) -> Path:
        return self.config / "hub.json"

    @property
    def rotation_dir(self) -> Path:
        return self.config / "systemd" / "user"


def _first_dir(*candidates: Path) -> Path:
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    return candidates[-1]


def core_paths() -> Paths:
    """Resolve the paths the Hub uses, honouring the same env vars as samurai-theme."""
    home = Path.home()
    data = Path(os.environ.get("XDG_DATA_HOME") or home / ".local" / "share")
    config = Path(os.environ.get("XDG_CONFIG_HOME") or home / ".config")
    cache = Path(os.environ.get("XDG_CACHE_HOME") or home / ".cache")
    repo = HUB_DIR.parents[2] if len(HUB_DIR.parents) > 2 else HUB_DIR

    themes = Path(
        os.environ.get("SAMURAI_THEME_DIR")
        or _first_dir(
            Path("/usr/share/samurai/themes"),
            HUB_DIR.parents[1] / "themes" if len(HUB_DIR.parents) > 1 else HUB_DIR / "themes",
        )
    )
    wallpapers = Path(
        os.environ.get("SAMURAI_WALLPAPER_DIR")
        or _first_dir(
            Path("/usr/share/backgrounds/samurai"),
            repo / "build/config/includes.chroot/usr/share/backgrounds/samurai",
        )
    )
    return Paths(
        hub=HUB_DIR,
        themes=themes,
        wallpapers=wallpapers,
        user_schemes=data / "color-schemes",
        config=config / "samurai",
        library=data / "samurai" / "themes",
        cache=cache / "samurai" / "hub",
        user_wallpapers=data / "samurai" / "wallpapers",
    )


# ---------------------------------------------------------------- colour maths


def is_hex(value: object) -> bool:
    return isinstance(value, str) and bool(HEX_RE.match(value))


def hex_to_rgb(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i : i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def rgb_to_hex(rgb: tuple[int, int, int]) -> str:
    return "#{:02X}{:02X}{:02X}".format(*(max(0, min(255, int(round(c)))) for c in rgb))


def mix(first: str, second: str, weight: float) -> str:
    """Blend ``weight`` of ``second`` into ``first`` (0..1)."""
    weight = max(0.0, min(1.0, weight))
    a, b = hex_to_rgb(first), hex_to_rgb(second)
    return rgb_to_hex(tuple(a[i] + (b[i] - a[i]) * weight for i in range(3)))  # type: ignore[arg-type]


def scale(color: str, factor: float) -> str:
    """Darken (factor < 1) or lighten (factor > 1) towards black/white."""
    factor = max(0.0, min(2.0, factor))
    return rgb_to_hex(tuple(c * factor for c in hex_to_rgb(color)))  # type: ignore[arg-type]


def relative_luminance(color: str) -> float:
    channels = []
    for value in hex_to_rgb(color):
        srgb = value / 255
        channels.append(srgb / 12.92 if srgb <= 0.03928 else ((srgb + 0.055) / 1.055) ** 2.4)
    return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2]


def contrast_ratio(first: str, second: str) -> float:
    lighter, darker = sorted((relative_luminance(first), relative_luminance(second)), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def readable_text(background: str, light: str = "#FFFFFF", dark: str = "#101010") -> str:
    """Pick whichever of ``light``/``dark`` reads better on ``background``."""
    return light if contrast_ratio(background, light) >= contrast_ratio(background, dark) else dark


def hsl_shift(color: str, lightness: float | None = None, saturation: float | None = None) -> str:
    red, green, blue = (c / 255 for c in hex_to_rgb(color))
    hue, lum, sat = colorsys.rgb_to_hls(red, green, blue)
    if lightness is not None:
        lum = max(0.0, min(1.0, lightness))
    if saturation is not None:
        sat = max(0.0, min(1.0, saturation))
    return rgb_to_hex(tuple(c * 255 for c in colorsys.hls_to_rgb(hue, lum, sat)))  # type: ignore[arg-type]


# ---------------------------------------------------------------- palette


@dataclass(frozen=True)
class Palette:
    background: str
    panel: str
    surface: str
    text: str
    text_dim: str
    accent: str
    gold: str
    border: str

    def __post_init__(self) -> None:
        for role in PALETTE_ROLES:
            value = getattr(self, role)
            if not is_hex(value):
                raise ValueError(f"{role} is not a #RRGGBB colour: {value!r}")
            object.__setattr__(self, role, value.upper())

    def as_dict(self) -> dict[str, str]:
        return {role: getattr(self, role) for role in PALETTE_ROLES}

    def with_role(self, role: str, value: str) -> "Palette":
        if role not in PALETTE_ROLES:
            raise KeyError(role)
        return replace(self, **{role: value})

    @classmethod
    def from_dict(cls, data: dict[str, str]) -> "Palette":
        missing = [role for role in PALETTE_ROLES if role not in data]
        if missing:
            raise ValueError(f"palette is missing {', '.join(missing)}")
        return cls(**{role: data[role] for role in PALETTE_ROLES})

    def contrast_problems(self, minimum: float = 4.5) -> list[str]:
        problems = []
        checks = {
            "text on background": (self.text, self.background),
            "text on panel": (self.text, self.panel),
            "dim text on background": (self.text_dim, self.background),
        }
        for label, (foreground, background) in checks.items():
            ratio = contrast_ratio(foreground, background)
            if ratio < minimum:
                problems.append(f"{label} is {ratio:.1f}:1, below {minimum:g}:1")
        return problems

    def is_dark(self) -> bool:
        return relative_luminance(self.background) < 0.35


# ---------------------------------------------------------------- presets


@dataclass(frozen=True)
class Preset:
    slug: str
    name: str
    tagline: str
    dark: bool
    wallpaper: str
    palette: Palette

    @property
    def scheme_id(self) -> str:
        return f"samurai-{self.slug}"

    def as_dict(self) -> dict:
        return {
            "slug": self.slug,
            "name": self.name,
            "tagline": self.tagline,
            "dark": self.dark,
            "wallpaper": self.wallpaper,
            "palette": self.palette.as_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Preset":
        slug = data.get("slug")
        if not isinstance(slug, str) or not SCHEME_ID_RE.match(slug):
            raise ValueError(f"invalid slug: {slug!r}")
        name = data.get("name")
        if not isinstance(name, str) or not name.strip() or len(name) > 64:
            raise ValueError(f"{slug}: name must be 1-64 characters")
        return cls(
            slug=slug,
            name=name.strip(),
            tagline=str(data.get("tagline", "")),
            dark=bool(data.get("dark", True)),
            wallpaper=str(data.get("wallpaper", "")),
            palette=Palette.from_dict(data.get("palette", {})),
        )


def load_presets(paths: Paths | None = None) -> list[Preset]:
    paths = paths or core_paths()
    document = json.loads((paths.hub / "presets.json").read_text(encoding="utf-8"))
    if document.get("schema") != 1:
        raise ValueError("presets.json: unsupported schema")
    presets = [Preset.from_dict(item) for item in document.get("presets", [])]
    if not presets:
        raise ValueError("presets.json: no presets")
    slugs = [preset.slug for preset in presets]
    if len(set(slugs)) != len(slugs):
        raise ValueError("presets.json: duplicate slugs")
    return presets


def load_preset(slug: str, presets: list[Preset]) -> Preset:
    for preset in presets:
        if preset.slug == slug:
            return preset
    raise KeyError(slug)


# ---------------------------------------------------------------- KDE schemes


def render_scheme(scheme_id: str, title: str, palette: Palette) -> str:
    """Render a KDE ``.colors`` file for a palette.

    The section/key set mirrors the committed Kuro and Shiro schemes, which are
    known to load in Plasma 6; adding a key Plasma does not know is harmless,
    omitting one it does want is not.
    """
    if not SCHEME_ID_RE.match(scheme_id):
        raise ValueError(f"invalid scheme id: {scheme_id!r}")

    background = palette.background
    window_alt = mix(background, palette.surface, 0.55)
    button_alt = mix(palette.surface, background, 0.45)
    selection_text = readable_text(palette.accent)
    selection_alt = scale(palette.accent, 0.72)
    positive = "#6AA84F" if palette.is_dark() else "#2E7D32"
    negative = "#DA4453" if palette.is_dark() else "#B3261E"

    def section(name: str, rows: list[tuple[str, str]]) -> str:
        body = "\n".join(f"{key}={value}" for key, value in rows)
        return f"[{name}]\n{body}\n"

    def window_rows(bg: str, alt: str) -> list[tuple[str, str]]:
        return [
            ("BackgroundNormal", rgb_csv(bg)),
            ("BackgroundAlternate", rgb_csv(alt)),
            ("ForegroundNormal", rgb_csv(palette.text)),
            ("ForegroundInactive", rgb_csv(palette.text_dim)),
            ("ForegroundActive", rgb_csv(palette.accent)),
            ("ForegroundLink", rgb_csv(palette.gold)),
            ("ForegroundVisited", rgb_csv(palette.accent)),
            ("ForegroundNegative", rgb_csv(negative)),
            ("ForegroundNeutral", rgb_csv(palette.gold)),
            ("ForegroundPositive", rgb_csv(positive)),
            ("DecorationFocus", rgb_csv(palette.accent)),
            ("DecorationHover", rgb_csv(palette.gold)),
        ]

    def selection_rows() -> list[tuple[str, str]]:
        return [
            ("BackgroundNormal", rgb_csv(palette.accent)),
            ("BackgroundAlternate", rgb_csv(selection_alt)),
            ("ForegroundNormal", rgb_csv(selection_text)),
            ("ForegroundInactive", rgb_csv(palette.text)),
            ("ForegroundActive", rgb_csv(selection_text)),
            ("ForegroundLink", rgb_csv(selection_text)),
            ("ForegroundVisited", rgb_csv(palette.text)),
            ("ForegroundNegative", rgb_csv("#FFC8C8")),
            ("ForegroundNeutral", rgb_csv(palette.text)),
            ("ForegroundPositive", rgb_csv("#D2FFD2")),
            ("DecorationFocus", rgb_csv(selection_text)),
            ("DecorationHover", rgb_csv(selection_text)),
        ]

    parts = [
        "[General]\n"
        f"ColorScheme={scheme_id}\n"
        f"Name={title}\n"
        "shadeSortColumn=true\n",
        section("Colors:Window", window_rows(background, window_alt)),
        section("Colors:View", window_rows(background, window_alt)),
        section("Colors:Button", window_rows(palette.surface, button_alt)),
        section("Colors:Selection", selection_rows()),
        section("Colors:Tooltip", window_rows(palette.surface, palette.panel)),
        section("Colors:Complementary", window_rows(palette.panel, palette.surface)),
        section("Colors:Header", window_rows(palette.panel, palette.surface)),
        section(
            "WM",
            [
                ("activeBackground", rgb_csv(palette.panel)),
                ("activeForeground", rgb_csv(palette.text)),
                ("activeBlend", rgb_csv(palette.surface)),
                ("inactiveBackground", rgb_csv(background)),
                ("inactiveForeground", rgb_csv(palette.text_dim)),
                ("inactiveBlend", rgb_csv(mix(background, palette.panel, 0.5))),
            ],
        ),
    ]
    return "\n".join(parts)


def rgb_csv(color: str) -> str:
    return ",".join(str(value) for value in hex_to_rgb(color))


REQUIRED_SECTIONS = (
    "General",
    "Colors:Window",
    "Colors:View",
    "Colors:Button",
    "Colors:Selection",
    "Colors:Tooltip",
    "Colors:Complementary",
)


def scheme_problems(text: str, expected_id: str) -> list[str]:
    """Return what is wrong with a rendered scheme; empty means usable."""
    parser = configparser.ConfigParser()
    try:
        parser.read_string(text)
    except configparser.Error as error:
        return [f"not a valid INI document: {error}"]
    problems = []
    if not parser.has_section("General"):
        return ["missing [General]"]
    if parser["General"].get("ColorScheme") != expected_id:
        problems.append(
            f"[General] ColorScheme is {parser['General'].get('ColorScheme')!r}, expected {expected_id!r}"
        )
    for section_name in REQUIRED_SECTIONS:
        if not parser.has_section(section_name):
            problems.append(f"missing [{section_name}]")
    for section_name in parser.sections():
        for key, value in parser[section_name].items():
            if key in {"ColorScheme", "Name"} or section_name == "General":
                continue
            if not re.fullmatch(r"\d{1,3},\d{1,3},\d{1,3}", value):
                problems.append(f"[{section_name}] {key}={value!r} is not R,G,B")
    return problems


def write_user_scheme(paths: Paths, scheme_id: str, text: str) -> Path:
    paths.user_schemes.mkdir(parents=True, exist_ok=True)
    target = paths.user_schemes / f"{scheme_id}.colors"
    target.write_text(text, encoding="utf-8", newline="\n")
    return target


def theme_scheme_text(paths: Paths, slug: str) -> str | None:
    """The committed scheme for a preset, if the theme folder ships one."""
    candidate = paths.themes / slug / f"samurai-{slug}.colors"
    if candidate.is_file():
        return candidate.read_text(encoding="utf-8")
    return None


def available_schemes(paths: Paths) -> list[str]:
    if not paths.themes.is_dir():
        return []
    found = []
    for directory in sorted(paths.themes.iterdir()):
        if directory.is_dir() and (directory / f"samurai-{directory.name}.colors").is_file():
            found.append(directory.name)
    return found


# ---------------------------------------------------------------- process helpers


def run(command: list[str], timeout: float = 20.0) -> tuple[bool, str]:
    """Run a helper, returning (ok, output). Never raises."""
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError:
        return False, f"{command[0]} is not installed"
    except subprocess.TimeoutExpired:
        return False, f"{command[0]} did not answer within {timeout:g}s"
    except OSError as error:
        return False, f"{command[0]} could not be started: {error}"
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode == 0, output.strip()


def apply_scheme(scheme_id: str, timeout: float = 25.0) -> tuple[bool, str]:
    ok, output = run(["plasma-apply-colorscheme", scheme_id], timeout=timeout)
    if ok:
        return True, f"Applied {scheme_id}"
    if "not found" in output or output.startswith("plasma-apply-colorscheme is not installed"):
        return False, "plasma-apply-colorscheme is not available; the scheme will be used at next login"
    return False, output or f"plasma-apply-colorscheme could not apply {scheme_id}"


def current_scheme() -> str | None:
    ok, output = run(["kreadconfig6", "--file", "kdeglobals", "--group", "KDE", "--key", "ColorScheme"])
    if ok and output:
        return output.strip().splitlines()[0]
    return None


def read_config(*args: str) -> str | None:
    ok, output = run(["kreadconfig6", *args])
    if ok and output:
        return output.strip().splitlines()[0]
    return None


def write_config(value: str, *args: str) -> tuple[bool, str]:
    return run(["kwriteconfig6", *args, value])


# ---------------------------------------------------------------- wallpapers


@dataclass(frozen=True)
class Wallpaper:
    stem: str
    path: Path
    title: str
    category: str
    tags: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        return self.title or self.stem


def wallpaper_metadata(paths: Paths) -> dict[str, dict]:
    try:
        document = json.loads((paths.hub / "wallpapers.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return document.get("wallpapers", {})


def list_wallpapers(paths: Paths | None = None) -> list[Wallpaper]:
    paths = paths or core_paths()
    metadata = wallpaper_metadata(paths)
    wallpapers = []
    seen = set()
    for directory in (paths.wallpapers, paths.user_wallpapers):
        if not directory or not directory.is_dir():
            continue
        for path in sorted(directory.iterdir()):
            if path.suffix.lower() not in {".jpg", ".jpeg", ".png"} or not path.is_file():
                continue
            if path.stem in seen:
                continue
            seen.add(path.stem)
            entry = metadata.get(path.name, {})
            wallpapers.append(
                Wallpaper(
                    stem=path.stem,
                    path=path,
                    title=str(entry.get("title") or path.stem.replace("-", " ").title()),
                    category=str(entry.get("category") or "Unsorted"),
                    tags=tuple(entry.get("tags") or ()),
                )
            )
    return wallpapers


def categories(wallpapers: list[Wallpaper]) -> list[str]:
    seen = sorted({wallpaper.category for wallpaper in wallpapers})
    return ["All"] + seen


def find_wallpaper(paths: Paths, name: str) -> Wallpaper | None:
    stem = Path(name).stem
    for wallpaper in list_wallpapers(paths):
        if wallpaper.stem == stem:
            return wallpaper
    return None


def _js_string(value: str) -> str:
    return json.dumps(value)


def wallpaper_script(default_uri: str | None, per_screen: dict[int, str] | None = None) -> str:
    """Build a plasmashell script that sets the image wallpaper.

    ``per_screen`` maps a screen index to a file URI; screens not listed fall
    back to ``default_uri``. The script is the same API Plasma's own
    plasma-apply-wallpaperimage uses.
    """
    targets = {str(screen): uri for screen, uri in (per_screen or {}).items()}
    lines = [f"var targets = {json.dumps(targets)};"]
    if default_uri:
        lines.append(f"var fallback = {_js_string(default_uri)};")
    else:
        lines.append("var fallback = undefined;")
    lines += [
        "for (var key in desktops()) {",
        "    var d = desktops()[key];",
        "    var uri = targets.hasOwnProperty(String(d.screen)) ? targets[String(d.screen)] : fallback;",
        "    if (uri === undefined) continue;",
        "    d.wallpaperPlugin = 'org.kde.image';",
        "    d.currentConfigGroup = ['Wallpaper', 'org.kde.image', 'General'];",
        "    d.writeConfig('Image', uri);",
        "    d.writeConfig('FillMode', 2);",
        "}",
    ]
    return "\n".join(lines)


def _plasma_eval(script: str, timeout: float = 120.0) -> bool:
    # A single quote would break out of the D-Bus argument, and a wallpaper path
    # is user-controlled once imports are allowed.
    if "'" in script:
        return False
    if shutil.which("dbus-send"):
        ok, _ = run(
            [
                "dbus-send",
                "--session",
                "--print-reply",
                f"--reply-timeout={int(timeout * 1000)}",
                "--dest=org.kde.plasmashell",
                "/PlasmaShell",
                "org.kde.PlasmaShell.evaluateScript",
                f"string:{script}",
            ],
            timeout=timeout,
        )
        if ok:
            return True
    if shutil.which("gdbus"):
        ok, _ = run(
            [
                "gdbus",
                "call",
                "--session",
                "--dest",
                "org.kde.plasmashell",
                "--object-path",
                "/PlasmaShell",
                "--method",
                "org.kde.PlasmaShell.evaluateScript",
                script,
            ],
            timeout=timeout,
        )
        if ok:
            return True
    return False


def apply_wallpaper(
    path: Path | str,
    per_screen: dict[int, Path | str] | None = None,
    timeout: float = 120.0,
) -> tuple[bool, str]:
    """Apply a wallpaper to every screen, or to the screens named in ``per_screen``."""
    target = Path(path)
    if not target.is_file():
        return False, f"{target.name} does not exist"
    uris = {screen: f"file://{Path(image)}" for screen, image in (per_screen or {}).items()}
    script = wallpaper_script(f"file://{target}", uris)
    if "'" in str(target) or any("'" in str(image) for image in (per_screen or {}).values()):
        return False, "wallpaper paths containing a single quote are not supported"
    if _plasma_eval(script, timeout=timeout):
        return True, f"Applied {target.name}"
    # Older Plasma builds answer the stock tool more reliably than a script.
    if shutil.which("plasma-apply-wallpaperimage"):
        ok, output = run(["plasma-apply-wallpaperimage", str(target)], timeout=timeout)
        if ok:
            return True, f"Applied {target.name}"
        return False, output or "the wallpaper could not be applied"
    return False, "plasmashell did not answer, so the wallpaper was not changed"


def apply_lockscreen_wallpaper(path: Path | str) -> tuple[bool, str]:
    """Set the lock screen image through kscreenlockerrc."""
    target = Path(path)
    if not target.is_file():
        return False, f"{target.name} does not exist"
    ok, output = write_config(
        f"file://{target}",
        "--file",
        "kscreenlockerrc",
        "--group",
        "Greeter",
        "--group",
        "Wallpaper",
        "--group",
        "org.kde.image",
        "--group",
        "General",
        "--key",
        "Image",
    )
    if not ok:
        return False, output or "the lock screen settings could not be written"
    write_config(
        "org.kde.image",
        "--file",
        "kscreenlockerrc",
        "--group",
        "Greeter",
        "--group",
        "Wallpaper",
        "--key",
        "Plugin",
    )
    return True, f"Lock screen wallpaper set to {target.name}"


# ---------------------------------------------------------------- accent extraction


def uses_pillow() -> bool:
    try:
        import PIL  # noqa: F401
    except Exception:
        return False
    return True


def _cache_path(paths: Paths, image: Path) -> Path:
    try:
        stamp = int(image.stat().st_mtime)
    except OSError:
        stamp = 0
    return paths.cache / f"accent-{image.stem}-{stamp}.json"


def extract_accent(paths: Paths, image: Path | str) -> str | None:
    """Pick a usable accent colour from a wallpaper, cached by mtime."""
    image = Path(image)
    cache_file = _cache_path(paths, image)
    try:
        cached = json.loads(cache_file.read_text(encoding="utf-8"))
        if is_hex(cached.get("accent")):
            return cached["accent"]
    except (OSError, ValueError):
        pass

    try:
        from PIL import Image
    except Exception:
        return None

    try:
        with Image.open(image) as source:
            sample = source.convert("RGB").resize((160, 90))
    except Exception:
        return None

    try:
        quantized = sample.quantize(colors=12, method=Image.Quantize.MEDIANCUT)
        palette = quantized.getpalette() or []
        counts = quantized.getcolors(maxcolors=160 * 90) or []
    except Exception:
        return None

    best: tuple[float, str] | None = None
    for count, index in counts:
        red, green, blue = palette[index * 3 : index * 3 + 3]
        hue, lum, sat = colorsys.rgb_to_hls(red / 255, green / 255, blue / 255)
        if lum < 0.12 or lum > 0.88 or sat < 0.18:
            continue
        score = count * (0.4 + sat) * (1.0 - abs(lum - 0.55))
        if best is None or score > best[0]:
            best = (score, rgb_to_hex((red, green, blue)))
    if best is None:
        return None

    accent = hsl_shift(best[1], lightness=0.55 if relative_luminance(best[1]) < 0.25 else 0.45,
                       saturation=None)
    if not is_hex(accent):
        return None
    try:
        cache_file.parent.mkdir(parents=True, exist_ok=True)
        cache_file.write_text(json.dumps({"accent": accent}), encoding="utf-8")
    except OSError:
        pass
    return accent


def palette_from_wallpaper(palette: Palette, accent: str) -> Palette:
    """Retarget a palette's accent (and its gold) onto a wallpaper-derived hue."""
    if not is_hex(accent):
        return palette
    gold = mix(accent, "#F2E3C0" if palette.is_dark() else "#6B4E24", 0.55)
    return palette.with_role("accent", accent.upper()).with_role("gold", gold.upper())


# ---------------------------------------------------------------- recommendations


CATEGORY_HINTS = {
    "kuro": ("Icons", "Characters"),
    "shiro": ("Landscapes", "Characters"),
    "ronin": ("Landscapes", "Neon"),
    "blood-moon": ("Crimson", "Characters"),
    "moonlight": ("Landscapes", "Icons"),
    "cyber-samurai": ("Neon", "Characters"),
    "sakura": ("Landscapes", "Icons"),
    "sunset-blade": ("Crimson", "Landscapes"),
}


def recommend_wallpapers(paths: Paths, preset: Preset, limit: int = 4) -> list[Wallpaper]:
    """Rank wallpapers for a preset: its own default first, then by mood."""
    wallpapers = list_wallpapers(paths)
    if not wallpapers:
        return []
    hints = CATEGORY_HINTS.get(preset.slug, ())

    def score(wallpaper: Wallpaper) -> tuple[int, float]:
        points = 0
        if wallpaper.stem == preset.wallpaper:
            points += 100
        if wallpaper.category in hints:
            points += 20 - 5 * hints.index(wallpaper.category)
        if preset.dark and ("night" in wallpaper.tags or "moon" in wallpaper.tags):
            points += 4
        if not preset.dark and ("paper" in wallpaper.tags or "ink" in wallpaper.tags):
            points += 4
        if preset.slug in wallpaper.tags:
            points += 10
        return points, 0.0

    ranked = sorted(wallpapers, key=score, reverse=True)
    return ranked[: max(1, limit)]


# ---------------------------------------------------------------- theme packages


def _validate_member(info: zipfile.ZipInfo) -> None:
    name = info.filename
    if "\\" in name:
        raise InvalidPackage(f"package member {name!r} uses a backslash")
    if name.startswith("/") or name.startswith("../") or "/../" in name or name == "..":
        raise InvalidPackage(f"package member {name!r} escapes the package")
    if name.endswith("/"):
        raise InvalidPackage(f"package member {name!r} is a directory entry")
    if name not in PACKAGE_MEMBERS:
        raise InvalidPackage(f"package member {name!r} is not a theme file")
    mode = info.external_attr >> 16
    if mode & 0o170000 == 0o120000:
        raise InvalidPackage(f"package member {name!r} is a symbolic link")
    if mode & 0o111:
        raise InvalidPackage(f"package member {name!r} is executable")


def inspect_package(path: Path | str) -> dict:
    """Validate a theme package without extracting it.

    Returns the manifest dict. Raises InvalidPackage with a user-facing reason.
    Nothing in the archive is executed, and no member outside the allowlist is
    ever written to disk.
    """
    path = Path(path)
    if not zipfile.is_zipfile(path):
        raise InvalidPackage(f"{path.name} is not a theme package (expected a .zip file)")
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        if not members:
            raise InvalidPackage("the package is empty")
        if len(members) > PACKAGE_MAX_MEMBERS:
            raise InvalidPackage(f"the package has {len(members)} files; a theme has at most {PACKAGE_MAX_MEMBERS}")
        total = sum(info.file_size for info in members)
        if total > PACKAGE_MAX_BYTES:
            raise InvalidPackage(f"the package is {total // (1024 * 1024)} MiB; the limit is {PACKAGE_MAX_BYTES // (1024 * 1024)} MiB")
        names = set()
        for info in members:
            _validate_member(info)
            if info.filename in names:
                raise InvalidPackage(f"the package contains {info.filename!r} twice")
            names.add(info.filename)
        if "theme.json" not in names:
            raise InvalidPackage("the package has no theme.json")
        raw = archive.read("theme.json")
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as error:
        raise InvalidPackage(f"theme.json is not valid UTF-8 JSON: {error}") from error
    if not isinstance(manifest, dict) or manifest.get("schema") != 1:
        raise InvalidPackage("theme.json must be an object with \"schema\": 1")
    try:
        preset = Preset.from_dict(manifest)
    except ValueError as error:
        raise InvalidPackage(str(error)) from error
    return preset.as_dict()


def export_package(
    destination: Path | str,
    preset: Preset,
    suggested_wallpaper: Path | None = None,
) -> Path:
    """Write a shareable theme package. Never includes anything executable."""
    destination = Path(destination)
    if destination.suffix.lower() != ".zip":
        destination = destination.with_suffix(".zip")
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = dict(preset.as_dict())
    manifest["schema"] = 1
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("theme.json", json.dumps(manifest, indent=2) + "\n")
        archive.writestr(
            "README.txt",
            "Samurai Linux theme package\n"
            f"Name: {preset.name}\n"
            "\n"
            "Import it in Samurai Customization Hub > Share > Import theme.\n"
            "The package contains colours and, optionally, one wallpaper. It\n"
            "contains no scripts and nothing in it is executed.\n",
        )
        if suggested_wallpaper and Path(suggested_wallpaper).is_file():
            suffix = Path(suggested_wallpaper).suffix.lower()
            if suffix in {".jpg", ".jpeg", ".png"}:
                archive.write(
                    suggested_wallpaper,
                    "wallpaper.png" if suffix == ".png" else "wallpaper.jpg",
                )
    return destination


def import_package(paths: Paths, source: Path | str) -> Path:
    """Import a validated package into the user's theme library."""
    manifest = inspect_package(source)
    slug = manifest["slug"]
    if slug in {"kuro", "shiro"}:
        raise InvalidPackage(f"{slug} is a built-in theme; rename the package to import it")
    target_dir = paths.library / slug
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "theme.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8", newline="\n"
    )
    with zipfile.ZipFile(source) as archive:
        for member in ("wallpaper.jpg", "wallpaper.png"):
            try:
                data = archive.read(member)
            except KeyError:
                continue
            (target_dir / member).write_bytes(data)
    return target_dir


def library_themes(paths: Paths) -> list[Preset]:
    themes = []
    if not paths.library.is_dir():
        return themes
    for manifest in sorted(paths.library.glob("*/theme.json")):
        try:
            themes.append(Preset.from_dict(json.loads(manifest.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return themes


# ---------------------------------------------------------------- rotation


def rotation_units(exec_line: str, minutes: int, shuffle: bool) -> tuple[str, str]:
    """systemd user service+timer that advances the wallpaper on a schedule."""
    minutes = max(1, min(24 * 60, int(minutes)))
    command = f"{exec_line} --next-wallpaper"
    if shuffle:
        command += " --shuffle"
    service = (
        "[Unit]\n"
        "Description=Rotate the Samurai wallpaper\n"
        "After=graphical-session.target\n"
        "\n"
        "[Service]\n"
        "Type=oneshot\n"
        f"ExecStart={command}\n"
    )
    timer = (
        "[Unit]\n"
        f"Description=Rotate the Samurai wallpaper every {minutes} minutes\n"
        "\n"
        "[Timer]\n"
        "OnBootSec=2min\n"
        f"OnUnitActiveSec={minutes}min\n"
        "AccuracySec=30s\n"
        "\n"
        "[Install]\n"
        "WantedBy=timers.target\n"
    )
    return service, timer


def install_rotation(paths: Paths, exec_line: str, minutes: int, shuffle: bool) -> tuple[bool, str]:
    service, timer = rotation_units(exec_line, minutes, shuffle)
    paths.rotation_dir.mkdir(parents=True, exist_ok=True)
    (paths.rotation_dir / ROTATION_SERVICE).write_text(service, encoding="utf-8", newline="\n")
    (paths.rotation_dir / ROTATION_TIMER).write_text(timer, encoding="utf-8", newline="\n")
    ok, output = run(["systemctl", "--user", "daemon-reload"], timeout=15)
    if not ok:
        return False, output or "systemctl --user is not available; the timer was written but not enabled"
    ok, output = run(["systemctl", "--user", "enable", "--now", ROTATION_TIMER], timeout=20)
    if not ok:
        return False, output or "the rotation timer could not be enabled"
    return True, f"Wallpaper rotation every {minutes} minutes"


def disable_rotation(paths: Paths) -> tuple[bool, str]:
    if shutil.which("systemctl"):
        run(["systemctl", "--user", "disable", "--now", ROTATION_TIMER], timeout=20)
    for name in (ROTATION_SERVICE, ROTATION_TIMER):
        try:
            (paths.rotation_dir / name).unlink()
        except OSError:
            pass
    return True, "Wallpaper rotation disabled"


def rotation_enabled(paths: Paths) -> bool:
    return (paths.rotation_dir / ROTATION_TIMER).is_file()


def next_wallpaper(paths: Paths, shuffle: bool = True) -> tuple[bool, str]:
    wallpapers = list_wallpapers(paths)
    if not wallpapers:
        return False, "no wallpapers are installed"
    state = load_state(paths)
    last = state.get("last_wallpaper")
    candidates = [wallpaper for wallpaper in wallpapers if wallpaper.stem != last] or wallpapers
    choice = random.choice(candidates) if shuffle else candidates[0]
    ok, message = apply_wallpaper(choice.path)
    if ok:
        state["last_wallpaper"] = choice.stem
        save_state(paths, state)
    return ok, message


# ---------------------------------------------------------------- desktop settings


def installed_icon_themes(roots: tuple[Path, ...] = (Path("/usr/share/icons"), Path.home() / ".local/share/icons")) -> list[str]:
    themes = set()
    for root in roots:
        if not root.is_dir():
            continue
        for entry in root.iterdir():
            if entry.is_dir() and (entry / "index.theme").is_file():
                themes.add(entry.name)
    return sorted(themes)


def installed_decorations() -> list[str]:
    names = set()
    for root in (Path("/usr/share/kwin/decorations"), Path("/usr/share/aurorae/themes")):
        if not root.is_dir():
            continue
        for entry in root.iterdir():
            if entry.is_dir():
                names.add(entry.name)
    return sorted(names)


#: Keys the Desktop page writes, with the KDE file/group each one belongs to.
DESKTOP_SETTINGS = {
    "icon_theme": ("kdeglobals", ("Icons",), "Theme"),
    "decoration": ("kwinrc", ("org.kde.kdecoration2",), "theme"),
    "animations": ("kdeglobals", ("KDE",), "AnimationDurationFactor"),
    "blur": ("kwinrc", ("Effect-kwin_blur",), "Enabled"),
    "blur_strength": ("kwinrc", ("Effect-kwin_blur",), "blurStrength"),
}


def apply_desktop_settings(settings: dict[str, object]) -> list[str]:
    """Write the desktop appearance knobs KDE exposes, returning what happened."""
    messages = []
    for key, value in settings.items():
        if key not in DESKTOP_SETTINGS:
            messages.append(f"{key}: not a setting this Hub writes")
            continue
        file_name, groups, config_key = DESKTOP_SETTINGS[key]
        args = ["--file", file_name]
        for group in groups:
            args += ["--group", group]
        args += ["--key", config_key]
        if isinstance(value, bool):
            text = "true" if value else "false"
        else:
            text = str(value)
        ok, output = write_config(text, *args)
        messages.append(f"{key}: {'set' if ok else 'failed: ' + output}")
    if "icon_theme" in settings:
        run(["kbuildsycoca6", "--noincremental"], timeout=30)
    if {"decoration", "blur", "blur_strength"} & set(settings):
        run(["qdbus", "org.kde.KWin", "/KWin", "reconfigure"], timeout=10)
    return messages


def panel_script(height: int | None, alignment: str | None, hiding: str | None) -> str:
    lines = ["for (var i = 0; i < panels().length; i++) {", "    var p = panels()[i];"]
    if height is not None:
        lines.append(f"    p.height = {max(24, min(120, int(height)))};")
    if alignment in {"left", "center", "right"}:
        lines.append(f"    p.alignment = {_js_string(alignment)};")
    if hiding in {"none", "autohide", "dodge"}:
        lines.append(f"    p.hiding = {_js_string(hiding)};")
    lines.append("}")
    return "\n".join(lines)


def apply_panel(height: int | None, alignment: str | None, hiding: str | None) -> tuple[bool, str]:
    if _plasma_eval(panel_script(height, alignment, hiding), timeout=30):
        return True, "Panel updated"
    return False, "plasmashell did not answer, so the panel was left unchanged"


# ---------------------------------------------------------------- state


DEFAULT_STATE = {
    "preset": "kuro",
    "favourites": [],
    "last_wallpaper": None,
    "rotation_minutes": 60,
    "rotation_shuffle": True,
    "custom_palette": None,
    "custom_name": "Custom",
}


def load_state(paths: Paths) -> dict:
    state = dict(DEFAULT_STATE)
    try:
        stored = json.loads(paths.state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return state
    if isinstance(stored, dict):
        state.update({key: value for key, value in stored.items() if key in DEFAULT_STATE})
    if not isinstance(state.get("favourites"), list):
        state["favourites"] = []
    return state


def save_state(paths: Paths, state: dict) -> None:
    paths.config.mkdir(parents=True, exist_ok=True)
    payload = {key: state.get(key, default) for key, default in DEFAULT_STATE.items()}
    try:
        paths.state_file.write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8", newline="\n"
        )
    except OSError:
        pass


def write_theme_marker(paths: Paths, slug: str) -> None:
    """Keep samurai-theme's first-login default in step with the Hub."""
    paths.config.mkdir(parents=True, exist_ok=True)
    try:
        (paths.config / "theme").write_text(slug + "\n", encoding="utf-8", newline="\n")
    except OSError:
        pass


# ---------------------------------------------------------------- CLI entry

USAGE = """\
Samurai Customization Hub

Usage: samurai-customize [option]

With no option the Hub window opens.

  --next-wallpaper   Apply the next (or a random) wallpaper; used by the
                     rotation timer
  --shuffle          With --next-wallpaper, pick a random wallpaper
  --apply-theme      Apply a built-in theme (colours + its wallpaper) as the
                     Hub would, on the session bus the caller is in
  --apply-wallpaper  Apply one installed wallpaper by name
  --list-presets     Print the built-in themes
  --list-wallpapers  Print the installed wallpapers
  --verify           Check that the installed data files are consistent
  --help             Show this text
"""


def apply_preset(paths: Paths, slug: str) -> tuple[bool, list[str]]:
    """Apply a built-in theme exactly as the window does, without a window.

    Used by the Plasma check that runs inside a live session: it must exercise
    the Hub's own apply path, not a copy of it, or the check proves nothing.
    """
    notes: list[str] = []
    presets = load_presets(paths)
    try:
        preset = load_preset(slug, presets)
    except KeyError:
        return False, [f"no theme called {slug!r}; have: " + ", ".join(p.slug for p in presets)]
    text = theme_scheme_text(paths, preset.slug)
    if text is None:
        return False, [f"{preset.slug}: no committed scheme in {paths.themes}"]
    problems = scheme_problems(text, preset.scheme_id)
    if problems:
        return False, [f"{preset.slug}: {problem}" for problem in problems]
    ok, message = apply_scheme(preset.scheme_id)
    notes.append(f"scheme {preset.scheme_id}: {message}")
    if not ok:
        return False, notes
    if preset.wallpaper:
        wallpaper = find_wallpaper(paths, preset.wallpaper)
        if wallpaper is None:
            return False, notes + [f"{preset.slug}: wallpaper {preset.wallpaper!r} is not installed"]
        ok, message = apply_wallpaper(wallpaper.path)
        notes.append(f"wallpaper {wallpaper.stem}: {message}")
        if not ok:
            return False, notes
    write_theme_marker(paths, preset.slug)
    return True, notes


def main(argv: list[str]) -> int:
    paths = core_paths()
    args = list(argv)
    if "--help" in args or "-h" in args:
        print(USAGE.rstrip())
        return 0
    if "--list-presets" in args:
        for preset in load_presets(paths):
            print(f"{preset.slug}\t{preset.name}\t{preset.tagline}")
        return 0
    if "--list-wallpapers" in args:
        for wallpaper in list_wallpapers(paths):
            print(f"{wallpaper.stem}\t{wallpaper.category}\t{wallpaper.label}")
        return 0
    if "--next-wallpaper" in args:
        ok, message = next_wallpaper(paths, shuffle="--shuffle" in args)
        print(message)
        return 0 if ok else 1
    if "--verify" in args:
        return verify(paths)
    for flag in ("--apply-theme", "--apply-wallpaper"):
        if flag not in args:
            continue
        index = args.index(flag)
        value = args[index + 1] if index + 1 < len(args) else ""
        if not value or value.startswith("--"):
            print(f"{flag} needs a name", file=sys.stderr)
            return 2
        if flag == "--apply-theme":
            ok, notes = apply_preset(paths, value)
        else:
            wallpaper = find_wallpaper(paths, value)
            if wallpaper is None:
                print(f"no wallpaper called {value!r}", file=sys.stderr)
                return 1
            ok, message = apply_wallpaper(wallpaper.path)
            notes, ok = [f"wallpaper {wallpaper.stem}: {message}"], ok
        print("\n".join(notes))
        return 0 if ok else 1
    print(USAGE.rstrip(), file=sys.stderr)
    return 2


def verify(paths: Paths) -> int:
    """Read-only consistency check used by the smoke suite and by --verify."""
    problems = []
    presets = load_presets(paths)
    for preset in presets:
        text = theme_scheme_text(paths, preset.slug)
        if text is None:
            problems.append(f"{preset.slug}: no committed scheme in {paths.themes}")
            continue
        for problem in scheme_problems(text, preset.scheme_id):
            problems.append(f"{preset.slug}: {problem}")
        if preset.wallpaper and find_wallpaper(paths, preset.wallpaper) is None:
            problems.append(f"{preset.slug}: recommended wallpaper {preset.wallpaper!r} is not installed")
        for problem in preset.palette.contrast_problems():
            problems.append(f"{preset.slug}: {problem}")
    for wallpaper in list_wallpapers(paths):
        # A picture the user imported has no metadata by design; only the
        # shipped set is expected to be described in wallpapers.json.
        if wallpaper.category == "Unsorted" and wallpaper.path.parent == paths.wallpapers:
            problems.append(f"{wallpaper.path.name}: no metadata in wallpapers.json")
    for problem in problems:
        print(problem)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
