# Samurai Linux - Known Limitations

## Build and Release
- **Hosted ISO build works** - `.github/workflows/build-iso-hosted.yml` builds
  the ISO on an ephemeral GitHub runner inside a privileged Debian trixie
  container. Local builds still require a Linux host with 50 GB+ free disk (100
  GB recommended), 4 GB+ RAM (8 GB recommended), and root for `chroot`.
- **The scripted installer test is green in CI, not yet on hardware** -
  `build/install-test.py` drives the real Calamares UI in QEMU, boots the
  written disk, and also boots into Plasma to check theming and
  GameMode/MangoHud. Install-test run `42392182476` completed green at commit
  `89ed5cf` against the ISO built by run `42296526484` (commit `d865e89`): it
  partitioned a blank disk, installed the bootloader, booted the installed
  system, read the security state back, and verified the Plasma desktop. That
  is a virtual machine with no GPU, no guest network and one disk;
  partitioning on real hardware, encrypted installs, Secure Boot and first
  boot on physical machines remain manual checks. See
  [`../../build/README.md`](../../build/README.md).
- **The first release is `v2026.11`** - the ISO, its checksum and the package
  manifest are signed, and the install test verifies them against the key
  committed under `samurai/keys/`. `scripts/release-gate.sh` refuses a tag
  without a green install test at that commit. The image is 2.9 GB, so GitHub
  publishes it in parts with `REASSEMBLE.txt`; a part on its own is not
  bootable. See [`release-process.md`](release-process.md).
- **Boot menu and splash are Samurai, the kernel boot logo is not** - the
  isolinux and GRUB menus use the Samurai title, entry labels, selection colour
  and splash images, but the Debian logo drawn by the live kernel and the GRUB
  labels on an installed system still come from Debian's packages.
- **No first-boot wizard** - the installed system boots to SDDM. The autostart
  entry applies the Kuro scheme and its wallpaper, but AI and gaming setup are
  manual commands after login.
- **Secure Boot is not supported at all** - the image installs
  `grub-efi-amd64-bin`, which produces an unsigned EFI binary, and no `shim`
  package is present, so neither the live ISO nor the installed system boots with
  Secure Boot enabled. Turn it off in firmware, or enrol your own key and sign the
  bootloader; there is no signing workflow here to hand one over.
- **Artifact retention** - hosted ISO artifacts expire after 7 days.

## Package management and updates
- **No Samurai APT repository** - every package comes from Debian. Adding a
  project archive would mean running a signing infrastructure, a mirror and a
  rebuild cadence, none of which exists here; a rebranded base is not a reason
  to invent one.
- **Profile installs are not exercised at runtime** - `samurai-profile` resolves
  every profile with `apt-get install -s` at build time (a name that has left
  Debian fails the ISO), but the install test runs its guest with no network, so
  downloading and installing a real profile, and removing it again, have not
  been executed on an installed system.
- **Recovery restores files, not a system state** - `samurai-recovery snapshot`,
  `verify` and `restore-etc` do run on the installed system in CI. It is not a
  filesystem snapshot: it captures no `/home`, cannot downgrade a package
  upgraded in place, and whole-system rollback still needs the installer or a
  snapshotting filesystem, which this image does not ship.
- **Unattended upgrades are verified as policy, not as a patch event** - the
  installed system's archive, origin list and timers are read back, and the
  build fails unless the security archive authenticates, but no test has yet
  watched an actual CVE fix arrive and get applied.

## AI Runtime

- **Model size limited by RAM** - larger models (12B+) need 16 GB+ system RAM
  or a compatible GPU; `samurai-ai check-compatibility` advises what will run
- **Ollama installed separately** - model management depends on Ollama, which is
  not baked into the live ISO; install it after first boot (there is no setup wizard)
- **Cloud chat not implemented** - the CLI stores provider credentials, but chat
  currently targets local Ollama only; no data is sent to cloud providers
- **Speech input/output not implemented** - these remain planned features

## Gaming
- **Steam needs Debian's `non-free` archive** - the image is built from
  `main contrib non-free-firmware`, and the Steam client itself lives in
  `non-free`, so `samurai-gaming install-profile` cannot install Steam on the
  shipped sources. It says so and stops instead of letting apt fail; enabling
  `non-free` is a user decision this project does not make silently.
- **No game has been run or measured** - the desktop phase proves GameMode and
  MangoHUD are installed and that the MangoHUD interposer preloads in a live
  session. No Proton title has been launched, no frame rate has been recorded,
  and QEMU's software renderer could not produce one that means anything.
- **No controller has been tested** - HID devices work the way Debian makes them
  work; nothing in this project sets one up and no test touches one.
- **Anti-cheat limitations** - some titles (kernel-level anti-cheat) do not
  work under Proton regardless of configuration
- **NVIDIA drivers manual** - enabling Debian's `non-free` archive and installing
  `nvidia-driver` is documented in [`gaming.md`](gaming.md) but nothing detects
  the GPU or configures it, and no NVIDIA system has been tested
- **Not all Windows games work** - Proton compatibility varies by title;
  check ProtonDB before expecting a given game to run
- **Overclocking excluded** - risky performance tweaks are optional and not
  enabled by default

