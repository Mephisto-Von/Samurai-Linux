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
    etc/xdg/autostart/calamares-desktop-icon.desktop \
    usr/bin/add-calamares-desktop-icon \
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
# installation.md promises a desktop icon as well as a menu entry, and in
# Debian's live configuration that icon is not on the ISO: an autostart entry
# runs add-calamares-desktop-icon, which drops the launcher into the live
# user's Desktop at login. Both halves have to be present or the icon never
# appears and the documented step is a lie.
assert_file etc/xdg/autostart/calamares-desktop-icon.desktop
assert_file usr/bin/add-calamares-desktop-icon
assert_contains etc/xdg/autostart/calamares-desktop-icon.desktop 'add-calamares-desktop-icon'
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

log "Checking the kernel the ISO boots against the modules in the live rootfs"
# The squashfs metadata is read once here and reused for the mode checks below.
# It is read rather than extracted because extracting as a non-root user rewrites
# ownership, and sudo ignores a group-writable sudoers drop-in while nft refuses
# to read a group-writable configuration, so a wrong mode is a security policy
# that is present and silently not applied.
#
# -ll is the ls -l style listing and -dest . makes it print ./path instead of
# prefixing the default squashfs-root/. Both flags have to be right: an option
# unsquashfs does not recognise prints its usage to stdout and exits 1, which is
# how run 41514577159 lost fifteen minutes of build with nothing on stderr.
#
# /live/vmlinuz and /lib/modules are produced by different live-build stages, so
# they can disagree: the binary stage upgrades the chroot after binary_rootfs has
# packed the squashfs, and binary_linux-image then copies the *newest* /boot
# kernel into /live. Run 41545976827 shipped a 6.12.115+deb13.1 kernel over a
# squashfs whose only modules tree was 6.12.107+deb13 - every module failed to
# load, including nf_tables, which took the firewall with it. Match /live/vmlinuz
# to a kernel that is actually in the image by content, not by name.
if ! unsquashfs -ll -dest . -quiet "$SQUASHFS" > "$TMP_DIR/squashfs-listing.txt"; then
    printf '%s\n' "what unsquashfs wrote to stdout:" >&2
    head -n 20 "$TMP_DIR/squashfs-listing.txt" >&2
    die "unsquashfs could not list the squashfs metadata"
fi
# Turn "mode owner/group size date time path" into "mode<TAB>owner/group<TAB>path".
# The path is everything after the timestamp rather than the last field, because
# a path may contain spaces; symlink lines are dropped, since their listing
# continues " -> target" and a link's own mode is always 777 anyway.
awk '{ ts = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9] "
    if (!match($0, ts) || $1 ~ /^l/) next
    name = substr($0, RSTART + RLENGTH)
    sub(/^\.\//, "", name)
    print $1 "\t" $2 "\t" name
}' "$TMP_DIR/squashfs-listing.txt" > "$TMP_DIR/squashfs-modes.tsv"
[[ -s "$TMP_DIR/squashfs-modes.tsv" ]] || die "the squashfs listing contains no file records"

live_kernel_hash=$(sha256sum "$TMP_DIR/vmlinuz" | cut -d' ' -f1)
live_kernel_size=$(stat -c %s "$TMP_DIR/vmlinuz")
printf '==> /live/vmlinuz is %s bytes, sha256 %s\n' "$live_kernel_size" "$live_kernel_hash"
awk '{ ts = "[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9] [0-9][0-9]:[0-9][0-9] "
    if (!match($0, ts)) next
    name = substr($0, RSTART + RLENGTH)
    sub(/^\.\//, "", name)
    if (name !~ /^boot\/vmlinuz-/) next
    print $3 "\t" name
}' "$TMP_DIR/squashfs-listing.txt" > "$TMP_DIR/boot-kernels.tsv"
[[ -s "$TMP_DIR/boot-kernels.tsv" ]] \
    || die "the live rootfs has no /boot/vmlinuz-* to compare /live/vmlinuz against"

