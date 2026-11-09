# Samurai Customization Hub

> **Implemented:** a Qt window (`samurai-customize`) that changes the theme,
> colours, wallpapers, lock screen and the desktop effects KDE exposes, with a
> live preview and one-click apply, reachable from a `kcm_samurai` module in
> System Settings -> Personalization. **Not implemented:** a hosted theme
> marketplace and custom icon or cursor sets (the image still ships none).
> Wallpapers are 3840x2160.

The Hub exists so that changing the desktop does not require a terminal. Its
whole job is to be the friendly front end to things the image already does:
KDE color schemes, Plasma wallpaper scripting and `kwriteconfig6`.

## Opening it

| Where | How |
|---|---|
| Application launcher | **Samurai Customization Hub** |
| Desktop icon | On a new account, created from `/etc/skel/Desktop` |
| Terminal | `samurai-customize` |
| System Settings | **Personalization -> Samurai Customization Hub** |
| Without a display | `samurai-customize --core --verify`, `--core --list-presets` |

Plasma's System Settings only hosts KCM modules, which are compiled C++/QML
plugins, and a Python application cannot register itself there. So the image
builds `kcm_samurai` from `samurai/kcm/` (`kcmutils_add_qml_kcm`): a small
plugin whose page says where the Hub's features live and has a button that
opens the window. It is a discovery entry, not a second theme editor; the
theme itself is applied by the schemes it installs in
`/usr/share/color-schemes` and by the Hub you get from the button.

## Themes

Eight built-in themes ship. Each is a complete appearance - palette plus a
matching wallpaper - and each is a real KDE color scheme installed in
`/usr/share/color-schemes`, so it also appears in System Settings → Colours.

| Theme | Mood | Default wallpaper |
|---|---|---|
| Kuro | Ink black, crimson, antique gold | `kuro.jpg` |
| Shiro | Ivory paper, charcoal, muted vermilion | `shiro.jpg` |
| Ronin | Charcoal, worn steel, moonlight blue | `misty-forest.jpg` |
| Blood Moon | Black lacquer, deep crimson | `crimson-moon.jpg` |
| Moonlight | Midnight blue, silver | `moonlit-tree.jpg` |
| Cyber Samurai | Navy, restrained neon cyan | `neon-city-rain.jpg` |
| Sakura | Ivory, blossom pink, charcoal | `moonlit-antlers.jpg` |
| Sunset Blade | Ember orange, dark red, black | `sunset-roof.jpg` |

Selecting a theme previews it immediately. The Hub applies the theme's colours
*and* its wallpaper; `samurai-theme set <theme>` applies the colours and the
same-named wallpaper (`kuro.jpg`, `shiro.jpg`) only, which is what it has always
done. The palette lives in
`samurai/desktop/hub/presets.json`, and `samurai/desktop/hub/render-schemes.py`
writes the committed `.colors` files from it, so the theme you see in the Hub
and the theme Plasma installs cannot drift apart. Editing the schemes by hand
fails `render-schemes.py --check`, which the smoke suite runs.

## Colours

Every role is independently editable: background, panels, surfaces, text,
secondary text, accent, highlight and borders. Three things make this safe:

- **Live preview.** Changes re-apply a throwaway `samurai-preview` scheme, so
  the desktop and the Hub window itself restyle while you pick. **Apply** writes
  the real scheme; **Cancel** re-applies the one that was in use when the Hub
  opened.
- **Undo and redo.** Ctrl+Z / Ctrl+Shift+Z, plus the header buttons.
- **Readability warnings.** The Hub computes WCAG contrast for text on
  background, text on panels and secondary text, and says so when a choice drops
  below 4.5:1. It warns rather than blocks: a deliberate low-contrast theme is a
  choice, but it should be a warned one.

**Accent from selected wallpaper** quantizes the image with Pillow and retargets
the accent and highlight onto a colour that actually occurs in it.

Applying an untouched built-in theme activates the scheme the image already
ships instead of writing a copy of it into the user's directory. A modified
palette is written to `~/.local/share/color-schemes/`.

## Wallpapers

All 22 wallpapers are 3840x2160, generated from the project art by
`build/make-wallpapers.py` after a neural 4x upscale of the thumbnails
(see `build/upscale-nn.py`). They appear in a gallery with real previews,
categorised (Characters, Crimson, Icons, Landscapes, Neon), with favourites,
double-click for a full-screen preview, one-click selection and your own
pictures: **Add image…**, or
just drag a JPEG or PNG onto the window. Your pictures are copied to
`~/.local/share/samurai/wallpapers` (a normal user cannot write to
`/usr/share`, and an upgrade should not have to worry about them) and listed
after the shipped set.

