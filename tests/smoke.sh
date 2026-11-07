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

# 1b. A quoted message must end its statement: a bare word after the closing
# quote becomes one more argument to the reporting call, and the command that
# word began never runs at all. This caught a manifest writer in samurai-profile
# that was reached only after apt had already failed.
while IFS= read -r file; do
    if grep -Eq '(die|warn|log)[[:space:]]+"[^"]*"[[:space:]]+[a-z_]' "$file"; then
        fail "a message call in $file swallowed the command that followed it"
    fi
done < <(find_shell_files)
ok "no message call swallowed the statement after it"

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
    # A call to a method the class does not have parses fine, passes pyflakes,
    # and only shows up when that line runs: run 41988375810 lost its whole CI
    # cycle to "InstallerTest object has no attribute write_file" because the
    # rewrite called the serial console's helper on the harness instead. Every
    # self.<name>(...) is therefore checked against what that class really
    # defines - methods plus attributes assigned anywhere in the module.
    python3 - "$REPO_ROOT/build/install-test.py" "$REPO_ROOT/scripts/use-heretic.py" <<'PY'
import ast
import pathlib
import sys

bad = []
for path in sys.argv[1:]:
    tree = ast.parse(pathlib.Path(path).read_text())
    assigned = {
        node.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Attribute)
        and isinstance(node.value, ast.Name)
        and node.value.id == "self"
        and isinstance(node.ctx, ast.Store)
    }
    for cls in [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]:
        own = {
            f.name
            for f in cls.body
            if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef))
        }
        for node in ast.walk(cls):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "self"
            ):
                name = node.func.attr
                if name not in own and name not in assigned:
                    bad.append(f"{path}:{node.lineno}: self.{name}() is not defined")
if bad:
    print("\n".join(bad))
    sys.exit(1)
PY
    ok "every method the harness calls on itself exists"
    # The harness types shell into a serial console, and a quote that closes the
    # wrong way there is a syntax error the guest reports on a line nobody reads
    # until minutes into a CI cycle. So parse every literal command string now,
    # with the same shell the guest runs.
    python3 - "$REPO_ROOT/build/install-test.py" <<'PY'
import ast
import pathlib
import subprocess
import sys
import tempfile

bad = []
for path in sys.argv[1:]:
    tree = ast.parse(pathlib.Path(path).read_text())
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr in {"command", "write_file", "background"}
            and node.args
        ):
            continue
        try:
            script = ast.literal_eval(node.args[0])
        except Exception:
            continue  # built from f-strings at runtime; checked where it runs
        if not isinstance(script, str) or not script.strip():
            continue
        with tempfile.NamedTemporaryFile("w", suffix=".sh", delete=False) as fh:
            fh.write(script)
            name = fh.name
        result = subprocess.run(["sh", "-n", name], capture_output=True, text=True)
        pathlib.Path(name).unlink()
        if result.returncode:
            bad.append(f"{path}:{node.lineno}: {result.stderr.strip()}")
if bad:
    print("\n".join(bad))
    sys.exit(1)
PY
    ok "every shell command the harness types parses"
    # A name that is never assigned parses fine, self-tests fine, and then stops
    # a three-hour CI install run in its tracks: install-test.py died with
    # "name 'tail' is not defined" after a rewrite deleted the line that set it.
    # Only undefined names are fatal here; other lint opinions stay optional.
    if python3 -m pyflakes --version >/dev/null 2>&1; then
        undef=$(python3 -m pyflakes "$REPO_ROOT/scripts/use-heretic.py" \
            "$REPO_ROOT/build/install-test.py" 2>&1 | grep "undefined" || true)
        [ -z "$undef" ] || { printf 'not ok - python names that are used but never set:\n%s\n' "$undef"; exit 1; }
        ok "no python name is used without being defined"
    else
        printf 'skip - pyflakes not installed\n'
    fi
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
# Exact, not a floor: README and the desktop docs publish this number, and a
# count nobody holds still is a claim that drifts out of date silently. When this
# fails deliberately, update the published figure in README.md,
# samurai/docs/desktop-and-themes.md and build/README.md.
(( wallpaper_count == 22 )) || fail "the documents publish 22 wallpapers, the tree has $wallpaper_count"
assert_file "$REPO_ROOT/build/make-wallpapers.py"
grep -q 'plasma-apply-wallpaperimage' "$REPO_ROOT/samurai/scripts/samurai-theme" \
    || fail "samurai-theme does not apply the theme wallpaper"

