#!/usr/bin/env bash
# Fast, dependency-light smoke tests for the Samurai scripts.
set -euo pipefail

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd)
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

pass=0
fail() { printf 'FAIL: %s\n' "$*" >&2; exit 1; }
ok() { pass=$((pass + 1)); printf 'ok %d - %s\n' "$pass" "$*"; }

assert_contains() {
    local haystack="$1" needle="$2" label="$3"
    [[ "$haystack" == *"$needle"* ]] || fail "$label: expected '$needle' in '$haystack'"
}

assert_file() {
    [[ -f "$1" ]] || fail "expected file: $1"
}

# Shell files: every file in samurai/scripts, plus named shell files elsewhere.
find_shell_files() {
    find "$REPO_ROOT/samurai/scripts" -type f
    find "$REPO_ROOT/scripts" "$REPO_ROOT/build" "$REPO_ROOT/tests" -type f \
        \( -name '*.sh' -o -name 'config' -o -name '*.hook.chroot' -o -name '*.hook.binary' \)
}

# 1. Syntax checks
while IFS= read -r file; do
    bash -n "$file" || fail "syntax error: $file"
done < <(find_shell_files)
ok "all shell scripts parse"

# 2. ShellCheck when available
if command -v shellcheck >/dev/null 2>&1; then
    while IFS= read -r file; do
        shellcheck -x "$file" || fail "shellcheck: $file"
    done < <(find_shell_files)
    ok "shellcheck passed"
else
    printf 'skip - shellcheck not installed\n'
fi

# 3. Python syntax and the install harness's serial-console self-test
if command -v python3 >/dev/null 2>&1; then
    python3 - "$REPO_ROOT/scripts/use-heretic.py" "$REPO_ROOT/build/install-test.py" <<'PY'
import ast
import pathlib
import sys

for path in sys.argv[1:]:
    ast.parse(pathlib.Path(path).read_text())
PY
    python3 "$REPO_ROOT/build/install-test.py" --self-test >/dev/null
    ok "python scripts parse and the install harness self-test passes"
fi

# 4. AI CLI usage, default model, and file credentials
HOME_DIR="$TMP/home"
mkdir -p "$HOME_DIR"
export SAMURAI_AI_FORCE_FILE=1

out=$(HOME="$HOME_DIR" bash "$REPO_ROOT/samurai/scripts/samurai-ai")
assert_contains "$out" "Samurai AI Assistant" "ai usage"

HOME="$HOME_DIR" bash "$REPO_ROOT/samurai/scripts/samurai-ai" set-default "llama3.2:3b" >/dev/null
assert_file "$HOME_DIR/.config/samurai/ai-default"
[[ "$(HOME="$HOME_DIR" bash "$REPO_ROOT/samurai/scripts/samurai-ai" get-default)" == "llama3.2:3b" ]] \
    || fail "get-default returned the wrong value"
ok "default model persists"

mkdir -p "$TMP/bin"
cat > "$TMP/bin/ollama" <<'EOF'
#!/bin/sh
printf 'ollama-args:%s\n' "$*"
EOF
chmod 0755 "$TMP/bin/ollama"
out=$(PATH="$TMP/bin:$PATH" HOME="$HOME_DIR" bash "$REPO_ROOT/samurai/scripts/samurai-ai" chat hello)
[[ "$out" == "ollama-args:run llama3.2:3b hello" ]] || fail "chat did not call 'ollama run' with the default model: $out"
ok "chat uses ollama run and the default model"

HOME="$HOME_DIR" bash "$REPO_ROOT/samurai/scripts/samurai-ai" credentials set openai sk-test >/dev/null
[[ "$(HOME="$HOME_DIR" bash "$REPO_ROOT/samurai/scripts/samurai-ai" credentials get openai)" == "sk-test" ]] \
    || fail "credential get failed"
HOME="$HOME_DIR" bash "$REPO_ROOT/samurai/scripts/samurai-ai" credentials remove openai >/dev/null
if [[ -f "$HOME_DIR/.config/samurai/credentials" ]] && grep -q 'openai' "$HOME_DIR/.config/samurai/credentials"; then
    fail "credential remove left data behind"
fi
ok "file credential fallback round-trips"

# 5. Theme CLI installs a real .colors file and supports the set alias
HOME="$HOME_DIR" SAMURAI_THEME_DIR="$REPO_ROOT/samurai/themes" \
    bash "$REPO_ROOT/samurai/scripts/samurai-theme" set kuro >/dev/null
