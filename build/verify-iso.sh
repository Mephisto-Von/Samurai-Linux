#!/usr/bin/env bash
# Verify the contents of a built Samurai Linux ISO before booting or installing it.
# Usage: bash build/verify-iso.sh <iso>
set -euo pipefail

ISO="${1:-}"
TMP_DIR=""
REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd)

log() { printf '==> %s\n' "$*"; }
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

cleanup() {
    if [[ -n "$TMP_DIR" && -d "$TMP_DIR" ]]; then
        rm -rf "$TMP_DIR"
    fi
}
trap cleanup EXIT

if [[ -z "$ISO" ]]; then
    printf 'Usage: %s <iso>\n' "$0" >&2
    exit 1
fi
[[ -f "$ISO" ]] || die "ISO not found: $ISO"

for tool in xorriso unsquashfs; do
    command -v "$tool" >/dev/null 2>&1 || die "$tool is not installed"
done

TMP_DIR=$(mktemp -d)
ROOT="$TMP_DIR/rootfs"
SQUASHFS="$TMP_DIR/filesystem.squashfs"
mkdir -p "$ROOT"

assert_file() {
    local path=$1
    [[ -f "$ROOT/$path" ]] || die "Missing from live rootfs: /$path"
}

assert_contains() {
    local path=$1 pattern=$2
    grep -Eq "$pattern" "$ROOT/$path" || die "/$path does not match: $pattern"
}

assert_not_contains() {
    local path=$1 pattern=$2
    if grep -Eq "$pattern" "$ROOT/$path"; then
        die "/$path still matches: $pattern"
    fi
}

assert_file_contains() {
    local path=$1 pattern=$2
    grep -Eq "$pattern" "$path" || die "$path does not match: $pattern"
}

log "ISO: $ISO ($(du -h "$ISO" | cut -f1))"

log "Checking ISO boot records"
xorriso -indev "$ISO" -report_el_torito plain >"$TMP_DIR/el-torito.txt" 2>/dev/null
grep -qi 'El Torito boot img' "$TMP_DIR/el-torito.txt" \
    || die "ISO has no El Torito boot record"
grep -qi 'UEFI' "$TMP_DIR/el-torito.txt" \
    || die "ISO has no UEFI boot entry"

log "Extracting live kernel, initramfs, and squashfs"
xorriso -osirrox on -indev "$ISO" \
    -extract /live/vmlinuz "$TMP_DIR/vmlinuz" \
    -extract /live/initrd.img "$TMP_DIR/initrd.img" \
    -extract /live/filesystem.squashfs "$SQUASHFS" \
    -extract /isolinux/isolinux.cfg "$TMP_DIR/isolinux.cfg" \
    -extract /isolinux/menu.cfg "$TMP_DIR/menu.cfg" \
    -extract /isolinux/stdmenu.cfg "$TMP_DIR/stdmenu.cfg" \
    -extract /isolinux/live.cfg "$TMP_DIR/live.cfg" \
    -extract /isolinux/splash.png "$TMP_DIR/isolinux-splash.png" \
    -extract /boot/grub/grub.cfg "$TMP_DIR/grub.cfg" \
    -extract /boot/grub/splash.png "$TMP_DIR/grub-splash.png" \
    -extract /boot/grub/live-theme/theme.txt "$TMP_DIR/grub-theme.txt" >/dev/null
[[ -s "$TMP_DIR/vmlinuz" ]] || die "ISO is missing /live/vmlinuz"
[[ -s "$TMP_DIR/initrd.img" ]] || die "ISO is missing /live/initrd.img"
[[ -s "$SQUASHFS" ]] || die "ISO is missing /live/filesystem.squashfs"

log "Checking the live boot menu auto-boots with a serial console"
grep -Eq '^timeout[[:space:]]+50$' "$TMP_DIR/isolinux.cfg" \
    || die "/isolinux/isolinux.cfg does not auto-boot (timeout is not 5s)"
grep -q 'console=ttyS0,115200n8' "$TMP_DIR/live.cfg" \
    || die "/isolinux/live.cfg does not pass console=ttyS0,115200n8"
grep -q 'console=ttyS0,115200n8' "$TMP_DIR/grub.cfg" \
    || die "/boot/grub/grub.cfg does not pass console=ttyS0,115200n8"

