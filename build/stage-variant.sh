#!/usr/bin/env bash
# Put one variant's material into the live-build config tree, and nothing else's.
#
# live-build has no notion of a variant: it installs every
# config/package-lists/*.list.chroot it finds and every config/archives/* it
# finds. So the choice of image is made here, in the filesystem, by which files
# are present - which is also why the removal comes first. A config tree that
# still held the security archive would build a security image under the desktop
# name, ship desktop documentation, and be indistinguishable from the outside
# except by its size.
#
# Staged paths are derived from what build/variants/*/ contains rather than from
# a hard-coded list, so adding a variant needs no change in this file, and
# deleting one cannot leave its orphan behind.
#
# --self-test builds fake variant and config trees in a temporary directory and
# checks both directions of the switch. It needs no root, no live-build and no
# network, which is why tests/smoke.sh runs it on every push.
set -euo pipefail

log() { printf '==> %s\n' "$*"; }
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

# The temporary tree the self-test builds. Global, and named here rather than
# inside the function that creates it, because the EXIT trap runs after that
# function has returned: a `local` name no longer exists by then, and `set -u`
# turns the cleanup itself into a failure that masks the tests that passed.
SELFTEST_TMP=""
selftest_cleanup() {
    [[ -z "$SELFTEST_TMP" ]] || rm -rf "$SELFTEST_TMP"
    return 0
}
trap selftest_cleanup EXIT

usage() {
    cat <<'EOF'
Stage one image variant into a live-build config tree.

Usage: bash build/stage-variant.sh --variant NAME --build-dir DIR
       bash build/stage-variant.sh --self-test

Options:
  --variant NAME     desktop or security (the name must be a directory under
                     DIR/variants, except that a variant with no material of its
                     own is a legitimate desktop build)
  --build-dir DIR    the build/ directory holding config/
  --self-test        run the built-in tests and exit
  -h, --help         show this help
EOF
}

# The files a variant owns, relative to the build directory, one per line.
# package-lists and includes.chroot are named so the inverse operation -
# removing what a previous build staged - can enumerate every variant, not just
# the one being built now.
variant_files() {
    local variant_root=$1 kind=$2
    [[ -d "$variant_root" ]] || return 0
    case "$kind" in
        package-lists)
            (cd "$variant_root" && find . -path './*/package-lists/*' -type f -printf '%P\n')
            ;;
        includes.chroot)
            (cd "$variant_root" && find . -path './*/includes.chroot/*' -type f -printf '%P\n')
            ;;
        *) die "stage-variant: unknown kind $kind" ;;
    esac
}

