# Samurai Linux - Known Limitations

## Build and Release
- **Hosted ISO build works** - `.github/workflows/build-iso-hosted.yml` builds
  the ISO on an ephemeral GitHub runner inside a privileged Debian trixie
  container. Local builds still require a Linux host with 50 GB+ free disk (100
  GB recommended), 4 GB+ RAM (8 GB recommended), and root for `chroot`.
- **The scripted installer test has not passed yet** - `build/install-test.py`
  drives the real Calamares UI in QEMU, boots the written disk, and now also
  boots into Plasma to check theming and GameMode/MangoHud. The ISO builds and
  boots to SDDM in CI, but no install-test run has been green end to end, so
  partitioning, bootloader installation, and first boot on real hardware are
  still unverified. The furthest a run has got is Calamares passing every
  mandatory requirement check (storage, RAM, root, partitions) and building its
  partition job queue - run 41989352435, which then lost the display server; no
  run has reached the execution page where jobs write to disk. See
  [`../../build/README.md`](../../build/README.md).
- **No release tag or GitHub Release yet** - signing works and is proved in CI
  (the ISO, its checksum and the package manifest are signed, and the install
  test verifies them against the key committed under `samurai/keys/`), but no
  tag will be pushed until an install-test run is green end to end.
- **Boot menu and splash are Samurai, the kernel boot logo is not** - the
  isolinux and GRUB menus use the Samurai title, entry labels, selection colour
  and splash images, but the Debian logo drawn by the live kernel and the GRUB
  labels on an installed system still come from Debian's packages.
- **No first-boot wizard** - the installed system boots to SDDM; theme, AI, and
  gaming setup are manual commands after login.
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
- **NVIDIA drivers manual** - NVIDIA setup is documented but not auto-configured
- **Not all Windows games work** - Proton compatibility varies by title;
  check ProtonDB before expecting a given game to run
- **Overclocking excluded** - risky performance tweaks are optional and not
  enabled by default

## Performance
- **No published numbers** - the boot time, idle memory and CPU figures this file
  used to imply were never measured, and the ones in `docs/performance.md`'s
  predecessors have been removed. `build/measure-performance.sh` is now the only
  source, and it runs inside the install test's desktop phase; until a green run
  attaches a `performance.txt`, nothing may be quoted.
- **No power profiles** - neither `power-profiles-daemon` nor TLP is in the image,
  so the balanced / performance / power-saving modes described in the brief do not
  exist. Nothing switches CPU governor or scheduler policy.
- **No compositor or resource-limit tuning** - the image ships no `kwinrc`, and
  there is no AI inference memory cap or load-triggered pause, because there is no
  AI runtime to cap.

## Desktop and Themes
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
- **The live image's X11 session does not come up through autologin** - two
  defects were found while working around the one above. Run 41993508779
  restarted SDDM into `plasmax11` and got a session with no compositor at all,
  because Debian ships `kwin_x11` in its own `kwin-x11` package and the image had
  never installed it; the package is in the manifest now and `verify-iso.sh`
  refuses an image that offers a session whose compositor is missing. Run
  42105485811 had the compositor installed and still showed an Xorg with nothing
  running on it, which read as "the session's program never ran". Run
  42112234958 said what actually happened: the SDDM journal shows
  `Starting Wayland user session` even with `/etc/sddm.conf.d/99-install-test-x11.conf`
  holding `Session=plasmax11`, that session exited after ten seconds, and SDDM
  then put a display on VT3 for **its own greeter**. The X11 desktop two cycles
  went looking for was a login screen with nobody logged in, and the autologin
  request had been ignored - which of the image's own configuration outvoted the
  drop-in is still not established. The install test now prints the live image's
  SDDM configuration before it touches anything, comments out every `Session=`
  key it finds, and writes its request to a drop-in named to sort last. If that
  still produces no compositor the harness starts the session file's own `Exec=`
  itself, kills the greeter first so it cannot draw over the installer, and says
  in the log that it did: a green run may therefore show an X11 desktop the
  harness logged into rather than one the image reached on its own, and the
  ignored-autologin defect remains open in the image.

## Scope
- **Single architecture** - x86_64 only; no ARM or RISC-V builds
- **KDE Plasma only** - no alternate desktop environments offered
- **Debian Trixie base** - tied to Debian's package set, cadence and security
  support. Extra tooling arrives by installing Debian packages through
  `samurai-profile`, not by packaging anything for a Samurai repository, because
  no such repository exists (see "Package management and updates" above).
