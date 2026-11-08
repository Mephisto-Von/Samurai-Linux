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

Artifacts are kept for 7 days, so a workflow artifact is not a permanent
download. The first tagged release, `v2026.11`, is: it publishes the image the
green install test installed, split into parts because GitHub refuses a release
asset above 2 GiB. Download every part, reassemble with `cat`, check the signed
checksum, then verify the GPG signature; `REASSEMBLE.txt` in the release repeats
the commands, and a part on its own is not bootable. See
[`release-process.md`](release-process.md).

An older reference image, kept only because it is the last pipeline that passed
every stage before the installer fixes, was run `40346119925` (commit `028a2ac`,
2026-10-26):

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

## Running the ISO in a virtual machine

This is how the image is exercised for a demo, and it is also how every
automated claim about it was produced - in QEMU. **No Samurai test or build has
ever run on VMware**, so a VMware session is new evidence rather than a
confirmation, and what it shows should be written down.

Get the current image (artifacts live 7 days):

```bash
gh run download <build-run-id> --name samurai-linux-iso --dir dist
cd dist && sha256sum -c ./*.iso.sha256 && gpg --verify ./*.iso.sig
```

Those two commands are not ceremony: install-test.yml performs the same
verification before it installs anything, and an ISO that was not built by the
run it claims is not the image a green test would have proven.

VM settings the image's own configuration dictates:

| Setting | Value | Why |
| --- | --- | --- |
| Firmware | UEFI **or** BIOS | the ISO is hybrid: `grub-pc-bin` and `grub-efi-amd64-bin` both ship |
| Secure Boot | **off** | nothing here signs a bootloader and no `shim` is installed |
| CD/DVD | ISO image file, connect at power on | the live system boots from the squashfs on the disc |
| Memory | 4 GB or more | Plasma, Calamares and the live rootfs share that RAM |
| Hard disk | 20 GB or more | installation.md's minimum for a real install |
| 3D acceleration | start with it on, and change only what you observed | the one documented live-session crash is `kwin_wayland` taking a SIGSEGV when Calamares paints its partition preview; that has only ever been seen with QEMU's software renderer, so VMware's path is unmeasured |
| Network | NAT is enough | outbound works; the image's nftables ruleset is `chain ingress ... policy drop`, so inbound connections are expected to fail |

What a VMware session can demonstrate without any further work: the boot menu
and splash, SDDM, the live Plasma desktop, the Kuro and Shiro themes
(`samurai-theme`), and the `samurai-*` CLIs. Booting to SDDM is verified in CI
(run `41545976827`) and branding is gated by `build/verify-iso.sh`.

A **completed** Calamares installation is demonstrated by the automated install
test, not by a hand-driven VM session: install-test run `42392182476` partitioned
a blank disk, installed the bootloader, booted the installed system and verified
it. That is a QEMU guest with no GPU and no network, so if the installer is part
of a demo on another hypervisor, rehearse it first in a throwaway VM and treat
the outcome as a result to be recorded rather than a step that is assumed to
work. The crash-and-recover notes for the live session are in the Live Session
steps above.

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
   not on physical hardware. The automated install test does not rely on the
   session menu: it switches the live session to X11 itself before launching
   Calamares, so a green run proves the installer on X11, not on the Wayland
   session the live image starts by default.

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

- The ISO builds, passes content verification, boots to SDDM in CI, and
  `build/install-test.py` drives the real Calamares installer to a virtual disk
  and boots the result; run `42392182476` completed that path green. Partitioning,
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
