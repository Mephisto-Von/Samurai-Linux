#!/usr/bin/env bash
# Build the Samurai Linux live ISO with Debian live-build.
set -euo pipefail

BUILD_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" >/dev/null 2>&1 && pwd)
REPO_ROOT=$(cd -- "$BUILD_DIR/.." && pwd)

# Two images come out of one image definition. `desktop` is what the repository
# shipped until the owner asked for a second, larger variant; `security` adds an
# archive, a tool list and a pin file from build/variants/security.
VARIANT="${SAMURAI_VARIANT:-desktop}"

# The disk floor is per variant because the work is not comparable: a desktop
# chroot fits in 50 GiB, while a chroot carrying a full offensive tool archive
# needs the installed tree, the binary copy of it and the squashfs of that
# roughly at once. Overridable, and check_host enforces it rather than warning,
# because a build that dies at 90% leaves a chroot no later run can resume.
apply_variant() {
    local default_disk
    case "$VARIANT" in
        desktop)
            ISO_PREFIX="samurai-linux"
            default_disk=50
            ;;
        security)
            ISO_PREFIX="samurai-security"
            default_disk=200
            ;;
        *) die "unknown variant '$VARIANT' (expected desktop or security)" ;;
    esac
    MIN_DISK_GB="${SAMURAI_MIN_DISK_GB:-$default_disk}"
}
MIN_RAM_GB="${SAMURAI_MIN_RAM_GB:-4}"

log() { printf '==> %s\n' "$*"; }
warn() { printf 'Warning: %s\n' "$*" >&2; }
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

# After the helpers, so an unknown SAMURAI_VARIANT fails with this script's
# error message rather than "die: command not found".
apply_variant

usage() {
    cat <<'EOF'
Build the Samurai Linux live ISO.

Usage: [sudo] bash build/build.sh [--variant NAME] [option]

Variants:
  desktop   (default) the workstation image
  security  the same desktop plus an installed offensive-security toolset

Options:
  (none)       Clean, configure, build, and collect the ISO
  --check      Validate the host, sync assets, and generate the config only
  --clean      Remove live-build state and generated files
  --no-clean   Build without running `lb clean`
  -h, --help   Show this help

Environment:
  SAMURAI_VARIANT       desktop or security (default: desktop)
  SAMURAI_MIN_DISK_GB   Required free disk in GiB (default: 50 desktop, 200 security)
  SAMURAI_MIN_RAM_GB    Warn below this RAM in GiB (default: 4)
  SAMURAI_SIGN_KEY      GPG key id used to sign the ISO (optional)

Output:
  dist/samurai-linux-YYYY.MM.DD-amd64.iso      (security: samurai-security-...)
  dist/<iso>.sha256
  dist/<iso>.sig  (when SAMURAI_SIGN_KEY is set)
EOF
}

require_root() {
    ((EUID == 0)) || die "live-build must run as root. Use: sudo bash build/build.sh"
}

check_host() {
    [[ "$(uname -s)" == "Linux" ]] || die "A Linux build host is required"
    [[ "$(uname -m)" == "x86_64" ]] || die "Only x86_64 is supported"

    local tool
    for tool in lb debootstrap xorriso mksquashfs; do
        command -v "$tool" >/dev/null 2>&1 || die "Missing build tool: $tool (install live-build, debootstrap, xorriso, squashfs-tools)"
    done

    local available_kb available_gb
    available_kb=$(df -Pk "$REPO_ROOT" | awk 'NR == 2 { print $4 }')
    available_gb=$((available_kb / 1024 / 1024))
    if ((available_gb < MIN_DISK_GB)); then
        die "Need at least ${MIN_DISK_GB} GiB free, found ${available_gb} GiB on the build filesystem"
    fi

    local mem_kb mem_gb
    mem_kb=$(awk '/^MemTotal:/ { print $2 }' /proc/meminfo)
    mem_gb=$((mem_kb / 1024 / 1024))
    if ((mem_gb < MIN_RAM_GB)); then
        warn "Only ${mem_gb} GiB RAM detected; ${MIN_RAM_GB} GiB or more is recommended"
    fi

    log "Host check passed (${available_gb} GiB free, ${mem_gb} GiB RAM) variant=$VARIANT needs ${MIN_DISK_GB} GiB"
}