assert_file "$HOME_DIR/.local/share/color-schemes/samurai-kuro.colors"
grep -q '^ColorScheme=samurai-kuro$' "$HOME_DIR/.local/share/color-schemes/samurai-kuro.colors" \
    || fail "Kuro scheme has the wrong ColorScheme key"
[[ "$(HOME="$HOME_DIR" bash "$REPO_ROOT/samurai/scripts/samurai-theme" status | head -n 1)" == "Selected theme: kuro" ]] \
    || fail "theme status did not report kuro"
ok "theme installs to the KDE color-schemes directory"

# 5b. Both KDE schemes parse and carry the expected scheme name
if command -v python3 >/dev/null 2>&1; then
    python3 - "$REPO_ROOT" <<'PY'
import configparser
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
for theme in ("kuro", "shiro"):
    path = root / "samurai" / "themes" / theme / f"samurai-{theme}.colors"
    parser = configparser.ConfigParser()
    parser.read(path)
    assert parser["General"]["ColorScheme"] == f"samurai-{theme}", path
    for section in ("Colors:Window", "Colors:View", "Colors:Button"):
        assert parser.has_section(section), f"{path}: missing {section}"
PY
    ok "KDE color schemes parse"
fi

# 5c. Calamares branding and package wiring are present
branding="$REPO_ROOT/build/config/includes.chroot/etc/calamares/branding/samurai"
assert_file "$branding/branding.desc"
for asset in productLogo.png productIcon.png productWelcome.png slide1.png show.qml; do
    assert_file "$branding/$asset"
done
grep -q '^componentName:.*samurai$' "$branding/branding.desc" || fail "Calamares component name is missing"
grep -q '^calamares$' "$REPO_ROOT/build/config/package-lists/samurai.list.chroot" || fail "calamares is not installed"
grep -q '^calamares-settings-debian$' "$REPO_ROOT/build/config/package-lists/samurai.list.chroot" \
    || fail "calamares-settings-debian is not installed"
for pkg in grub-pc-bin grub-efi-amd64-bin efibootmgr squashfs-tools; do
    grep -q "^$pkg$" "$REPO_ROOT/build/config/package-lists/samurai.list.chroot" \
        || fail "$pkg is not installed for the installer"
done
grep -q 'branding: samurai' "$REPO_ROOT/build/config/hooks/normal/0100-samurai.hook.chroot" \
    || fail "Calamares branding is not selected"
assert_file "$REPO_ROOT/build/verify-iso.sh"
assert_file "$REPO_ROOT/build/config/hooks/normal/0100-serial.hook.binary"
assert_file "$REPO_ROOT/build/config/hooks/normal/0110-branding.hook.chroot"
assert_file "$REPO_ROOT/build/config/hooks/normal/0200-branding.hook.binary"
for splash in \
    "$REPO_ROOT/build/config/bootloaders/isolinux/splash.png" \
    "$REPO_ROOT/build/config/bootloaders/grub-pc/splash.png" \
    "$REPO_ROOT/build/config/includes.chroot/usr/share/samurai/boot/grub-splash.png"; do
    assert_file "$splash"
done

# 5d. Wallpapers and the theme manager that applies them
wallpaper_dir="$REPO_ROOT/build/config/includes.chroot/usr/share/backgrounds/samurai"
assert_file "$wallpaper_dir/kuro.jpg"
assert_file "$wallpaper_dir/shiro.jpg"
wallpaper_count=$(find "$wallpaper_dir" -type f -name '*.jpg' | wc -l)
(( wallpaper_count >= 20 )) || fail "expected at least 20 wallpapers, found $wallpaper_count"
assert_file "$REPO_ROOT/build/make-wallpapers.py"
grep -q 'plasma-apply-wallpaperimage' "$REPO_ROOT/samurai/scripts/samurai-theme" \
    || fail "samurai-theme does not apply the theme wallpaper"
grep -q 'install -d -m 0755 /boot/grub' \
    "$REPO_ROOT/build/config/hooks/normal/0110-branding.hook.chroot" \
    || fail "the chroot branding hook does not create /boot/grub for the installer"
# The single quotes are intentional: this matches the literal text the hook
# writes into isolinux.cfg, not a value expanded here.
# shellcheck disable=SC2016
grep -q 'menu title Samurai Linux \${menu_version}' \
    "$REPO_ROOT/build/config/hooks/normal/0200-branding.hook.binary" \
    || fail "the binary branding hook does not rename the boot menu with the build date"
grep -q 'date -u +%Y.%m.%d' "$REPO_ROOT/build/config/hooks/normal/0200-branding.hook.binary" \
    || fail "the boot menu title is not derived from the build date"