# 5d-1. The wallpaper call must not inherit Plasma's 25 s default D-Bus reply
# timeout: a software-rendered first login can still be loading plasmashell's
# script engine then. samurai-theme sends the same evaluateScript call itself
# with a longer deadline, so a fake dbus-send proves the call is made at all.
mkdir -p "$TMP/wallpapers"
: > "$TMP/wallpapers/kuro.jpg"
cat > "$TMP/bin/dbus-send" <<'EOF'
#!/bin/sh
printf '%s\n' "$*" > "$FAKE_DBUS_LOG"
exit 0
EOF
chmod 0755 "$TMP/bin/dbus-send"
dbus_log="$TMP/dbus-args.log"
theme_out=$(HOME="$HOME_DIR" SAMURAI_THEME_DIR="$REPO_ROOT/samurai/themes" \
    SAMURAI_WALLPAPER_DIR="$TMP/wallpapers" FAKE_DBUS_LOG="$dbus_log" \
    PATH="$TMP/bin:$PATH" bash "$REPO_ROOT/samurai/scripts/samurai-theme" set kuro 2>&1)
assert_contains "$theme_out" "Applied wallpaper kuro.jpg" "theme wallpaper"
grep -q 'org.kde.PlasmaShell.evaluateScript' "$dbus_log" \
    || fail "samurai-theme did not ask plasmashell to change the wallpaper"
grep -q "file://$TMP/wallpapers/kuro.jpg" "$dbus_log" \
    || fail "the wallpaper D-Bus call does not name the selected image"
ok "the theme wallpaper call outlives Plasma's default D-Bus timeout"
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
# A snapshot named the way `list` and `verify` print it - its absolute path -
# has to be the snapshot, not one of the files. Run 42121878962 lost its whole
# installed-system phase because an absolute first argument was sorted into the
# file list and tar answered "Not found in archive".
snapshot_abs="$TMP/rec/2026-01-01T000000Z"
if out=$(SAMURAI_RECOVERY_STORE="$TMP/rec" \
        bash "$REPO_ROOT/samurai/scripts/samurai-recovery" restore-etc "$snapshot_abs" 2>&1); then
    fail "restore-etc accepted a snapshot with no files to restore"
fi
assert_contains "$out" "needs at least one file" \
    "an absolute snapshot path must be the selector, not a file: $out"
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
    etc/apt/sources.list.d/samurai-security.list \
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

# 6f. Performance claims require a measurement. The harness must exist, must be
# the thing the install test runs, and docs/performance.md must not have grown
# an unmeasured number back - the section it replaced invented a boot time, an
# idle-memory figure and a CPU load out of nothing.
perf_script="$REPO_ROOT/build/measure-performance.sh"
[ -f "$perf_script" ] || fail "the performance harness is missing"
grep -q 'unavailable' "$perf_script" \
    || fail "the performance harness has no honest fallback for a metric it cannot measure"
grep -q 'label\\tvalue\\tunit\\tcommand' "$perf_script" \
    || fail "the performance harness no longer pairs each value with the command that produced it"
grep -q 'measure-performance.sh' "$REPO_ROOT/build/install-test.py" \
    || fail "the install test never runs the performance harness"
for metric in memory_used cpu_idle units_enabled services_running sha256_mib_per_s rootfs_used; do
    grep -q "$metric" "$REPO_ROOT/build/install-test.py" \
        || fail "the install test does not gate the $metric measurement"