booted_version=""
size_matches=0
while IFS=$'\t' read -r candidate_size candidate; do
    if ! unsquashfs -f -no-progress -d "$ROOT" "$SQUASHFS" "$candidate" >/dev/null 2>&1; then
        printf '    %s: unsquashfs could not extract it\n' "$candidate" >&2
        continue
    fi
    candidate_hash=$(sha256sum "$ROOT/$candidate" | cut -d' ' -f1)
    printf '    %s: %s bytes, sha256 %s\n' "$candidate" "$candidate_size" "$candidate_hash" >&2
    if [[ "$candidate_hash" == "$live_kernel_hash" ]]; then
        booted_version="${candidate##*/vmlinuz-}"
        break
    fi
    if [[ "$candidate_size" == "$live_kernel_size" ]]; then
        # A byte-for-byte copy is not guaranteed: live-build owns what it puts in
        # /live. A size match still names the version, as long as only one kernel
        # has that size - two would be indistinguishable.
        booted_version="${candidate##*/vmlinuz-}"
        size_matches=$((size_matches + 1))
    fi
done < "$TMP_DIR/boot-kernels.tsv"
if [[ -z "$booted_version" ]]; then
    die "/live/vmlinuz is not any kernel in the live rootfs (sizes and hashes above): the ISO would boot a kernel whose modules are not in the image"
fi
((size_matches <= 1)) \
    || die "${size_matches} kernels in the live rootfs are the same size as /live/vmlinuz, so which one the ISO boots cannot be told apart"