stage() {
    local variant=$1 build_dir=$2
    local variant_root="$build_dir/variants"
    local includes="$build_dir/config/includes.chroot"
    local src rel

    [[ -d "$build_dir/config" ]] || die "no live-build config tree in $build_dir"

    # 1. Remove every variant's staged material, whatever the last build left.
    rm -rf "$build_dir/config/archives"
    while IFS= read -r rel; do
        [[ -n "$rel" ]] || continue
        rm -f "$build_dir/config/package-lists/$(basename -- "$rel")"
    done < <(variant_files "$variant_root" package-lists)
    while IFS= read -r rel; do
        [[ -n "$rel" ]] || continue
        rm -f "$includes/${rel#*/includes.chroot/}"
    done < <(variant_files "$variant_root" includes.chroot)

    # 2. Record what this image is. verify-iso.sh reads this file to decide
    #    which declared package list the squashfs has to satisfy, so the check
    #    that a tool was not silently dropped follows the image rather than the
    #    build machine's environment.
    install -d -m 0755 "$includes/etc"
    printf '%s\n' "$variant" > "$includes/etc/samurai-variant"

    # 3. Stage the selected variant, if it has material of its own.
    src="$variant_root/$variant"
    if [[ ! -d "$src" ]]; then
        [[ "$variant" == desktop ]] \
            || die "variant '$variant' has no directory at $src"
        log "Staged variant 'desktop' (no material of its own)"
        return 0
    fi
    if [[ -d "$src/archives" ]]; then
        install -d -m 0755 "$build_dir/config/archives"
        cp -a "$src/archives/." "$build_dir/config/archives/"
    fi
    if [[ -d "$src/package-lists" ]]; then
        install -d -m 0755 "$build_dir/config/package-lists"
        cp -a "$src"/package-lists/* "$build_dir/config/package-lists/"
    fi
    if [[ -d "$src/includes.chroot" ]]; then
        (cd "$src" && cp -a includes.chroot/. "$includes/")
    fi
    log "Staged variant '$variant' into the live-build config"
}

# A fake tree: one base package list that belongs to every variant, one tool
# list and one archive set that belong to `security`, and one shipped config file
# that neither variant owns and staging must never touch.
make_fixture() {
    local root=$1
    install -d -m 0755 "$root/variants/security/package-lists" \
        "$root/variants/security/archives" \
        "$root/variants/security/includes.chroot/etc/calamares" \
        "$root/config/package-lists" \
        "$root/config/includes.chroot/etc/apt/preferences.d"
    printf 'base\n' > "$root/config/package-lists/samurai.list.chroot"
    printf 'base config, owned by the repository\n' \
        > "$root/config/includes.chroot/etc/apt/preferences.d/99samurai"
    printf 'nmap\nmetasploit-framework\n' \
        > "$root/variants/security/package-lists/samurai-security.list.chroot"
    printf 'deb https://archive.kali.org/kali kali-rolling main\n' \
        > "$root/variants/security/archives/kali.list.chroot"
    printf 'Package: *\nPin: release n=kali-rolling\nPin-Priority: 50\n' \
        > "$root/variants/security/archives/kali.pref.chroot"
    printf '# not a key\n' > "$root/variants/security/archives/kali.key.fpr"
    printf 'branding\n' > "$root/variants/security/includes.chroot/etc/calamares/branding.desc"
}

self_test() {
    local root fail=0 rel
    root=$(mktemp -d)
    SELFTEST_TMP=$root

    make_fixture "$root"

    # desktop: nothing of its own, so the base tree must come out unchanged and
    # the security material must not be reachable from it.
    stage desktop "$root" >/dev/null
    if [[ -e "$root/config/archives" ]]; then
        log "FAIL: a desktop build still has config/archives"
        fail=1
    fi
    if [[ -e "$root/config/package-lists/samurai-security.list.chroot" ]]; then
        log "FAIL: a desktop build installs the security package list"
        fail=1
    fi
    if [[ -e "$root/config/includes.chroot/etc/calamares/branding.desc" ]]; then
        log "FAIL: a desktop build shipped the security variant's file"
        fail=1
    fi
    if ! grep -q '^desktop$' "$root/config/includes.chroot/etc/samurai-variant"; then
        log "FAIL: the desktop image does not say which variant it is"
        fail=1
    fi
    if [[ ! -f "$root/config/package-lists/samurai.list.chroot" ]]; then
        log "FAIL: staging removed the base package list, which no variant owns"
        fail=1
    fi
    if [[ ! -f "$root/config/includes.chroot/etc/apt/preferences.d/99samurai" ]]; then
        log "FAIL: staging removed a config file that belongs to the repository"
        fail=1
    fi
    ((fail == 0)) && log "ok - a desktop build stages exactly the base tree"

    # security: the archive set, the tool list and the variant marker appear.
    make_fixture "$root"
    stage security "$root" >/dev/null
    for rel in config/archives/kali.list.chroot config/archives/kali.pref.chroot \
        config/package-lists/samurai-security.list.chroot \
        config/includes.chroot/etc/calamares/branding.desc; do
        if [[ ! -f "$root/$rel" ]]; then
            log "FAIL: a security build is missing $rel"
            fail=1
        fi
    done
    # An extension live-build does not glob must not be mistaken for one it does.
    if [[ -e "$root/config/archives/kali.key.fpr.chroot" ]]; then
        log "FAIL: staging renamed a file live-build never asked for"
        fail=1
    fi
    if ! grep -q '^security$' "$root/config/includes.chroot/etc/samurai-variant"; then
        log "FAIL: the security image does not say which variant it is"
        fail=1
    fi
    ((fail == 0)) && log "ok - a security build stages the archive, the pin and the tool list"

    # The switch that matters: security then desktop, with no clean in between,
    # because that is what happens when one machine builds both images.
    make_fixture "$root"
    stage security "$root" >/dev/null
    stage desktop "$root" >/dev/null
    if [[ -e "$root/config/archives" ||
          -e "$root/config/package-lists/samurai-security.list.chroot" ||
          -e "$root/config/includes.chroot/etc/calamares/branding.desc" ]]; then
        log "FAIL: a desktop build after a security one inherited its material"
        fail=1
    fi
    if ! grep -q '^desktop$' "$root/config/includes.chroot/etc/samurai-variant"; then
        log "FAIL: the variant marker still said security after a desktop stage"
        fail=1
    fi
    ((fail == 0)) && log "ok - switching variants leaves nothing of the previous one behind"

    # In a subshell, because `die` exits the process: wrapped around the bare
    # call, an `if !` would take the whole self-test down with the error it was
    # checking for.
    if ! (stage nonexistent "$root" >/dev/null 2>&1); then
        log "ok - an unknown variant is refused rather than built as desktop"
    else
        log "FAIL: an unknown variant was accepted"
        fail=1
    fi

    ((fail == 0)) || die "stage-variant self-test failed"
    log "stage-variant self-test passed"
}

main() {
    local variant=${SAMURAI_VARIANT:-desktop} build_dir="" test=0
    while (($#)); do
        case "$1" in
            --variant)
                (($# >= 2)) || die "--variant needs a name"
                variant=$2
                shift 2
                ;;
            --variant=*) variant=${1#--variant=}; shift ;;
            --build-dir)
                (($# >= 2)) || die "--build-dir needs a path"
                build_dir=$2
                shift 2
                ;;
            --build-dir=*) build_dir=${1#--build-dir=}; shift ;;
            --self-test) test=1; shift ;;
            -h|--help) usage; return 0 ;;
            *) die "Unknown option: $1 (run: bash build/stage-variant.sh --help)" ;;
        esac
    done

    if ((test)); then
        self_test
        return 0
    fi

    [[ -n "$build_dir" ]] || die "--build-dir is required (or run --self-test)"
    case "$variant" in
        desktop|security) ;;
        *) die "unknown variant '$variant' (expected desktop or security)" ;;
    esac
    stage "$variant" "$build_dir"
}

main "$@"