done
for perf_doc in "$REPO_ROOT/samurai/docs/performance.md" "$REPO_ROOT/samurai/docs/testing.md"; do
    if grep -Eq 'Boot time:[[:space:]]*[0-9]|Idle memory:[[:space:]]*[0-9]|CPU utilization:[[:space:]]*[0-9]' "$perf_doc"; then
        fail "$(basename "$perf_doc") publishes a performance number that no measurement produced"
    fi
done
for phrase in 'power-profiles-daemon' 'No compositor tuning' 'measure-performance.sh'; do
    grep -qi "$phrase" "$REPO_ROOT/samurai/docs/performance.md" \
        || fail "docs/performance.md no longer states the status of: $phrase"
done
ok "performance numbers can only come from the harness"

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
# The security pocket ships as a file, not as a live-build option. live-build
# rewrites /etc/apt/sources.list around the squashfs packing, so asking it for a
# binary security mirror is not a guarantee the installed system has one: runs
# 41447034423 and 41452920694 both built images whose shipped sources named no
# security archive, the second with --security true already set. --security false
# is deliberate - it stops live-build writing a second entry beside ours, which
# apt would report as a duplicated source on every update.
assert_contains "$out" "--security false" "config leaves the security archive to us"
if grep -vE '^[[:space:]]*#' "$REPO_ROOT/build/auto/config" |
    grep -qE -- '--mirror-(chroot|binary)-security|--security true'; then
    fail "auto/config asks live-build for the security archive again; it ships from includes.chroot"
fi
ok "live-build config uses valid option names"

# 9. The rest of the required test categories need a gate that can regress by
# silence: each one is checked by a script somewhere else, and if that check is
# deleted the pipeline still goes green. This section keeps them named.
for prereq in 'A Linux build host is required' 'Only x86_64 is supported' \
    'Missing build tool' 'Need at least'; do
    grep -q "$prereq" "$REPO_ROOT/build/build.sh" \
        || fail "build.sh no longer detects the prerequisite: $prereq"
done
grep -Eq 'for tool in lb debootstrap xorriso mksquashfs' "$REPO_ROOT/build/build.sh" \
    || fail "build.sh no longer checks the tools the build needs"
# --check has to actually refuse. An impossible disk requirement is the one gate
# that behaves the same on every host, so the check is run rather than read.
if SAMURAI_MIN_DISK_GB=100000000 bash "$REPO_ROOT/build/build.sh" --check >/dev/null 2>&1; then
    fail "build.sh --check accepted a host that cannot possibly have the disk it needs"
fi
ok "build prerequisite detection runs and refuses an unprepared host"

# Kernel and boot configuration: auto-boot timeout, serial console on both
# bootloaders, and the same parameter in the installed system's grub config.
for boot_check in "^timeout" "console=ttyS0,115200n8" "etc/default/grub"; do
    grep -qF "$boot_check" "$REPO_ROOT/build/verify-iso.sh" \
        || fail "ISO verification no longer checks the boot configuration: $boot_check"
done
grep -q 'bash build/qemu-test.sh' "$REPO_ROOT/.github/workflows/build-iso-hosted.yml" \
    || fail "the hosted build no longer boots the image it produced"
ok "boot configuration and the ISO boot test are gated"

# Checksum and signature verification: the ISO, its checksum and the package
# manifest each need a detached signature, checked against the repository key
# whose fingerprint is cross-read rather than trusted.
for artifact in "sign \"\$iso\"" "sign \"\$iso.sha256\"" "sign \"\$manifest\""; do
    grep -qF "$artifact" "$REPO_ROOT/.github/workflows/build-iso-hosted.yml" \
        || fail "the hosted build no longer signs an artifact: $artifact"
done
for gate in "samurai-release.asc" "samurai-release.fpr" "*.packages.tsv"; do
    grep -qF "$gate" "$REPO_ROOT/.github/workflows/install-test.yml" \
        || fail "the install test no longer verifies the release artifact: $gate"
done
ok "release artifacts can only be consumed through a verified signature"

