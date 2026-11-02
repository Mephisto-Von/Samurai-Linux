# Samurai Gaming Configuration

> **Implemented today:** the image ships GameMode, MangoHUD, Mesa DRI drivers
> and Vulkan drivers. `samurai-gaming install-profile` enables i386, installs
> `steam-installer`, GameMode and MangoHUD, adds Lutris, Gamescope, winetricks
> and protontricks when the configured archives provide them, and enables
> `gamemoded` for the current user. `samurai-gaming steam|lutris` launch through
> GameMode and MangoHUD. Nothing else on this page is implemented: there is no
> automatic controller setup, no redistributable installer, no Proton toggling
> and no measured game workload.

## What ships in the image

| Component | Status | Evidence |
| --- | --- | --- |
| GameMode | installed | `gamemode` in `build/config/package-lists/samurai.list.chroot`; the install test checks `samurai-gaming status` reports `gamemoderun: installed` on a booted system |
| MangoHUD | installed | `mangohud` in the same list; the install test reads the interposer `.so` out of the package and preloads it in a live session |
| Mesa / Vulkan | installed | `libgl1-mesa-dri`, `libegl-mesa0`, `mesa-vulkan-drivers`; `glxinfo -B` must report a renderer before the desktop phase continues |
| Steam, Proton, Lutris, Gamescope, Heroic | not installed | installed only by `install-profile`, and only if the archives offer them |

## Compatibility layer

- **Steam** - installed by `install-profile` through Debian's `steam-installer`.
  The Steam client itself is in Debian's `non-free` archive, which the Samurai
  image does **not** enable; `install-profile` stops with instructions instead
  of letting apt fail on unmet dependencies.
- **Proton** - arrives with Steam and is configured by Steam, not by Samurai.
  Nothing in this project enables it for you.
- **Lutris, winetricks, protontricks** - installed by `install-profile` when the
  configured archives carry them.
- **Heroic Games Launcher** - not in Debian's archives and not installed or
  configured by anything in this repository. `samurai-gaming status` only reports
  whether the command happens to exist.

## Graphics drivers

Mesa (open-source AMD/Intel) and the Vulkan drivers ship with the image, which is
what lets KWin composite at all. NVIDIA needs Debian's `non-free` driver packages
and is documented, not automated: nothing in the image detects a GPU and installs
a proprietary driver.

## Gaming enhancers

- **GameMode** - `gamemoderun` wraps a launched game; `install-profile` tries
  `systemctl --user enable --now gamemoded` and warns if it could not.
- **MangoHud** - an overlay driven by environment variables. Inside Steam the
  documented form is `MANGOHUD=1 %command%`. The install test only proves the
  interposer loads (`MANGOHUD=1 mangohud /bin/true`), because QEMU's software
  renderer cannot produce a frame rate worth reporting.
- **Gamescope** - a nested Wayland compositor used to run games in their own
  session with scaling and VRR. Installed opportunistically by `install-profile`;
  Samurai does not configure or launch it.

## Controllers and audio

ALSA utilities, PipeWire/PulseAudio and Bluetooth KDE tooling (`bluedevil`) are in
the image, so an ordinary HID controller works the way it works on any Debian
desktop. There is no Samurai controller setup step, no mapping UI and no
calibration, and no test asserts anything about a controller.

## Commands

```bash
samurai-gaming install-profile   # Steam/GameMode/MangoHUD plus optional tools
samurai-gaming steam             # gamemoderun mangohud steam
samurai-gaming lutris            # gamemoderun mangohud lutris
samurai-gaming status            # what is actually installed right now
systemctl --user start gamemoded # GameMode daemon for this user
MANGOHUD=1 %command%             # Steam launch option for the overlay
```

## Known limits

- No game has been run and measured by this project, so there are no frame-time,
  FPS or compatibility numbers to quote.
- Anti-cheat titles and some DRM stacks do not work under Proton; this is a
  property of those games, not something Samurai can configure away.
- Overclocking and other risky performance changes are out of scope.