sync_assets() {
    local includes="$BUILD_DIR/config/includes.chroot"
    local bin="$includes/usr/local/bin"
    local themes="$includes/usr/share/samurai/themes"

    rm -rf "$bin" "$themes"
    install -d -m 0755 "$bin" "$themes"
    cp -a "$REPO_ROOT/samurai/scripts/." "$bin/"
    cp -a "$REPO_ROOT/samurai/themes/." "$themes/"

    find "$bin" -maxdepth 1 -type f -name 'samurai-*' -exec chmod 0755 {} +
    if [[ -d "$BUILD_DIR/config/hooks" ]]; then
        find "$BUILD_DIR/config/hooks" -name '*.hook.chroot' -exec chmod 0755 {} +
    fi
    chmod 0755 "$BUILD_DIR/auto/config"
    # The variant's archive, tool list and pin files, and /etc/samurai-variant.
    # A separate script because the rule "staging must remove what the previous
    # build staged before it copies what this one stages" is worth testing on a
    # machine with no live-build on it: see `bash build/stage-variant.sh --self-test`.
    bash "$BUILD_DIR/stage-variant.sh" --variant "$VARIANT" --build-dir "$BUILD_DIR"
    log "Synced scripts and themes into config/includes.chroot"
}

run_config() {
    log "Generating live-build configuration"
    (cd "$BUILD_DIR" && bash auto/config)
}

clean_build() {
    require_root
    if [[ ! -d "$BUILD_DIR/.build" && ! -d "$BUILD_DIR/binary" &&
          ! -d "$BUILD_DIR/bootstrap" && ! -d "$BUILD_DIR/chroot" &&
          ! -d "$BUILD_DIR/cache" && ! -d "$BUILD_DIR/config/binary" &&
          ! -d "$BUILD_DIR/config/bootstrap" && ! -d "$BUILD_DIR/config/chroot" ]]; then
        log "Nothing to clean"
        return 0
    fi
    log "Cleaning previous live-build state"
    (cd "$BUILD_DIR" && lb clean --purge)
}

build_iso() {
    log "Building the ISO (this can take 20-60 minutes)"
    (cd "$BUILD_DIR" && lb build 2>&1 | tee build.log)
}

collect_artifacts() {
    local source out name
    local isos=()
    shopt -s nullglob
    isos=("$BUILD_DIR"/live-image-*.hybrid.iso)
    shopt -u nullglob

    ((${#isos[@]} > 0)) || die "Build finished but no live-image-*.hybrid.iso was produced"
    source="${isos[0]}"
    name="$ISO_PREFIX-$(date +%Y.%m.%d)-amd64.iso"
    install -d -m 0755 "$REPO_ROOT/dist"
    out="$REPO_ROOT/dist/$name"
    cp -- "$source" "$out"
    (cd "$REPO_ROOT/dist" && sha256sum "$name" > "$name.sha256")

    if [[ -n "${SAMURAI_SIGN_KEY:-}" ]]; then
        command -v gpg >/dev/null 2>&1 || die "SAMURAI_SIGN_KEY is set but gpg is not installed"
        gpg --armor --detach-sign --local-user "$SAMURAI_SIGN_KEY" --output "$out.sig" "$out"
        log "Signed $out"
    else
        warn "SAMURAI_SIGN_KEY is not set; the ISO was not signed"
    fi

    log "ISO:      $out"
    log "Checksum: $out.sha256"
}

main() {
    # --variant is accepted anywhere, because the thing it changes - which
    # variant is staged and what the ISO is called - has to be known before the
    # first step that reads the config tree, and a caller who means
    # `--check --variant security` should not have to know which one parses first.
    local -a rest=()
    while (($#)); do
        case "$1" in
            --variant)
                (($# >= 2)) || die "--variant needs a name: desktop or security"
                VARIANT=$2
                shift 2
                ;;
            --variant=*)
                VARIANT=${1#--variant=}
                shift
                ;;
            *)
                rest+=("$1")
                shift
                ;;
        esac
    done
    apply_variant

    case "${rest[0]:-}" in
        --check)
            check_host
            sync_assets
            run_config
            log "Configuration is valid"
            ;;
        --clean)
            clean_build
            ;;
        --no-clean)
            require_root
            check_host
            sync_assets
            run_config
            build_iso
            collect_artifacts
            ;;
        -h|--help)
            usage
            ;;
        "")
            require_root
            check_host
            sync_assets
            # Configure before cleaning so `lb clean` always has a config to
            # remove (it refuses to run in a fresh checkout), then regenerate.
            run_config
            clean_build
            run_config
            build_iso
            collect_artifacts
            ;;
        *)
            die "Unknown option: ${rest[*]} (run: bash build/build.sh --help)"
            ;;
    esac
}

main "$@"