# Update and recovery workflows, as configured state on the installed system.
for updater in "apt-daily-upgrade.timer" "unattended upgrades" "Allowed-Origins" \
    "upgrade origins"; do
    grep -qF "$updater" "$REPO_ROOT/build/install-test.py" \
        || fail "the install test does not verify the update workflow: $updater"
done
grep -qF "samurai-recovery snapshot" "$REPO_ROOT/build/install-test.py" \
    || fail "the install test never runs the recovery snapshot workflow"
ok "update and recovery workflows are verified on the installed system"

# 22. The manifest validator has to fail in the right direction. Written as
# `if awk 'END { exit bad }'; then die`, it rejects a good file and accepts a bad
# one, because awk signals a problem with exit 1 while `if` runs its body on 0 -
# that inversion cost build 41528368817, so both directions are pinned here.
printf 'foo\t1.0\tamd64\nbar\t2.0\tall\n' > "$TMP/good.packages.tsv"
bash "$REPO_ROOT/build/check-manifest.sh" "$TMP/good.packages.tsv" >/dev/null \
    || fail "the manifest validator rejects a well formed manifest"
printf 'foo\t1.0\tamd64\nbar 2.0 all\n' > "$TMP/bad.packages.tsv"
if bash "$REPO_ROOT/build/check-manifest.sh" "$TMP/bad.packages.tsv" >/dev/null 2>&1; then
    fail "the manifest validator accepts a row that is not three tab-separated fields"
fi
: > "$TMP/empty.packages.tsv"
if bash "$REPO_ROOT/build/check-manifest.sh" "$TMP/empty.packages.tsv" >/dev/null 2>&1; then
    fail "the manifest validator accepts an empty manifest"
fi
printf '# noarch: installed with no Architecture field\nfoo\t1.0\tamd64\n' \
    > "$TMP/partial.packages.tsv"
if bash "$REPO_ROOT/build/check-manifest.sh" "$TMP/partial.packages.tsv" >/dev/null 2>&1; then
    fail "the manifest validator accepts an installed record with no version or architecture"
fi
if bash "$REPO_ROOT/build/check-manifest.sh" >/dev/null 2>&1; then
    fail "the manifest validator should require a manifest path"
fi
ok "the manifest validator accepts good manifests and rejects broken ones"

# 23. The signing step's fingerprint pipeline has to run on the gpg that is
# actually installed. Build 41539298221 produced three good signatures and then
# died on `gpg --fingerprints`, which GnuPG 2.5 removed, so the extraction is run
# here against the key the repository publishes rather than merely read.
if command -v gpg >/dev/null 2>&1; then
    keyring="$TMP/gnupg"
    mkdir -p "$keyring"
    chmod 700 "$keyring"
    if ! GNUPGHOME="$keyring" gpg --batch --import "$REPO_ROOT/samurai/keys/samurai-release.asc" \
        >/dev/null 2>&1; then
        fail "gpg could not import samurai/keys/samurai-release.asc"
    fi
    listed=$(GNUPGHOME="$keyring" gpg --batch --with-colons --list-keys \
        | awk -F: '$1 == "fpr" { print $10; exit }')
    documented=$(tr -d '[:space:]' < "$REPO_ROOT/samurai/keys/samurai-release.fpr")
    [[ "$listed" == "$documented" ]] \
        || fail "the published key reports fingerprint ${listed:-none}, not $documented"
    if grep -rn -- '--fingerprints' "$REPO_ROOT/.github/workflows" >/dev/null; then
        fail "a workflow passes --fingerprints to gpg, an option GnuPG 2.5 removed"
    fi
    ok "the release key fingerprint is read the way the signing step reads it"
else
    printf 'skip - gpg not installed, the fingerprint pipeline was not run\n'
fi

