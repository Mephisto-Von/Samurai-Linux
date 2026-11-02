# Samurai KDE Plasma and Design System

> **Legacy design document.** There is no `samurai-kuro` or `samurai-shiro`
> command; the theme switcher is `samurai-theme set kuro|shiro|auto`. The colour
> schemes and wallpapers described here do ship, but the custom icon set and
> cursor theme below are still planned and are not in the image. See
> [`../docs/desktop-and-themes.md`](../docs/desktop-and-themes.md).

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
- **Wallpaper**: Original Samurai-themed wallpaper with restrained brushstroke design
- **Icons**: Custom Samurai icon set with crimson accent highlights
- **Terminal colors**: Kuro scheme with `#F2EEE5` text on `#111214` background
- **Login screen**: Branded with Samurai logo and Kuro theme
- **Cursor**: Samurai-themed cursor with crimson accent

### Configuration
```bash
# Apply and persist Kuro
samurai-theme kuro

# Or use the explicit form
samurai-theme set kuro
```

Installed scheme: `~/.local/share/color-schemes/samurai-kuro.colors`.

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
- **Wallpaper**: Original Samurai-themed light wallpaper
- **Icons**: Light Samurai icon set with vermilion accents
- **Terminal colors**: Shiro scheme with `#242321` text on `#F5F0E6` background
- **Login screen**: Branded with Samurai logo and Shiro theme
- **Cursor**: Samurai-themed cursor with vermilion accent

### Configuration
```bash
# Apply and persist Shiro
samurai-theme shiro

# Or use the explicit form
samurai-theme set shiro
```

Installed scheme: `~/.local/share/color-schemes/samurai-shiro.colors`.

## Theme Selector
- **Persistent theme selector** in System Settings -> Appearance
- **Auto mode** - follows system color scheme (light/dark automatic)
- **Contrast testing** - ensured for both themes
- **Focus states** - visible focus indicators in both themes
- **Application behavior** - tested in both themes

## Installation Artwork
- **Original wallpapers** - Japanese Samurai motifs
- **Logos** - Samurai crest with Japanese calligraphy elements
- **Icons** - Consistent design language across themes
- **Terminal colors** - Both Kuro and Shiro schemes
- **Login branding** - Samurai logo at login screen
- **Installer artwork** - Branded installer with theme preview
