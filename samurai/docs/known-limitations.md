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
  still unverified. See [`../../build/README.md`](../../build/README.md).
- **No release, no signature yet** - the repository has no tag and no GitHub
  Release. The `Sign the ISO` step needs `SAMURAI_SIGN_*` repository secrets
  before any published image can be verified.
- **Boot menu and splash are Samurai, the kernel boot logo is not** - the
  isolinux and GRUB menus use the Samurai title, entry labels, selection colour
  and splash images, but the Debian logo drawn by the live kernel and the GRUB
  labels on an installed system still come from Debian's packages.
- **No first-boot wizard** - the installed system boots to SDDM; theme, AI, and
  gaming setup are manual commands after login.
- **Installed system is not Secure Boot signed** - the live ISO uses Debian's
  signed UEFI shim, but Calamares installs unsigned GRUB by default. Disable
  Secure Boot after installation or sign the bootloader with your own keys.
- **Artifact retention** - hosted ISO artifacts expire after 7 days.

## AI Runtime
- **Model size limited by RAM** - larger models (12B+) need 16 GB+ system RAM
  or a compatible GPU; `samurai-ai check-compatibility` advises what will run
- **Ollama installed separately** - model management depends on Ollama, which is
  not baked into the live ISO; install it after first boot (there is no setup wizard)
- **Cloud chat not implemented** - the CLI stores provider credentials, but chat
  currently targets local Ollama only; no data is sent to cloud providers
- **Speech input/output not implemented** - these remain planned features

## Gaming
- **Anti-cheat limitations** - some titles (kernel-level anti-cheat) do not
  work under Proton regardless of configuration
- **NVIDIA drivers manual** - NVIDIA setup is documented but not auto-configured
- **Not all Windows games work** - Proton compatibility varies by title;
  check ProtonDB before expecting a given game to run
- **Overclocking excluded** - risky performance tweaks are optional and not
  enabled by default

## Desktop and Themes
- **Icons and cursors are pending** - the Kuro/Shiro color schemes and 22
  Samurai wallpapers ship with the image, but the custom icon set and cursors
  are still planned
- **Plasma Wayland quirks** - some gaming overlays (MangoHUD) work best on X11
  sessions currently

## Scope
- **Single architecture** - x86_64 only; no ARM or RISC-V builds
- **KDE Plasma only** - no alternate desktop environments offered
- **Debian Trixie base** - tied to Debian's package cadence; upstream packages
  must be packaged into the Samurai repository for inclusion