log "Checking Samurai bootloader branding"
# The menu title carries the build date (YYYY.MM.DD) and the ISO file is named
# after the same date, so a stale hardcoded title cannot slip through.
ISO_DATE=""
if [[ $(basename "$ISO") =~ samurai-linux-([0-9]{4}\.[0-9]{2}\.[0-9]{2})-amd64\.iso$ ]]; then
    ISO_DATE="${BASH_REMATCH[1]}"
fi
if [[ -n "$ISO_DATE" ]]; then
    assert_file_contains "$TMP_DIR/menu.cfg" "^menu title Samurai Linux ${ISO_DATE//./\\.}$"
fi
assert_file_contains "$TMP_DIR/menu.cfg" '^menu title Samurai Linux [0-9]{4}\.[0-9]{2}\.[0-9]{2}$'
assert_file_contains "$TMP_DIR/live.cfg" 'Samurai Linux Live'
assert_file_contains "$TMP_DIR/grub.cfg" 'Samurai Linux Live'
assert_file_contains "$TMP_DIR/stdmenu.cfg" '#b52832ff'
assert_file_contains "$TMP_DIR/grub-theme.txt" '^title-text: ""$'
if grep -Eqi 'Debian' "$TMP_DIR/live.cfg" "$TMP_DIR/grub.cfg"; then
    die "the live boot menus still mention Debian"
fi
cmp -s "$TMP_DIR/isolinux-splash.png" "$REPO_ROOT/build/config/bootloaders/isolinux/splash.png" \
    || die "/isolinux/splash.png is not the Samurai splash"
cmp -s "$TMP_DIR/grub-splash.png" "$REPO_ROOT/build/config/bootloaders/grub-pc/splash.png" \
    || die "/boot/grub/splash.png is not the Samurai splash"

log "Extracting installer files from the live rootfs"
unsquashfs -f -no-progress -d "$ROOT" "$SQUASHFS" \
    etc/calamares/settings.conf \
    etc/calamares/branding/samurai/branding.desc \
    etc/calamares/branding/samurai/productLogo.png \
    etc/calamares/branding/samurai/productIcon.png \
    etc/calamares/branding/samurai/productWelcome.png \
    etc/calamares/branding/samurai/show.qml \
    etc/calamares/branding/samurai/slide1.png \
    etc/calamares/modules/packages.conf \
    usr/bin/calamares \
    usr/bin/calamares-install-debian \
    usr/bin/unsquashfs \
    usr/bin/rsync \
    usr/local/bin/samurai-ai \
    usr/local/bin/samurai-theme \
    usr/local/bin/samurai-gaming \
    usr/local/bin/samurai-profile \
    usr/local/bin/samurai-recovery \
    etc/nftables.conf \
    etc/sudoers.d/90samurai \
    etc/apt/preferences.d/99samurai \
    etc/apt/apt.conf.d/20samurai-security \
    etc/apt/sources.list.d/samurai-security.list \
    etc/systemd/journald.conf.d/99samurai.conf \
    usr/share/color-schemes/samurai-kuro.colors \
    usr/share/color-schemes/samurai-shiro.colors \
    usr/share/applications/calamares-install-debian.desktop \
    usr/share/backgrounds/samurai/kuro.jpg \
    usr/share/backgrounds/samurai/shiro.jpg \
    usr/share/samurai/boot/grub-splash.png \
    usr/share/pixmaps/samurai-linux.png \
    usr/lib/grub/i386-pc/normal.mod \
    usr/lib/grub/x86_64-efi/normal.mod \
    etc/os-release \
    etc/issue \
    etc/issue.net \
    etc/lsb-release \
    etc/motd \
    etc/default/grub \
    var/lib/dpkg/status >/dev/null