# 25. The check that the ISO's kernel and its modules tree agree has to be run,
# not read. It discarded two good ISOs while only being looked at: first as
# `grep | grep -q`, where grep -q leaves on its first match, the upstream grep
# dies of SIGPIPE and pipefail reports a passed check as a failure (run
# 41790753113); then as a prefix test on "lib/modules/", which merged-usr makes
# impossible because the listing says usr/lib/modules (run 41793293770). The
# shipped lines are extracted between their markers and executed against
# synthetic listings, so a third layout cannot cost another build.
live_block="$TMP/live-modules.sh"
awk '/# >>> live-modules-check/ { on = 1; next }
     /# <<< live-modules-check/ { on = 0 }
     on' "$REPO_ROOT/build/verify-iso.sh" > "$live_block"
[[ -s "$live_block" ]] \
    || fail "the live modules check in build/verify-iso.sh is not delimited for this test"
cat > "$TMP/gate-runner.sh" <<'RUNNER'
#!/bin/bash
set -euo pipefail
die() { printf 'DIE: %s\n' "$1" >&2; exit 1; }
log() { printf 'LOG: %s\n' "$1"; }
booted_version="$1"
export TMP_DIR="$PWD"
source "$2"
RUNNER
gate_dir="$TMP/live-gate"
mkdir -p "$gate_dir"
listing=$(printf '%s\t%s\t%s\n' \
    '-rw-r--r--' 'root/root' 'usr/lib/modules/6.12.115+deb13.1-amd64/modules.dep' \
    '-r--r--r--' 'root/root' 'usr/lib/modules/6.12.115+deb13.1-amd64/kernel/net/netfilter/nf_conntrack.ko.zst' \
    '-r--r--r--' 'root/root' 'usr/lib/modules/6.12.115+deb13.1-amd64/kernel/net/netfilter/nf_tables.ko.zst' \
    '-r--r--r--' 'root/root' 'usr/lib/modules/6.12.115+deb13.1-amd64/kernel/drivers/hid/usbhid/usbhid.ko.zst' \
    '-r--r--r--' 'root/root' 'usr/lib/modules/6.12.107+deb13-amd64/kernel/net/netfilter/nf_tables.ko.zst' \
    '-rw-r--r--' 'root/root' 'usr/lib/grub/i386-pc/normal.mod')
run_gate() {
    printf '%s\n' "$2" > "$gate_dir/squashfs-modes.tsv"
    (cd "$gate_dir" && bash "$TMP/gate-runner.sh" "$1" "$live_block") 2>&1
}
booted='6.12.115+deb13.1-amd64'
merged=$(printf '%s\t%s\t%s\n' '-rw-r--r--' 'root/root' 'usr/lib/modules/6.12.115+deb13.1-amd64/modules.dep' \
    '-r--r--r--' 'root/root' 'usr/lib/modules/6.12.115+deb13.1-amd64/kernel/net/netfilter/nf_tables.ko.zst' \
    '-r--r--r--' 'root/root' 'usr/lib/modules/6.12.107+deb13-amd64/kernel/net/netfilter/nf_tables.ko.zst')
unmerged=$(printf '%s\n' "$listing" | awk -F'\t' 'BEGIN{OFS="\t"} {sub(/^usr\//, "", $3); print $1, $2, $3}')
no_tree=$(printf '%s\n' "$listing" | awk -F'\t' 'BEGIN{OFS="\t"} $3 !~ /6\.12\.115/ {print $1, $2, $3}')
no_module=$(printf '%s\n' "$listing" | awk -F'\t' 'BEGIN{OFS="\t"} $3 !~ /netfilter\/nf_tables\.ko\.zst$/ {print $1, $2, $3}')

out=$(run_gate "$booted" "$merged") || fail "the check rejects a merged-usr image that has the modules: $out"
assert_contains "$out" 'usr/lib/modules/6.12.115+deb13.1-amd64/kernel/net/netfilter/nf_tables.ko' \
    "a passing check must name where the module really is"