## Performance
- **No published numbers** - the boot time, idle memory and CPU figures this file
  used to imply were never measured, and the ones in earlier revisions of
  [`performance.md`](performance.md) have been removed.
  `build/measure-performance.sh` is now the only source, and it runs inside the
  install test's desktop phase, so a green run
  carries a `performance.txt` (run `42392182476` did). Those numbers describe a
  QEMU guest with no GPU, so they are not a baseline for real hardware and are
  not quoted in the documentation.
- **No power profiles** - neither `power-profiles-daemon` nor TLP is in the image,
  so the balanced / performance / power-saving modes described in the brief do not
  exist. Nothing switches CPU governor or scheduler policy.
- **No compositor or resource-limit tuning** - the image ships no `kwinrc`, and
  there is no AI inference memory cap or load-triggered pause, because there is no
  AI runtime to cap.

## Desktop and Themes
- **The System Settings page is a front end, not a second editor** - System
  Settings hosts compiled KCM plugins, so `kcm_samurai` (a small KDE 6
  plugin built by `build/build.sh` from `samurai/kcm/`) drives the same
  headless commands as the window. Applying colours from the page saves a
  `samurai-custom-<theme>` scheme rather than editing the built-in one; the
  wallpapers, live preview, effects and theme library still live in the
  window, which the page opens
- **No theme marketplace** - theme packages export and import as `.zip`
  files, and the importer validates them before writing anything, but there is
  no hosted catalog, account or upload: sharing means sending someone a file
- **The Hub's Plasma calls are unproven on a real session** - the window, the
  colour maths, the scheme renderer and the package validator were exercised;
  applying a scheme, wallpaper, lock screen, panel geometry or KWin effect
  through this window was not, because the build and test machines have no
  Plasma session. The tools it calls are the ones `samurai-theme` already uses
  in a green install test
- **The 4K wallpapers are regenerated, not captured at 4K** - the thumbnails
  in `Samurai Walls/` are 236-760 px wide; a neural 4x upscale
  (`build/upscale-nn.py`) synthesises line work and texture, and the
  generator then finishes each frame. What looks like detail is the
  model's interpretation, not recovered pixels - which is visible
  if you compare the gallery against the thumbnails, and is why the
  upscaled intermediates are not committed
- **Icons and cursors are pending** - the Kuro/Shiro color schemes and 22
  Samurai wallpapers ship with the image, but the custom icon set and cursors
  are still planned
- **Plasma Wayland quirks** - some gaming overlays (MangoHUD) work best on X11
  sessions currently
- **Installing from the Wayland live session can take the desktop down** - in
  QEMU with a virtio-gpu device, three runs (41545976827, 41596964514,
  41989352435) ended the same way: Calamares logs `Updating partitioning preview
  widgets`, `kwin_wayland` then dies of SIGSEGV (coredumpctl names
  `/usr/bin/kwin_wayland`, the backtrace is in `libkwin.so.6`), the session's
  Xwayland dies with the compositor, and Calamares exits quoting `The X11
  connection broke (error 1)`. The install test now switches the live session to
  Plasma on X11 before starting Calamares and logs that it did, so what the test
  can claim is the installer on an X11 desktop - not on the Wayland session the
  live image starts by default. Nobody has reproduced the crash outside the CI
  VM, so whether it needs a software-rendered guest with no mirrorable DRM device
  or also happens on a real GPU is unknown.
- **The live image autologins into the Wayland session, and its X11 session is
  not the default** - two defects were found while working around the crash
  above. Run 41993508779 restarted SDDM into `plasmax11` and got a session with
  no compositor at all, because Debian ships `kwin_x11` in its own `kwin-x11`
  package and the image had never installed it; the package is in the manifest
  now and `verify-iso.sh` refuses an image that offers a session whose
  compositor is missing. Run 42105485811 had the compositor installed and still
  showed an Xorg with nothing running on it, which read as "the session's
  program never ran", and run 42112234958 looked as if the test's `[Autologin]`
  drop-in had been ignored outright. Run `42121878962` settled it by printing
  the live image's configuration before touching it: `/etc/sddm.conf.d` does
  not exist in the live image, and `/etc/sddm.conf` is rewritten at every boot -
  its timestamp is boot time - by `live-config` 11.0.5, which puts

  ```
  [Autologin]
  User=samurai
  Session=plasma.desktop
  ```

  there. `plasma` resolves to the session SDDM tries first, and that is the
  Wayland one; the earlier "ignored drop-in" was this file winning, not a
  precedence mystery. The install test now comments out that key, states
  `Session=plasmax11` itself and restarts SDDM, and run `42121878962` shows the
  result: `x11=yes` with `kwin_x11` running 26 seconds after the restart, with
  no help from the harness. So the live image still starts on Wayland by
  default - which is the session the crash above happens in, and a user
  following `installation.md` step 5 still has to pick **Plasma (X11)** by hand -
  and making X11 the image's own default is an open decision, not a settled
  design.

## Scope
- **Single architecture** - x86_64 only; no ARM or RISC-V builds
- **KDE Plasma only** - no alternate desktop environments offered
- **Debian Trixie base** - tied to Debian's package set, cadence and security
  support. Extra tooling arrives by installing Debian packages through
  `samurai-profile`, not by packaging anything for a Samurai repository, because
  no such repository exists (see "Package management and updates" above).
