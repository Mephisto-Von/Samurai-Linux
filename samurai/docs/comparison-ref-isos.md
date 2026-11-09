# Comparison against the reference ISOs in `ref/`

Read-only inventory of `kali-linux-2026-W43-installer-purple-amd64.iso`,
`ubuntu-25.04-desktop-amd64.iso` and `samurai-linux-2026.11.05-amd64.iso`
(mounted, package lists extracted with `filesystem.packages` /
`filesystem.manifest` / the live trees, 2026-11-09). The aim is: where is
Samurai weaker than the ISOs it sits beside on a user's desk, and what would
close the gap.

> Numbers are from the installed package sets, not from what a project's
> upstream defaults contain. Some absences are softer than they look — a
> `kde-standard` package pulls a lot in by recommends — but deliberate
> dependencies (something on the package list by name) are the only ones a
> Debian user can count on to survive an upgrade.

## At a glance

| | Samurai (2026.11.05 image) | Ubuntu 25.04 Desktop | Kali 2026-W43 (installer) |
|---|---|---|---|
| ISO size | 2.95 GB | 6.28 GB | 5.05 GB |
| Installed packages (manifest) | 1,951 | 1,866 | — (installer-only ISO: no live image; the `pool/` is a 3,303-package repo) |
| Kernel | Linux 6.12.115 (trixie) + 6.12.107 also shipped | Linux 6.8 (Plucky) | Debian installer kernel |
| Desktop | KDE Plasma 6.3.6, SDDM | GNOME 48, GDM3 | XFCE default live (this ISO installs from `pool/`) |
| Installer | Calamares (graphical, from the live session) | Ubiquity (desktop) / casper (live) | Debian installer: graphical, text, expert, automated, rescue, speech synthesis |
| Firmware | All of it, baked into the image (`firmware-*` all present) | Partial (community + `fwupd`) | Separate `firmware/` folder of `.deb`s on the ISO |
| Boot splash / GRUB theme | `splash.png` + `live-theme` + `theme.cfg` | Minimal | `splash.png` + `theme/` + `font.pf2` (custom Kali theme) |
| Live credentials | `samurai` user, auto-logged in for the live session | `ubuntu` user | `kali` user |
| Checksums | `sha256sum.txt` (295 files), signed `.sig` beside it when keys are set | `md5sum.txt` | `md5sum.txt` (3,649 files) + `.sig` on the release |

## Everyday desktop (what Ubuntu has and Samurai does not)

These are roles, not preferences: each row is a thing a fresh desktop user
reaches for within the first day.

| Role | Ubuntu 25.04 | Samurai |
|---|---|---|
| Office suite | LibreOffice (Writer/Calc/Impress) | — (Okular/Kate only) |
| Email | Thunderbird | — (the old image had `kmail`, dropped from the current package list) |
| Calendar/tasks | GNOME Calendar | — (old image had `korganizer`) |
| Photo manager | Shotwell | — |
| Video player | Totem | Dragon Player (old image only) |
| Torrent client | Transmission | — |
| Printing + scanning | CUPS + Simple Scan (scanner) | — |
| Backup | Déjà Dup | — (old image had `bup`) |
| Cloud-init / automated provisioning | cloud-init | — |
| Accessibility | `brltty` | — |

## Security depth (what Kali's repo offers and Samurai does not)

Kali's image is a 3,303-package repo with defined tool categories. Samurai
documented an "offensive-security variant" that adds an archive pin and a
tool list, but neither of those contains Kali-style tooling.

| Category | Kali repo | Samurai |
|---|---|---|
| Network analysis | wireshark, tshark, tcpdump, nmap, net-tools, metasploit-framework | — (nftables only) |
| Forensics & IR | autopsy, sleuthkit, yara, chkrootkit, rkhunter | — |
| Crackers & offensive | nmap, john, metasploit, burpsuite, aircrack-ng | — |
| Password helpers | kwalletmanager | kwalletmanager (via kde-standard) |
| Speech install (accessibility) | yes | — |

## What Samurai already does better (or differently)

- The firmware set (`firmware-*` for AMD/Intel/NVIDIA/Broadcom/Atheros/
  Realtek/Mediatek plus `firmware-linux-free`) is **baked in**, so USB
  Wi-Fi/Bluetooth/printers work out of the box; Ubuntu needs `fwupd` plus
  community drivers, and Kali ships firmware as separate `.deb`s to install.
- The installer is one graphical flow (Calamares) started from the live
  desktop, with the GRUB config used both for the live boot and the
  installed system — no split-brain between `ubiquity`/`casper` and the
  Debian installer.
- Theme system (8 KDE colour schemes + the Customization Hub + a System
  Settings module) — Ubuntu's and Kali's desktops don't have anything like
  it out of the box.
- The ISO is half the size of Ubuntu's despite shipping more batteries
  than it from 2025.

## Prioritised recommendations

### 1. Close the everyday gaps (highest user-visible value)
Add by name to `build/config/package-lists/samurai.list.chroot` (with a
KDE-flavoured pick per role, or the same package Ubuntu uses):

1. `libreoffice` (even metapackage `libreoffice-core` + Writer/Impress if
   size matters) — office is the single most-missed capability.
2. `thunderbird` and `korganizer` (email + calendar; both were in the old
   image and were dropped — restore deliberately or note the removal).
3. `system-config-printer` + `simple-scan` + the CUPS stack — printing and
   scanning are day-1 expectations.
4. `transmission-gtk` and a backup story (`bup` back in, or `borgbackup`).
5. `dragonplayer` (video) and `shotwell` (photos).

### 2. Decide what the security variant *is*
Either give it real tooling — a `kali-tools-*`-style list (at minimum
`nmap wireshark net-tools tcpdump john hashcat`) plus Kali's archive pin —
or drop the offline-security-toolset claim from the docs, because today the
variant carries Debian tooling, not an offensive set. Kali's speech install
and rescue/expert modes are also worth an assessment: some of that is
provided by Debian directly (rescue/expert via the Debian installer path,
which Samurai's Calamares does not use).

### 3. Clean up the image's own bloat
The old image ships **two** kernels (6.12.107 *and* 6.12.115) and a 141 MB
initrd (Ubuntu's is 86 MB), because an older kernel remained in the chroot
when the newer one was pulled in. A `linux-headers-*`-free, single-kernel
image trims size and boot time. The 2.95 GB vs 6.28 GB Ubuntu figure is
already good; this takes it further.

### 4. Small release hygiene
- Samurai's `.disk/` lacks `base_installable` (so Debian-derived tools
  don't know the disc is installable) — the live-build auto-config can set
  it.
- Keep the keys: `.disk/info` shows a correct Debian snapshot label, and
  `sha256sum.txt` exists; add the Kali-style public `.sig` distribution and
  the Ubuntu-style `md5sum.txt` symmetry (at least document which one the
  release signs).
- The `FILES` documentation should say what the updater (`unattended-
  upgrades` is installed, but which repo lists are shipped?) actually
  updates from, because `cloud-init`-style automation is a Ubuntu
  differentiator Samurai lacks.

## Where the numbers come from

Both manifests were copied straight off the mounted ISOs and normalised;
the Kali count is the repo's `Packages.gz` `Package:` fields (3,303), since
the installer ISO has no live manifest. Counts of dependencies will drift
with each build; the roles above were verified package-by-package against
the lists.