out=$(run_gate "$booted" "$unmerged") || fail "the check rejects a listing that names lib/modules directly: $out"
out=$(run_gate "$booted" "$no_tree") && fail "the check accepts an image with no modules tree for its kernel"
assert_contains "$out" 'no modules tree' "a missing tree must be reported as such"
assert_contains "$out" '6.12.107+deb13-amd64' "a missing tree must say which trees the image does hold"
out=$(run_gate "$booted" "$no_module") && fail "the check accepts a tree with no nf_tables module"
assert_contains "$out" 'nf_tables module' "a missing module must be reported as such"
ok "the live kernel/modules check runs on both layouts and reports what it saw"

# 26. The release gate is the only thing between a commit and a tag that users
# quote, so it is run here rather than trusted: its self-test decides whether a
# green install test at another commit, an unsigned checksum or a set of parts
# that do not rebuild the ISO stops a publication. An over-sized ISO is split
# into publishable parts instead of being refused. And the workflow that calls
# it must not be able to fire on a push, which is how a release would appear
# without anyone choosing to make one.
bash "$REPO_ROOT/scripts/release-gate.sh" --self-test >/dev/null \
    || fail "the release gate self-test failed"
release_workflow="$REPO_ROOT/.github/workflows/release.yml"
assert_file "$release_workflow"
triggers=$(awk '/^on:/ { on = 1; next } on && /^[^[:space:]]/ { on = 0 }
                on { sub(/#.*/, ""); print }' "$release_workflow")
[[ "$triggers" == *workflow_dispatch* ]] \
    || fail "the release workflow has no manual trigger"
if grep -Eq 'push|pull_request|schedule|release_created|created' <<<"$triggers"; then
    fail "the release workflow fires on something besides a person: $triggers"
fi
grep -q 'scripts/release-gate.sh --check' "$release_workflow" \
    || fail "the release workflow publishes without consulting the gate"
ok "the release gate refuses what it must and only a person can publish"

# 27. The security variant is a second APT source in a distribution that promises
# only Debian, so the two properties that make it survivable are checked here
# rather than on a build host: that nothing variant-owned reaches the desktop
# configuration, and that the Kali archive is pinned below Debian instead of
# beside it. Both are decidable from the repository alone, and both would regress
# silently - the first by shipping Kali libraries in a Plasma image nobody asked
# for, the second by letting a rolling suite replace the base system underneath it.
variant_archives="$REPO_ROOT/build/variants/security/archives"
variant_list="$REPO_ROOT/build/variants/security/package-lists/samurai-security.list.chroot"
assert_file "$variant_list"
for kind in list pref key; do
    assert_file "$variant_archives/kali.$kind.chroot"
    assert_file "$variant_archives/kali.$kind.binary"
done
# The chroot pass installs the source, resolves the toolset and then removes it
# again; the image only keeps what the binary pass installs. The two files carry
# different comments on purpose - each explains its own pass - so the pair is
# compared by what apt reads, not byte for byte: the key has to be the same key,
# and the source and the pin have to be the same stanza.
cmp -s "$variant_archives/kali.key.chroot" "$variant_archives/kali.key.binary" \
    || fail "the Kali key differs between the build chroot and the image"
for kind in list pref; do
    diff -u \
        <(grep -Ev '^[[:space:]]*(#|$)' "$variant_archives/kali.$kind.chroot") \
        <(grep -Ev '^[[:space:]]*(#|$)' "$variant_archives/kali.$kind.binary") \
        >/dev/null \
        || fail "kali.$kind.chroot and kali.$kind.binary disagree on what apt is told"
done
# live-build reads config/package-lists and config/archives with a non-recursive
# glob, which is why build/variants/ is inert until build/stage-variant.sh copies
# it. Checked-in variant content in the tree live-build reads would ship in the
# desktop image, and no build output would say so.
for stray in "$REPO_ROOT/build/config/package-lists"/*security* \
    "$REPO_ROOT/build/config/archives"/*kali* \
    "$REPO_ROOT/build/config/includes.chroot/etc/apt/sources.list.d"/*kali*; do
    [[ -e "$stray" ]] && fail "the desktop configuration tree carries variant content: $stray"
done
ok "no variant content is checked into the configuration live-build reads"

# Package: * with a number below Debian's 500 is the whole of "Debian first".
pin="$variant_archives/kali.pref.chroot"
awk 'BEGIN { OFS = "\n" }
     /^Package:[[:space:]]*\*[[:space:]]*$/ { package = 1 }
     /^Pin:[[:space:]]*release n=kali-rolling[[:space:]]*$/ { release = 1 }
     /^Pin-Priority:[[:space:]]*[0-9]+[[:space:]]*$/ {
         priority = $2
         if (package && release) print priority
         package = 0; release = 0
     }' "$pin" > "$TMP/kali-pin"
pin_priority=$(head -n1 "$TMP/kali-pin")
[[ -n "$pin_priority" ]] || fail "kali.pref.chroot does not pin n=kali-rolling under Package: *"
((pin_priority > 0 && pin_priority < 500)) \
    || fail "kali-rolling is pinned at $pin_priority; it must be above 0 to be installable and below Debian's 500"
priorities=$(grep -c '^Pin-Priority:' "$pin")
[[ "$priorities" == 1 ]] \
    || fail "kali.pref.chroot carries $priorities Pin-Priority lines, so the pin below 500 is not the only rule"
# Below zero would forbid installation outright, which the plan considered and
# rejected: a maximal toolset cannot resolve a Kali-only dependency closure then.
ok "the Kali archive is pinned at $pin_priority: installable, never preferred"

if command -v gpg >/dev/null 2>&1; then
    kali_keyring="$TMP/kali-gnupg"
    mkdir -p "$kali_keyring"
    chmod 700 "$kali_keyring"
    GNUPGHOME="$kali_keyring" gpg --batch --import "$variant_archives/kali.key.chroot" \
        >/dev/null 2>&1 || fail "gpg could not import the committed Kali archive key"
    kali_listed=$(GNUPGHOME="$kali_keyring" gpg --batch --with-colons --list-keys \
        | awk -F: '$1 == "fpr" { print $10; exit }')
    kali_documented=$(tr -d '[:space:]' < "$variant_archives/kali.key.fpr")
    [[ "$kali_listed" == "$kali_documented" ]] \
        || fail "the Kali key reports fingerprint ${kali_listed:-none}, not the recorded $kali_documented"
    # An expired archive key fails every apt run in the build, and the failure
    # looks like a network problem. The expiry is printed here so the date a
    # build dies on is written down before someone has to rediscover it.
    kali_expiry=$(GNUPGHOME="$kali_keyring" gpg --batch --with-colons --list-keys \
        | awk -F: '$1 == "pub" { print $7; exit }')
    if [[ -n "$kali_expiry" && "$kali_expiry" != "0" ]] \
        && (( $(date +%s) > kali_expiry )); then
        fail "the Kali archive key expired on $(date -d "@$kali_expiry" +%Y-%m-%d); the security variant cannot build until it is replaced"
    fi
    ok "the committed Kali archive key matches its recorded fingerprint and has not expired"
else
    printf 'skip - gpg not installed, the Kali key was not examined\n'
fi

# Staging is the only thing standing between "the variant exists in the
# repository" and "the variant reached the image", so its own contract is run:
# desktop stages nothing extra, security stages its three files, and switching
# back to desktop leaves no Kali source behind.
bash "$REPO_ROOT/build/stage-variant.sh" --self-test >/dev/null \
    || fail "build/stage-variant.sh --self-test failed"
ok "variant staging is idempotent and leaves nothing behind when switched off"

# The image-side gates have to read the image, not the tree it came from.
verify="$REPO_ROOT/build/verify-iso.sh"
grep -q '/etc/samurai-variant' "$verify" \
    || fail "build/verify-iso.sh no longer reads the variant the image declares"
grep -q 'variants/security/package-lists/samurai-security.list.chroot' "$verify" \
    || fail "build/verify-iso.sh no longer requires every declared security tool to be installed"
ok "the ISO verifier follows the variant the image declares"

printf '\nAll %d smoke checks passed.\n' "$pass"