assert_file etc/calamares/settings.conf
assert_file etc/calamares/branding/samurai/branding.desc
assert_file etc/calamares/branding/samurai/productLogo.png
assert_file etc/calamares/branding/samurai/productIcon.png
assert_file etc/calamares/branding/samurai/productWelcome.png
assert_file etc/calamares/branding/samurai/show.qml
assert_file etc/calamares/branding/samurai/slide1.png
assert_file etc/calamares/modules/packages.conf
assert_file usr/bin/calamares
assert_file usr/bin/calamares-install-debian
assert_file usr/bin/unsquashfs
assert_file usr/bin/rsync
assert_file usr/local/bin/samurai-ai
assert_file usr/local/bin/samurai-theme
assert_file usr/local/bin/samurai-gaming
assert_file usr/local/bin/samurai-profile
assert_file usr/local/bin/samurai-recovery
assert_file etc/nftables.conf
assert_file etc/sudoers.d/90samurai
assert_file etc/apt/preferences.d/99samurai
assert_file etc/apt/apt.conf.d/20samurai-security
assert_file etc/systemd/journald.conf.d/99samurai.conf
assert_file usr/share/color-schemes/samurai-kuro.colors
assert_file usr/share/color-schemes/samurai-shiro.colors
assert_file usr/share/applications/calamares-install-debian.desktop
assert_file usr/share/backgrounds/samurai/kuro.jpg
assert_file usr/share/backgrounds/samurai/shiro.jpg
assert_file usr/share/samurai/boot/grub-splash.png
assert_file usr/share/pixmaps/samurai-linux.png
assert_file usr/lib/grub/i386-pc/normal.mod
assert_file usr/lib/grub/x86_64-efi/normal.mod
assert_file etc/os-release
assert_file etc/issue
assert_file etc/issue.net
assert_file etc/lsb-release
assert_file etc/motd
assert_file etc/default/grub
assert_file var/lib/dpkg/status

log "Checking Calamares branding and desktop entry"
assert_contains etc/calamares/settings.conf '^branding:[[:space:]]*samurai$'
assert_contains etc/calamares/branding/samurai/branding.desc \
    'productName:[[:space:]]+Samurai Linux'
assert_contains usr/share/applications/calamares-install-debian.desktop \
    '^Name=Install Samurai Linux$'
assert_contains usr/share/applications/calamares-install-debian.desktop \
    '^Exec=calamares-install-debian$'

# An apt-get remove of a package that is not installed exits 100 and aborts the
# whole install, so every live package we purge unconditionally must be present
# in the image and the speculative entries must sit under try_remove.
log "Checking Calamares package operations"
assert_contains etc/calamares/modules/packages.conf '^backend:[[:space:]]*apt$'
assert_contains etc/calamares/modules/packages.conf '^  - remove:$'
assert_contains etc/calamares/modules/packages.conf '^      - live-boot$'
assert_contains etc/calamares/modules/packages.conf '^      - calamares-settings-debian$'
assert_contains etc/calamares/modules/packages.conf '^  - try_remove:$'
assert_contains etc/calamares/modules/packages.conf \
    '^      - live-task-localisation$'
assert_contains var/lib/dpkg/status '^Package: live-boot$'
assert_contains var/lib/dpkg/status '^Package: live-config$'
assert_contains var/lib/dpkg/status '^Package: live-config-systemd$'
assert_contains var/lib/dpkg/status '^Package: live-tools$'

log "Checking distribution branding"
assert_contains etc/os-release '^NAME="Samurai Linux"$'
assert_contains etc/os-release '^ID=samurai$'
assert_contains etc/os-release '^PRETTY_NAME="Samurai Linux 2026\.10"$'
assert_contains etc/os-release '^ID_LIKE=debian$'
assert_contains etc/issue 'Samurai Linux 2026\.10'
assert_contains etc/issue.net 'Samurai Linux 2026\.10'
assert_contains etc/lsb-release '^DISTRIB_ID=Samurai$'
assert_contains etc/motd 'Welcome to Samurai Linux'
assert_not_contains etc/os-release 'Debian GNU/Linux'
assert_not_contains etc/issue 'Debian GNU/Linux'
assert_not_contains etc/issue.net 'Debian GNU/Linux'
assert_contains etc/default/grub '^GRUB_DISTRIBUTOR="Samurai Linux"$'
assert_contains etc/default/grub '^GRUB_BACKGROUND="/usr/share/samurai/boot/grub-splash.png"$'
assert_contains etc/default/grub 'console=ttyS0,115200n8'
cmp -s "$ROOT/usr/share/samurai/boot/grub-splash.png" \
    "$REPO_ROOT/build/config/includes.chroot/usr/share/samurai/boot/grub-splash.png" \
    || die "the installed GRUB splash is not the Samurai splash"

log "Checking desktop wallpapers"
for wallpaper in kuro.jpg shiro.jpg; do
    cmp -s "$ROOT/usr/share/backgrounds/samurai/$wallpaper" \
        "$REPO_ROOT/build/config/includes.chroot/usr/share/backgrounds/samurai/$wallpaper" \
        || die "/usr/share/backgrounds/samurai/$wallpaper is not the Samurai wallpaper"
