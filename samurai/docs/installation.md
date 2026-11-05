# Samurai Linux Installation and First Boot

## Bootable ISO

The ISO is built with Debian `live-build`; see
[`build/README.md`](../../build/README.md). The old direct `xorriso` recipe was
invalid (it produced a data ISO, not a bootable live image).

Build locally:

```bash
sudo bash build/build.sh
bash build/verify-iso.sh dist/samurai-linux-*-amd64.iso
bash build/qemu-test.sh dist/samurai-linux-*-amd64.iso --gui
```

Or download the `samurai-linux-iso` artifact from the latest
**Build ISO (hosted)** run in GitHub Actions. The workflow builds the ISO,
verifies the live rootfs, and boots it headlessly in QEMU before uploading it.

Artifacts are kept for 7 days, so there is no permanently downloadable ISO yet -
that is what the first tagged release provides. The last pipeline that passed
every stage was run `40346119925` (commit `028a2ac`, 2026-10-26):

- `samurai-linux-2026.10.26-amd64.iso`
- 2,547,646,464 bytes (2.37 GiB)
- SHA-256 `811ae8b19f4f0296dc485014f5772c587a7e531f6269553e30b0bd4caf9b7555`

It predates the installer fixes made since, so treat it as a reference, not as
the release image.

Verify the download and write it to a USB drive:

```bash
cd dist
sha256sum -c ./*.sha256

# Replace /dev/sdX with the USB device, not a partition. This erases it.
sudo dd if=samurai-linux-*-amd64.iso of=/dev/sdX bs=4M status=progress oflag=sync
```

The hybrid ISO boots on BIOS and UEFI systems with Secure Boot **disabled**.
Nothing in this repository signs a bootloader: `grub-efi-amd64-bin` produces an
unsigned EFI binary and no `shim` package is installed, so neither the live
image nor the installed system satisfies Secure Boot's chain of trust. Booting
with Secure Boot on requires either turning it off in firmware or enrolling your
own key and signing the bootloader yourself.

## Live Session

1. Boot the USB drive and choose **Samurai Linux Live (amd64)** in the boot
   menu (it auto-selects after 5 seconds). The menu title, entry labels and
   isolinux/GRUB splashes are Samurai artwork; the boot logo is still Debian's
   because the live kernel/initramfs come from Debian's `live-boot` package.
2. The live session logs in as `samurai` (password `live` if asked). `sudo` is
   passwordless in the live session.
3. Connect to the network from the Plasma system tray if you want to install
   updates or packages after installation.
4. Start the installer from the desktop icon or the application menu entry
   **Install Samurai Linux**.
5. If the whole desktop disappears a moment after you pick a target disk on the
   partition page, the Plasma Wayland compositor has crashed and taken the
   installer's display with it. Reboot, and if SDDM shows its login screen
   instead of logging in again, choose **Plasma (X11)** in the session menu
   before starting the installer. Images built before the `kwin-x11` package
   was added list that session but cannot start it, since the X11 compositor
   was not installed; current builds ship it. This has been seen only in QEMU
   virtual machines so far (see [`known-limitations.md`](known-limitations.md)),
   not on physical hardware.

## Installation with Calamares

The ISO ships Calamares with Debian's live-install configuration and Samurai
branding. The steps are:

1. **Welcome** - choose language and continue.
2. **Location** - choose region and time zone.
3. **Keyboard** - choose the keyboard layout.
4. **Partitions** - use guided partitioning for a simple install, or manual
   partitioning for a custom layout. Guided partitioning creates an unencrypted
   layout; encrypted installs depend on Debian's packaged Calamares configuration
   plus `cryptsetup` being present, and **no Samurai test has ever installed to
   an encrypted disk**, so full-disk encryption is not a supported path today.
5. **Users** - create the account you will use after installation.
6. **Summary** - review the disk changes. This is the last point before the
   installer writes to disk.
7. **Install** - Calamares unpacks the live filesystem, installs GRUB for BIOS
   or UEFI, and creates the initial initramfs.
8. **Finish** - reboot and remove the USB drive.

Notes:

- Use a disk of at least 20 GB. Back up existing data first.
- The installer copies the live rootfs, so the installed system contains the
  same KDE desktop, Samurai CLIs, themes, and installer packages.
- A network connection is not required for the base installation.
- On UEFI systems, the installer creates an EFI system partition and installs
  GRUB there. On BIOS systems it installs GRUB to the disk's boot area.
- If the machine has Secure Boot enabled and the installed system does not boot,
  disable Secure Boot in firmware or sign the installed GRUB with your own keys.

The current installer is Debian's packaged Calamares configuration plus Samurai
branding. Samurai-specific package-profile screens and a custom first-boot
wizard are not implemented.

## First Boot

After rebooting into the installed system, log in with the account created by
Calamares. There is no first-boot wizard; finish setup from a terminal:

```bash
# Update the installed system
sudo apt update
sudo apt full-upgrade

# Theme: Kuro is applied for new users; switch or inspect it with:
samurai-theme list
samurai-theme status
samurai-theme set kuro
samurai-theme set shiro

# AI assistant: install Ollama separately, then choose a model
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.2:3b
samurai-ai set-default llama3.2:3b
samurai-ai chat "Hello"

# Gaming: install the profile, then launch Steam
samurai-gaming install-profile
samurai-gaming steam
```

Steam, Ollama, and AI models are not included in the ISO. Large models need
enough RAM or a compatible GPU; run `samurai-ai check-compatibility` for
guidance.

## Current Limitations

- The ISO builds, passes content verification, and boots to SDDM in CI, and
  `build/install-test.py` drives the real Calamares installer to a virtual disk,
  but no automated install run has been green end to end yet. Partitioning,
  bootloader installation, and first boot on real hardware remain unverified.
- The bootloader splash and menus use Samurai artwork; the kernel boot logo and
  the installed system's GRUB menu labels still come from Debian's packages.
  Calamares and the desktop use Samurai branding.
- There is no Samurai first-boot wizard and no `samurai-install` command.
- The installed system's bootloader is not Secure Boot signed.
- There is no signed APT repository; the installed system uses Debian's
  repositories plus the packages copied from the live image.
- Wallpapers and color schemes ship with the image; icon sets and cursors are
  not yet packaged as a complete Samurai theme.

## Recovery

- **Live ISO rescue** - boot the ISO, mount the installed partitions, and
  `chroot` into the system to repair packages or the bootloader.
- **Reinstall GRUB from the live session** - mount the target root and EFI
  system partition, bind-mount `/dev`, `/proc`, and `/sys`, then run
  `grub-install` and `update-grub` inside the chroot.
- **Backups** - keep a separate backup of `/home` and any custom configuration
  before reinstalling or repartitioning.