- **Multi-monitor.** Each screen can take a different wallpaper, or all screens
  can share one. This uses the same Plasma scripting API as the single-screen
  case: the script maps each desktop's `screen` to an image.
- **Rotation.** A systemd user timer runs `samurai-customize --next-wallpaper`
  on a schedule you choose (1 minute to 24 hours, optionally in random order).
  Turning the Hub's rotation off removes the units, so no timer is left behind.
- **Lock screen.** Writes the image into `kscreenlockerrc` for the Plasma lock
  screen; it does not touch SDDM's login background.

## Desktop

The Desktop page writes settings through `kwriteconfig6` and tells KWin to
reconfigure, so the change lands in the running session:

| Setting | Where it goes |
|---|---|
| Icon theme | `kdeglobals` `[Icons] Theme`, then `kbuildsycoca6` |
| Window decoration | `kwinrc` `[org.kde.kdecoration2] theme` |
| Animation speed | `kdeglobals` `[KDE] AnimationDurationFactor` |
| Blur on/off and strength | `kwinrc` `[Effect-kwin_blur]` |
| Panel height, alignment, visibility | Plasma scripting (`panels()`) |

Icon and decoration lists are read from what the system actually has installed,
not from a hardcoded list that could name something the image does not ship.

## Sharing themes

A theme package is a `.zip` containing `theme.json`, optionally one wallpaper
(`wallpaper.jpg` or `wallpaper.png`), and optionally `README.txt`. Nothing else.
Export writes one; import validates before writing a byte:

- only allowlisted member names, no directories, at most 16 entries and 32 MiB;
- no absolute paths, no `..` segments, no backslashes, no symbolic links, no
  executable bits, no duplicate entries;
- `theme.json` must be schema 1 with a valid slug and all eight palette roles as
  `#RRGGBB`;
- the built-in themes cannot be overwritten by an import.

Nothing in a package is executed. There is **no remote marketplace**: no server
is operated for this project, so "share" means exporting a file and sending it,
and "browse" means the themes on your own machine. The Hub is honest about that
rather than shipping a download button that fails.

## What is not built

- **The System Settings entry opens the window; it does not replace it.**
  See "Opening it" above. If the module is built without `cmake` (a warning in
  `build/build.sh`), the entry is absent and `build/verify-iso.sh` fails.
- **No marketplace backend.** The validation and packaging exist; the catalog,
  accounts and upload do not.
- **Icons and cursors.** The image ships no Samurai icon or cursor set, so those
  pages list the system's own themes.
- **Login screen branding.** SDDM's background is not changed by the Hub.
- **Panel layouts.** Height, alignment and auto-hide are applied; adding,
  removing or rearranging panel widgets is not.

## How it is put together

| File | Role |
|---|---|
| `samurai/desktop/hub/samurai_customize.py` | The window (PySide6). Drawing and wiring only. |
| `samurai/desktop/hub/samurai_hub_core.py` | All logic, no Qt: palettes, scheme rendering, packages, rotation, state. |
| `samurai/desktop/hub/presets.json` | The eight themes: the single source of colour truth. |
| `samurai/desktop/hub/wallpapers.json` | Titles, categories and tags for the 22 wallpapers. |
| `samurai/desktop/hub/render-schemes.py` | Renders the committed `.colors` files. |
| `samurai/scripts/samurai-customize` | Launcher; answers the non-GUI commands without importing Qt. |
| `samurai/desktop/samurai-customize.desktop` | Menu entry, and the desktop icon for new accounts. |

`build/build.sh` stages `samurai/desktop/hub/` into `/usr/share/samurai/hub` and
installs the launcher; the image installs `python3-pyside6.qtwidgets` and
`python3-pil`. Keeping the Qt imports out of the core means the rotation timer
and `--verify` run on a session with no display, and the suite can test the
logic without a GUI toolkit.

## Verifying it

```bash
samurai-customize --core --verify            # presets, schemes and wallpapers agree
samurai-customize --core --list-presets      # what the image installs
python3 samurai/desktop/hub/render-schemes.py --check
bash tests/smoke.sh
```

The smoke suite checks the 4K wallpaper sizes, that the committed schemes are
exactly what `presets.json` renders, and that the package validator accepts a
real export while refusing a script, a traversal path, a symlink and an
executable bit.

## What has not been tested

The window, the colour maths, the scheme renderer and the package validator were
exercised; the **Plasma interactions were not**, because the build and test
machines have no Plasma session. Applying a scheme, wallpaper, lock screen,
panel geometry and KWin effects calls the same tools `samurai-theme` already
uses in a green install test, but this window driving them has only been read,
not run, on a live desktop. Treat the first session with it as a test, and
`samurai-customize --core --verify` plus `samurai-theme status` as the fallback.