grep -q 'GRUB_BACKGROUND' "$REPO_ROOT/build/config/hooks/normal/0110-branding.hook.chroot" \
    || fail "the chroot branding hook does not set the GRUB background"
grep -q 'usr/share/backgrounds/samurai' "$REPO_ROOT/build/verify-iso.sh" \
    || fail "ISO verification does not check the desktop wallpapers"
grep -q 'os-release' "$REPO_ROOT/build/verify-iso.sh" \
    || fail "ISO verification does not check distribution branding"
assert_file "$REPO_ROOT/build/install-test.py"
assert_file "$REPO_ROOT/build/install-test.sh"
# YAML flow sequences split on commas, so the console argument must stay quoted
# or it reaches the installed kernel as two parameters (ttyS0 + 115200n8).
grep -q '"console=ttyS0,115200n8"' "$REPO_ROOT/build/install-test.py" \
    || fail "the install test overlay does not quote the serial console parameter"
grep -q 'uses: ./.github/workflows/install-test.yml' "$REPO_ROOT/.github/workflows/build-iso-hosted.yml" \
    || fail "the hosted ISO build does not run the install test"
if git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    for hook in 0110-branding.hook.chroot 0200-branding.hook.binary \
        0120-security.hook.chroot 0130-profiles.hook.chroot; do
        if git -C "$REPO_ROOT" check-ignore -q "build/config/hooks/normal/$hook"; then
            fail "build/config/hooks/normal/$hook is ignored by git"
        fi
    done
fi
grep -Fq 'timeout[[:space:]]+0$/timeout 50/' "$REPO_ROOT/build/config/hooks/normal/0100-serial.hook.binary" \
    || fail "the live ISO boot menu does not auto-boot"
grep -q 'bash build/verify-iso.sh' "$REPO_ROOT/.github/workflows/build-iso-hosted.yml" \
    || fail "hosted workflow does not verify ISO contents"
ok "Calamares installer configuration is present"

# 6. Gaming launcher strips the subcommand before passing arguments
mkdir -p "$TMP/bin"
cat > "$TMP/bin/steam" <<'EOF'
#!/bin/sh
printf 'steam-args:%s\n' "$*"
EOF
chmod 0755 "$TMP/bin/steam"
out=$(PATH="$TMP/bin:$PATH" HOME="$HOME_DIR" bash "$REPO_ROOT/samurai/scripts/samurai-gaming" steam --foo)
[[ "$out" == "steam-args:--foo" ]] || fail "steam launcher passed the wrong args: $out"
ok "gaming launcher forwards only user arguments"

# 6b. Developer profiles name real packages and refuse to guess
PROFILE_NAMES=(c python web rust go java databases containers docker virtualization debug ml)
profile_list=$(bash "$REPO_ROOT/samurai/scripts/samurai-profile" list)
for expected in "${PROFILE_NAMES[@]}"; do
    assert_contains "$profile_list" "$expected" "profile list"
done
for profile in "${PROFILE_NAMES[@]}"; do
    # ml deliberately has no apt set; every other profile must resolve to names.
    if [[ "$profile" == ml ]]; then
        continue
    fi
    names=$(bash "$REPO_ROOT/samurai/scripts/samurai-profile" packages "$profile")
    [[ -n "$names" ]] || fail "profile $profile declares no packages"
done
if bash "$REPO_ROOT/samurai/scripts/samurai-profile" packages nonexistent >/dev/null 2>&1; then
    fail "samurai-profile accepted an unknown profile"
fi
bash "$REPO_ROOT/samurai/scripts/samurai-profile" show ml | grep -q 'venv' \
    || fail "the ml profile does not describe how to get a working environment"
ok "developer profiles declare packages or explain why they do not"

# 6c. Recovery refuses to replace a whole /etc
mkdir -p "$TMP/rec/2026-01-01T000000Z"
if SAMURAI_RECOVERY_STORE="$TMP/rec" \
    bash "$REPO_ROOT/samurai/scripts/samurai-recovery" restore-etc 2026-01-01T000000Z >/dev/null 2>&1; then
    fail "restore-etc accepted a request to restore with no files named"
fi
if SAMURAI_RECOVERY_STORE="$TMP/rec" \
    bash "$REPO_ROOT/samurai/scripts/samurai-recovery" restore-etc 2026-01-01T000000Z etc/passwd >/dev/null 2>&1; then
    fail "restore-etc accepted a relative path"
fi
SAMURAI_RECOVERY_STORE="$TMP/rec" bash "$REPO_ROOT/samurai/scripts/samurai-recovery" --help | grep -q 'restore-packages' \
    || fail "samurai-recovery does not document package rollback"
