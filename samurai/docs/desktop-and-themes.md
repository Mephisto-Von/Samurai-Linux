# Samurai KDE Plasma and Design System

> **Implemented today:** Kuro and Shiro KDE color schemes (`.colors`) installed
> system-wide and per user, a full set of Samurai wallpapers in
> `/usr/share/backgrounds/samurai/`, the branded Calamares welcome slide, and
> the `samurai-theme` CLI that applies colors *and* wallpaper (with an optional
> systemd user timer). Custom icon sets, cursors, and login-screen branding are
> **not included yet**.

## Kuro - Dark Theme

### Color Palette
- **Background**: `#111214`
- **Panels**: `#1B1D20`
- **Elevated surfaces**: `#25272B`
- **Primary text**: `#F2EEE5`
- **Secondary text**: `#B8B4AC`
- **Crimson**: `#B52832`
- **Gold**: `#B89A59`
- **Borders**: `#383A3D`

### Visual Elements
- **Japanese Samurai motifs**: brushstroke artwork, waves, mountains, moonlight, lacquered black surfaces, crimson accents
- **Wallpaper**: `kuro.jpg` - a samurai silhouette against a full moon (dark, high contrast)
- **Icons**: Custom Samurai icon set with crimson accent highlights (planned)
- **Terminal colors**: Kuro scheme with `#F2EEE5` text on `#111214` background
- **Login screen**: Branded with Samurai logo and Kuro theme (planned)
- **Cursor**: Samurai-themed cursor with crimson accent (planned)

### Configuration
```bash
# Apply and persist Kuro
samurai-theme kuro

# Or use the explicit form
samurai-theme set kuro

# List themes and show the current selection
samurai-theme list
samurai-theme status

# Manage wallpapers
samurai-theme wallpaper        # list all wallpapers
samurai-theme wallpaper kuro   # apply a specific wallpaper
samurai-theme random          # apply a random wallpaper
```

The scheme is installed as `~/.local/share/color-schemes/samurai-kuro.colors`
and activated with `plasma-apply-colorscheme samurai-kuro`. The system copy lives
in `/usr/share/color-schemes/samurai-kuro.colors`.

## Shiro - Light Theme

### Color Palette
- **Background**: `#F5F0E6`
- **Panels**: `#ECE5D8`
- **Elevated surfaces**: `#FFFDF8`
- **Primary text**: `#242321`
- **Secondary text**: `#686258`
- **Vermilion**: `#B52832`
- **Gold**: `#96733B`
- **Borders**: `#D8D0C2`

### Visual Elements
- **Japanese Samurai motifs**: same restrained aesthetic as Kuro
- **Wallpaper**: `shiro.jpg` - an ink-wash landscape with a vermilion sun on rice paper
- **Icons**: Light Samurai icon set with vermilion accents (planned)
- **Terminal colors**: Shiro scheme with `#242321` text on `#F5F0E6` background
- **Login screen**: Branded with Samurai logo and Shiro theme (planned)
- **Cursor**: Samurai-themed cursor with vermilion accent (planned)

### Configuration
```bash
# Apply and persist Shiro
samurai-theme shiro

# Or use the explicit form
samurai-theme set shiro
```

The scheme is installed as `~/.local/share/color-schemes/samurai-shiro.colors`
and activated with `plasma-apply-colorscheme samurai-shiro`.

## Wallpapers

The image ships 22 wallpapers in `/usr/share/backgrounds/samurai/`, generated
from the Samurai art collection with `build/make-wallpapers.py`:

- `kuro.jpg` and `shiro.jpg` are the theme defaults. `samurai-theme` applies
  the one matching the selected theme with `plasma-apply-wallpaperimage`, and
  the Plasma autostart entry runs `samurai-theme default` on first login, so the
  live session and freshly installed systems both start with Kuro colors and
  the moonlit wallpaper.
- Portrait sources are placed, fit to full height, over a blurred copy of
  themselves; landscape sources are scaled and centre-cropped to 1920x1080, so
  nothing is distorted.
- The other 20 wallpapers (`crimson-moon.jpg`, `moonlit-tree.jpg`, ...) are
  available in the Plasma wallpaper picker.

Regenerate after changing the source art (requires Pillow):

```bash
python3 build/make-wallpapers.py
```

The generated files are committed, so ISO builds do not need Pillow.

## Theme Selector
- **Persistent theme selector** in System Settings -> Appearance
- **CLI selector** - `samurai-theme kuro|shiro|list|status|wallpaper|random`
- **Auto mode** - `samurai-theme auto` switches at 06:00 and 18:00
- **Persistent auto mode** - `samurai-theme install-auto` installs a systemd user timer
- **Wallpapers** - Samurai art collection (22 pieces) from the project, auto-applied per theme or manually selectable
- **Contrast targets** - palette values are chosen for WCAG AA body text, but
  no contrast ratio has been measured; see
  [`testing.md`](testing.md) for what the automated suite does and does not
  assert
- **Focus states** - crimson/gold focus indicators defined in both schemes, not
  yet checked for visibility
- **Application behavior** - still needs testing against real KDE applications

## Installation Artwork
- **Wallpapers** - 22 Samurai wallpapers shipped in the ISO (see above)
- **Logos** - Samurai crest with Japanese calligraphy elements
- **Icons** - Consistent design language across themes (icon set pending)
- **Terminal colors** - Both Kuro and Shiro schemes
- **Login branding** - Samurai logo at login screen (pending)
- **Installer artwork** - Calamares uses the Samurai branding component with a
  branded welcome slide (`/etc/calamares/branding/samurai/slide1.png`)