done

log "Checking that the live rootfs can run update-grub"
# Calamares' calamares-bootloader-config helper ends with update-grub, which
# writes /boot/grub/grub.cfg. The live image never installs GRUB to a disk, so
# the directory has to ship in the image or the installer fails offline.
unsquashfs -l "$SQUASHFS" boot/grub >/dev/null 2>&1 \
    || die "the live rootfs has no /boot/grub; Calamares could not write grub.cfg"

log "Checking installed packages needed by the installer"
assert_contains var/lib/dpkg/status '^Package: calamares$'
assert_contains var/lib/dpkg/status '^Package: calamares-settings-debian$'
assert_contains var/lib/dpkg/status '^Package: grub-pc-bin$'
assert_contains var/lib/dpkg/status '^Package: grub-efi-amd64-bin$'
assert_contains var/lib/dpkg/status '^Package: efibootmgr$'
assert_contains var/lib/dpkg/status '^Package: squashfs-tools$'
assert_contains var/lib/dpkg/status '^Package: rsync$'
assert_contains var/lib/dpkg/status '^Package: cryptsetup$'

log "Checking the shipped security policy"
assert_contains etc/nftables.conf '^table inet samurai'
assert_contains etc/nftables.conf 'type filter hook input priority 0; policy drop'
assert_contains etc/nftables.conf 'chain ingress_exceptions'
assert_contains etc/sudoers.d/90samurai '^Defaults[[:space:]]env_reset$'
assert_contains etc/apt/preferences.d/99samurai '^Pin-Priority: 600$'
assert_contains etc/apt/apt.conf.d/20samurai-security 'APT::Periodic::Unattended-Upgrade "1"'
assert_contains etc/apt/apt.conf.d/20samurai-security '"Debian:trixie-security"'
assert_contains etc/apt/sources.list.d/samurai-security.list '^deb http://deb.debian.org/debian-security trixie-security main$'
assert_contains etc/systemd/journald.conf.d/99samurai.conf '^Storage=persistent$'
assert_contains usr/local/bin/samurai-profile '^profile_packages\(\) \{$'
assert_contains usr/local/bin/samurai-recovery '^cmd_snapshot\(\) \{$'

