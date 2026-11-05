# Samurai Linux Build Guide

The supported build path is Debian's `live-build`, driven by
[`build/build.sh`](../../build/build.sh). See
[`build/README.md`](../../build/README.md) for the operational guide.

> The previous `debootstrap` + `xorriso` recipe in this document was not
> bootable. It has been replaced; do not copy old `xorriso -as iso` commands.

## 1. Build host

| Requirement | Minimum | Recommended |
|---|---|---|
| OS | Debian 13 (Trixie) | Debian 13 |
| Architecture | x86_64 | x86_64 |
| Free disk | 50 GiB | 100 GiB |
| RAM | 4 GiB | 8 GiB |
| CPU | 2 cores | 4+ cores |

Use a native Linux filesystem (ext4/xfs/btrfs). Do not build on a Windows
filesystem mounted under WSL (`/mnt/c`, `/mnt/d`): `chroot` and maintainer
scripts require Unix permissions and device nodes.

## 2. Install build tools

```bash
sudo apt-get update
sudo apt-get install -y \
    live-build debootstrap xorriso squashfs-tools gnupg
```

`build/build.sh` refuses to start if any required tool is missing.

## 3. Configure the image

`build/auto/config` pins the image definition:

- Debian 13 `trixie`, `amd64`
- `iso-hybrid` output with BIOS and UEFI boot
- `main contrib non-free-firmware` archive areas
- live user `samurai`, hostname `samurai`
- KDE Plasma package list in `build/config/package-lists/samurai.list.chroot`

Customise packages there, and put files that should be copied verbatim into the
image under `build/config/includes.chroot/`. Chroot setup lives in
`build/config/hooks/normal/`.

## 4. Build

```bash
# Validate the host and generate config without building
bash build/build.sh --check

# Full clean build (requires root)
sudo bash build/build.sh
```

The script syncs `samurai/scripts/` and `samurai/themes/` into the live-build
include tree, runs `lb clean --purge`, builds, and copies the result to `dist/`:

```
dist/samurai-linux-YYYY.MM.DD-amd64.iso
dist/samurai-linux-YYYY.MM.DD-amd64.iso.sha256
```

`SAMURAI_MIN_DISK_GB` and `SAMURAI_MIN_RAM_GB` override the preflight limits.
They exist because a build that runs out of disk halfway through leaves a
`chroot` tree that no later run can clean up; overriding them downwards is
allowed and unwise.

### Building without a Linux host

The hosted workflow is the same `live-build` run inside a privileged
`debian:trixie` container on a GitHub runner, followed by `verify-iso.sh`, the
QEMU boot test, signing and the chained install test:

```bash
gh workflow run build-iso-hosted.yml          # then watch the Actions tab
gh run download <run-id> --name samurai-linux-iso --dir dist
```

This is the route to use from Windows, and it is not a lesser build: the image
definition, the verification gates and the signing key are the ones in this
repository. Its practical limits are that the whole build has to fit the free
disk a hosted runner offers - which is why the workflow deletes unused
toolchains first and still asks for `min_disk_gb` (default 25 GiB) - that the
artifact disappears after 7 days, and that a build is not a test: the install
test chained to it is what says whether the image installs.

### The update loop

A new image is the only way anything in the ISO changes. The loop is:

1. Edit the image definition - packages in
   `build/config/package-lists/samurai.list.chroot`, files in
   `build/config/includes.chroot/`, setup in `build/config/hooks/normal/`.
2. `bash build/build.sh --check`, then build (locally or through the workflow).
3. `bash build/verify-iso.sh dist/<iso>` - this is where a missing compositor,
   an unloadable firewall module or a broken kernel/modules pairing is caught
   without booting anything.
4. Boot it (`build/qemu-test.sh`, or a VM), then dispatch
   `install-test.yml` with that run's id.
5. Sign and, only once the install test is green at that commit, release
   (`scripts/release-gate.sh`; see
   [`release-process.md`](release-process.md)).

An **installed** system updates another way entirely: `apt`, plus
`unattended-upgrades` for `Debian:trixie-security` as configured by
`build/config/includes.chroot/etc/apt/apt.conf.d/20samurai-security`. There is
no Samurai APT repository, so package changes reach users only through a newer
ISO.

## 5. Sign the release

```bash
sudo -E SAMURAI_SIGN_KEY="<gpg-key-id>" bash build/build.sh
```

This writes an armored **detached** signature:

```bash
gpg --verify dist/samurai-linux-*.iso.sig dist/samurai-linux-*.iso
(cd dist && sha256sum -c ./*.iso.sha256)
```

## 6. Boot-test

```bash
# Headless serial check, 180 s timeout
bash build/qemu-test.sh dist/samurai-linux-*-amd64.iso

# Interactive desktop check
bash build/qemu-test.sh dist/samurai-linux-*-amd64.iso --gui
```

Pass criteria for the headless run: the serial log contains kernel or systemd
boot messages. Pass criteria for the GUI run: SDDM appears and the KDE Plasma
live session starts as user `samurai`. The 2026-10-26 hosted build (run
`40346119925`) reached `sddm.service` and a `samurai login:` prompt.

## 7. Verify the live session

Inside the VM:

```bash
samurai-theme list          # kuro, shiro
samurai-theme shiro         # applies and persists across logout
samurai-theme auto          # one-shot day/night selection
samurai-theme install-auto  # systemd user timer at 06:00 and 18:00
samurai-ai --help
samurai-gaming status
```

## 8. Release acceptance criteria

A release may ship only when every item passes or is explicitly waived with a
documented reason:

1. Bootable ISO generated and validated
2. Installation and first boot tested
3. KDE Plasma works as the primary desktop
4. Kuro and Shiro themes persist and function
5. Developer profile usable
6. Security defaults and update mechanisms documented and tested
7. AI assistant works with at least one configured model backend
8. Local AI mode works without a cloud API key
9. Cloud integrations disclose external data transmission
10. Model routing uses documented criteria and permits user overrides
11. Gaming capabilities tested on declared supported configurations
12. Performance measurements reproducible
13. Recovery and upgrade procedures documented
14. Critical known defects resolved or explicitly block release
15. Build and release instructions complete
16. Checksums and GPG signature verify against the published ISO
17. APT repository publication and upgrade path from the previous release tested

## 9. Troubleshooting

| Problem | Fix |
|---|---|
| `lb: command not found` | `sudo apt-get install live-build` |
| Disk check fails | Free space; 50 GiB is the hard minimum |
| Build fails in `/mnt/*` | Move the checkout to the Linux filesystem |
| `steam-installer` unavailable at runtime | Enable `contrib` and run `sudo apt-get update` |
| Theme does not change immediately | Run inside a Plasma session; `plasma-apply-colorscheme` needs D-Bus |
| Scripts fail with `$'\r'` | Re-clone in Linux; `.gitattributes` enforces LF |