ok "recovery commands fail closed on ambiguous input"

# 6d. The profile build hook resolves every profile against the archive
hook="$REPO_ROOT/build/config/hooks/normal/0130-profiles.hook.chroot"
assert_file "$hook"
grep -q 'samurai-profile' "$hook" || fail "the profile hook does not use samurai-profile"
grep -q -- '-s --no-install-recommends' "$hook" \
    || fail "the profile hook does not simulate the install instead of performing it"
grep -q 'usr/local/bin/samurai-profile' "$REPO_ROOT/build/verify-iso.sh" \
    || fail "ISO verification does not check that samurai-profile ships in the image"
grep -q 'usr/local/bin/samurai-recovery' "$REPO_ROOT/build/verify-iso.sh" \
    || fail "ISO verification does not check that samurai-recovery ships in the image"
ok "every shipped profile is resolver-tested at build time"

# 6e. The security policy ships as configured state, and both gates read it back
assert_file "$REPO_ROOT/build/config/hooks/normal/0120-security.hook.chroot"
for policy in \
    etc/nftables.conf \
    etc/sudoers.d/90samurai \
    etc/apt/preferences.d/99samurai \
    etc/apt/apt.conf.d/20samurai-security \
    etc/systemd/journald.conf.d/99samurai.conf; do
    assert_file "$REPO_ROOT/build/config/includes.chroot/$policy"
    grep -qF "$policy" "$REPO_ROOT/build/verify-iso.sh" \
        || fail "ISO verification does not check /$policy"
done
grep -q 'table inet' "$REPO_ROOT/build/config/includes.chroot/etc/nftables.conf" \
    || fail "the firewall filters only one address family"
grep -q 'policy drop' "$REPO_ROOT/build/config/includes.chroot/etc/nftables.conf" \
    || fail "the firewall does not default-drop inbound traffic"
if grep -Ev '^[[:space:]]*#' "$REPO_ROOT/build/config/includes.chroot/etc/sudoers.d/90samurai" |
    grep -q 'NOPASSWD'; then
    fail "the shipped sudoers fragment grants passwordless root"
fi
# The image rebrands DISTRIB_ID, so Debian's "${distro_id}-based Allowed-Origins
# matches nothing here. The origin has to be named literally and asserted again
# after install, or automatic upgrades are configured, enabled and inert.
grep -q '"Debian:trixie-security"' \
    "$REPO_ROOT/build/config/includes.chroot/etc/apt/apt.conf.d/20samurai-security" \
    || fail "20samurai-security names no literal security origin"
grep -q 'Debian:trixie-security' "$REPO_ROOT/build/install-test.py" \
    || fail "the install test no longer asserts the security origin the image names"
# The hook must derive the origin from the archive metadata rather than trust
# either side of that pair to still be true.
grep -qF '/^Origin: /' "$REPO_ROOT/build/config/hooks/normal/0120-security.hook.chroot" \
    || fail "the security hook no longer reads the archive's own Origin field"
for gate in nftables apparmor apt-daily-upgrade.timer NOPASSWD; do
    grep -q "$gate" "$REPO_ROOT/build/install-test.py" \
        || fail "the install test does not verify $gate on the installed system"
done
grep -q 'packages.tsv' "$REPO_ROOT/build/verify-iso.sh" \
    || fail "ISO verification does not produce the installed-package manifest"
ok "security defaults are configured in the image and verified after install"

# 7. Post-build helpers fail clearly without arguments
if bash "$REPO_ROOT/scripts/analyze-iso.sh" >/dev/null 2>&1; then
    fail "analyze-iso.sh should fail without an ISO path"
fi
bash "$REPO_ROOT/scripts/post-build-workflow.sh" --help >/dev/null
ok "post-build helpers have usable interfaces"

# 8. live-build config emits the documented option names
mkdir -p "$TMP/fakelb" "$TMP/lbwork"
cat > "$TMP/fakelb/lb" <<'EOF'
#!/bin/sh
printf '%s\n' "$*"
EOF
chmod 0755 "$TMP/fakelb/lb"
out=$(cd "$TMP/lbwork" && PATH="$TMP/fakelb:$PATH" bash "$REPO_ROOT/build/auto/config")
assert_contains "$out" "--architecture amd64" "config architecture"
assert_contains "$out" "--binary-image iso-hybrid" "config binary image"
assert_contains "$out" "--debian-installer none" "config installer"
assert_contains "$out" "--archive-areas main contrib non-free-firmware" "config archive areas"
ok "live-build config uses valid option names"

printf '\nAll %d smoke checks passed.\n' "$pass"