# Unattended upgrades are only real if an archive exists to upgrade from. The
# shipped source list is written by live-build from --mirror-binary-security and
# is gated on --security in build/auto/config, so this is the only place that
# can prove it survived: the chroot hooks run before the build-time sources are
# replaced with the final ones. Checked per file, because /etc/apt as a whole
# would also match the pin in preferences.d, which proves nothing about a
# configured source.
unsquashfs -f -no-progress -d "$ROOT" etc/apt/sources.list >/dev/null 2>&1 || true
unsquashfs -f -no-progress -d "$ROOT" etc/apt/sources.list.d >/dev/null 2>&1 || true
sources_found=0
sources_named=()
for source in "$ROOT/etc/apt/sources.list" "$ROOT/etc/apt/sources.list.d"/*.list \
    "$ROOT/etc/apt/sources.list.d"/*.sources; do
    [[ -e "$source" ]] || continue
    if grep -q 'trixie-security' "$source"; then
        sources_found=$((sources_found + 1))
        sources_named+=("$source")
    fi
done
if ((sources_found == 0)); then
    printf '%s\n' "shipped APT sources:" >&2
    for source in "$ROOT/etc/apt/sources.list" "$ROOT/etc/apt/sources.list.d"/*; do
        [[ -f "$source" ]] || continue
        printf '--- %s\n' "$source" >&2
        cat "$source" >&2
    done
    die "the image configures no Debian security archive to update from"
fi
# samurai-security.list is the one we ship and expect; a second entry beside it
# makes apt print "Target Packages is configured multiple times" on every run.
if ((sources_found > 1)); then
    die "the security archive is configured ${sources_found} times: ${sources_named[*]}"
fi

log "Checking the permissions the image records for those files"
# Read from the squashfs metadata rather than an extraction: extracting as a
# non-root user rewrites ownership, and sudo ignores a group-writable sudoers
# drop-in while nft refuses to read a group-writable configuration, so a wrong
# mode is a security policy that is present and silently not applied.
unsquashfs -lm "$SQUASHFS" > "$TMP_DIR/squashfs-listing.txt"
assert_image_mode() {
    local path=$1 expect=$2 found
    found=$(awk -v p="$path" '{ name = $NF; sub(/^\./, "", name)
        if (name == p) { print $1, $2; exit } }' "$TMP_DIR/squashfs-listing.txt")
    [[ -n "$found" ]] || die "/$path is not in the squashfs metadata"
    if [[ "$found" != "$expect" ]]; then
        die "/$path is recorded as '$found', expected '$expect'"
    fi
}
assert_image_mode etc/sudoers.d/90samurai '-rw-r----- root/root'
assert_image_mode etc/nftables.conf '-rw-r--r-- root/root'
assert_image_mode etc/apt/preferences.d/99samurai '-rw-r--r-- root/root'
assert_image_mode etc/apt/apt.conf.d/20samurai-security '-rw-r--r-- root/root'
assert_image_mode usr/local/bin/samurai-profile '-rwxr-xr-x root/root'
assert_image_mode usr/local/bin/samurai-recovery '-rwxr-xr-x root/root'
# apt reads a source file only if it is not group- or world-writable, and a
# security archive the updater cannot read is the failure this whole check exists
# to prevent.
assert_image_mode etc/apt/sources.list.d/samurai-security.list '-rw-r--r-- root/root'

# The published wallpaper count has to mean something about the shipped image,
# not only about the repository: this is the gate that holds it.
image_wallpapers=$(awk '{ name = $NF; sub(/^\./, "", name)
    if (name ~ /^usr\/share\/backgrounds\/samurai\/[^/]+\.jpg$/) count++ }
    END { print count + 0 }' "$TMP_DIR/squashfs-listing.txt")
source_wallpapers=$(find "$REPO_ROOT/build/config/includes.chroot/usr/share/backgrounds/samurai" \
    -type f -name '*.jpg' | wc -l | tr -d '[:space:]')
if [[ "$image_wallpapers" != "$source_wallpapers" ]]; then
    die "the image carries $image_wallpapers wallpapers, the build tree has $source_wallpapers"
fi
log "the image carries all $image_wallpapers wallpapers"

log "Writing and validating the release package manifest"
TAB=$'	'  # the manifest separator; a literal tab is too easy to lose in an edit
# Version tracking for one build: the exact package set the ISO carries, which is
# what a vulnerability triage or a bug report needs to be able to name.
MANIFEST="${ISO%.iso}.packages.tsv"
awk '
    /^Package: / { package = substr($0, 10) }
    /^Version: / { version = substr($0, 10) }
    /^Architecture: / { architecture = substr($0, 15) }
    /^Status: / { installed = ($0 == "Status: install ok installed") }
    /^$/ {
        if (package != "" && installed) printf "%s\t%s\t%s\n", package, version, architecture
        package = ""; version = ""; architecture = ""; installed = 0
    }
    END { if (package != "" && installed) printf "%s\t%s\t%s\n", package, version, architecture }
' "$ROOT/var/lib/dpkg/status" | sort > "$MANIFEST"
[[ -s "$MANIFEST" ]] || die "the manifest is empty: dpkg status produced nothing"
if awk -F'\t' 'NF != 3 { bad = 1 } END { exit bad }' "$MANIFEST"; then
    die "the manifest has a line without package, version and architecture"
fi
manifest_count=$(wc -l < "$MANIFEST")
if ((manifest_count < 400)); then
    die "the manifest lists only $manifest_count packages; a Plasma system has far more"
fi
log "Manifest: $MANIFEST ($manifest_count installed packages)"
for package in plasma-desktop sddm linux-image-amd64 nftables apparmor \
    unattended-upgrades libgl1-mesa-dri mesa-vulkan-drivers mangohud gamemode calamares; do
    if ! grep -q "^${package}${TAB}" "$MANIFEST"; then
        die "the manifest does not contain $package"
    fi
done

# Everything the package lists declare must be in the image. live-build would
# have failed on an unfetchable name, so this catches the quieter mistake: a list
# that was trimmed, or a package that stopped being installed and nobody noticed.
while IFS= read -r package; do
    [[ -n "$package" ]] || continue
    if ! grep -q "^${package}${TAB}" "$MANIFEST"; then
        die "$package is declared in samurai.list.chroot but absent from the image"
    fi
done < <(grep -Ev '^[[:space:]]*(#|$)' "$REPO_ROOT/build/config/package-lists/samurai.list.chroot")

log "ISO verification passed"