# One awk pass answers both questions, because a pipeline cannot be trusted
# here: grep -q leaves as soon as it matches, the upstream grep then dies of
# SIGPIPE, and pipefail reports the pipeline as failed on an image that passed
# it (run 41790753113 lost a build that way). $3 is the path with its leading
# "./" already stripped; the live rootfs is merged-usr, so the modules live
# under usr/lib/modules and only reach /lib/modules through the root symlink
# (run 41793293770 was discarded for not knowing that). Compare and report
# against the merged view, and carry the evidence the failure needs: which
# trees the image holds at all, and what the booted tree actually contains.
# >>> live-modules-check (tests/smoke.sh executes these lines against fixture
# listings, because this block discarded two good ISOs when it was only read)
modules_summary=$(awk -F'\t' -v tree="lib/modules/$booted_version/" -v mod='/net/netfilter/nf_tables.ko' '
    { p = $3; sub(/^usr\//, "", p) }
    index(p, "lib/modules/") == 1 {
        version = p
        sub(/^lib\/modules\//, "", version)
        sub(/\/.*/, "", version)
        if (!(version in seen)) {
            seen[version] = 1
            trees = trees (trees == "" ? "" : ", ") version
        }
    }
    index(p, tree) == 1 {
        count++
        if (module == "" && index(p, mod)) module = $3
        if (shown < 3) {
            shown++
            sample = sample (sample == "" ? "" : ", ") $3
        }
    }
    END { print count + 0 "\t" module "\t" trees "\t" sample }' "$TMP_DIR/squashfs-modes.tsv")
# Split on the tab by hand: read would treat it as IFS whitespace and collapse
# an empty field, so a tree without the module would report the module path
# that the field after it happens to hold.
modules_found=${modules_summary%%$'\t'*}
modules_rest=${modules_summary#*$'\t'}
nftables_module=${modules_rest%%$'\t'*}
modules_rest=${modules_rest#*$'\t'}
modules_trees=${modules_rest%%$'\t'*}
modules_sample=${modules_rest#*$'\t'}
((modules_found > 0)) \
    || die "the ISO boots $booted_version but the live rootfs has no modules tree for it (the image holds: ${modules_trees:-none}): the kernel would load no driver"
[ -n "$nftables_module" ] \
    || die "the ISO boots $booted_version, whose tree has no nf_tables module (its entries include: $modules_sample): the default-deny ruleset could not load"
log "the ISO boots $booted_version: the live rootfs holds $modules_found of its files, including $nftables_module"
# <<< live-modules-check

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
unsquashfs -f -no-progress -d "$ROOT" "$SQUASHFS" etc/apt/sources.list >/dev/null 2>&1 || true
unsquashfs -f -no-progress -d "$ROOT" "$SQUASHFS" etc/apt/sources.list.d >/dev/null 2>&1 || true
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
# $TMP_DIR/squashfs-modes.tsv, built above, is the squashfs metadata listing.
image_mode_problems=()
assert_image_mode() {
    local path=$1 expect=$2 found
    found=$(awk -F'\t' -v p="$path" '$3 == p { print $1, $2; exit }' "$TMP_DIR/squashfs-modes.tsv")
    if [[ -z "$found" ]]; then
        image_mode_problems+=("/$path is not in the squashfs metadata")
    elif [[ "$found" != "$expect" ]]; then
        image_mode_problems+=("/$path is recorded as '$found', expected '$expect'")
    fi
}
# Every expected mode and owner is the one 0120-security.hook.chroot sets, so a
# mismatch means the hook stopped running or live-build copied something else
# over it. All of them are reported together: one build per mistake is expensive,
# and a second wrong expectation is invisible behind the first.
assert_image_mode etc/sudoers.d/90samurai '-r--r----- root/root'
assert_image_mode etc/nftables.conf '-rw-r--r-- root/root'
assert_image_mode etc/apt/preferences.d/99samurai '-rw-r--r-- root/root'
assert_image_mode etc/apt/apt.conf.d/20samurai-security '-rw-r--r-- root/root'
assert_image_mode usr/local/bin/samurai-profile '-rwxr-xr-x root/root'
assert_image_mode usr/local/bin/samurai-recovery '-rwxr-xr-x root/root'
# apt reads a source file only if it is not group- or world-writable, and a
# security archive the updater cannot read is the failure this whole check exists
# to prevent.
assert_image_mode etc/apt/sources.list.d/samurai-security.list '-rw-r--r-- root/root'
assert_image_mode etc/systemd/journald.conf.d/99samurai.conf '-rw-r--r-- root/root'
assert_image_mode usr/share/color-schemes/samurai-kuro.colors '-rw-r--r-- root/root'
assert_image_mode usr/share/color-schemes/samurai-shiro.colors '-rw-r--r-- root/root'
if (( ${#image_mode_problems[@]} > 0 )); then
    printf '%s\n' "${image_mode_problems[@]}" >&2
    die "${#image_mode_problems[@]} file(s) in the image do not carry the recorded permissions"
fi

# The published wallpaper count has to mean something about the shipped image,
# not only about the repository: this is the gate that holds it.
image_wallpapers=$(awk -F'\t' '$3 ~ /^usr\/share\/backgrounds\/samurai\/[^\/]+\.jpg$/ { c++ }
    END { print c + 0 }' "$TMP_DIR/squashfs-modes.tsv")
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
# Parse by "Key:" prefix instead of a fixed substr offset, flush a record when a
# new Package: header arrives as well as on the blank line, and replace any tab
# inside a value: this file is read back as tab-separated, and run 41520207923
# found a row that was not three fields wide without being able to say which one.
awk '
    function emit() {
        if (pkg != "" && status == "install ok installed") {
            if (version == "" || arch == "")
                printf "# %s: installed with %s\n", pkg, \
                    (version == "" ? "no Version field" : "no Architecture field")
            else printf "%s\t%s\t%s\n", pkg, version, arch
        }
        pkg = ""; version = ""; arch = ""; status = ""
    }
    { line = $0; sub(/\r$/, "", line) }
    line ~ /^[A-Za-z][A-Za-z0-9-]*:/ {
        key = line; sub(/:.*/, "", key)
        value = line; sub(/^[^:]*:[ ]?/, "", value)
        gsub(/\t/, " ", value)
        if (key == "Package") { emit(); pkg = value }
        else if (key == "Version") version = value
        else if (key == "Architecture") arch = value
        else if (key == "Status") status = value
        next
    }
    line ~ /^[[:space:]]*$/ { emit(); next }
    END { emit() }
' "$ROOT/var/lib/dpkg/status" | sort > "$MANIFEST"
bash "$REPO_ROOT/build/check-manifest.sh" "$MANIFEST"
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
