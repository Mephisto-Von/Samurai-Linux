# Samurai Linux Testing Strategy

## Test Levels

### 1. Script Smoke Tests
Run `bash tests/smoke.sh` on every change. It parses every shell script,
runs ShellCheck when available, and checks:

```bash
# Theme manager installs a real .colors file and persists the selection
samurai-theme set kuro
samurai-theme list
samurai-theme status

# AI CLI: default model and credentials (no Ollama model required)
samurai-ai --help
samurai-ai set-default llama3.2:3b
samurai-ai get-default
samurai-ai credentials set openai test-key
samurai-ai credentials get openai
samurai-ai credentials remove openai

# Gaming launcher argument handling (uses a fake steam binary)
samurai-gaming steam --foo

# Customization Hub data, package validation and Plasma calls
samurai-customize --core --verify
```

It also fails closed on repository-level lies: a shell call whose quoted message
swallowed the next command, a profile that names packages nobody resolved, a
security policy file that no gate reads back, a `docs/performance.md` that
publishes a number no harness measured, and a file left in a theme folder that
`build.sh` would copy into the image though nothing reads it.

Do not run `samurai-gaming install-profile` as a smoke test: it installs packages
and modifies the system.

Smoke also keeps each required test category attached to the gate that proves it,
so deleting that gate fails here instead of quietly going green: build
prerequisite detection (`build/build.sh --check` is *run* with an impossible disk
requirement and must refuse), boot configuration (auto-boot timeout,
`console=ttyS0,115200n8` on both bootloaders, the installed `/etc/default/grub`),
the QEMU boot test, detached signatures over the ISO, its checksum and the
package manifest plus a fingerprint cross-check against `samurai/keys/`, and the
update and recovery workflows the install test reads back.

### 2. Build Pipeline Tests
- `bash build/build.sh --check` passes (host, tools, disk, config generation)
- `lb build` completes and the hybrid ISO appears under `dist/`
- `bash build/verify-iso.sh dist/samurai-linux-*-amd64.iso` passes: BIOS and
  UEFI boot records exist, the live kernel/initramfs/squashfs are present, and
  Calamares, Samurai branding, the installer entry, GRUB packages, `unsquashfs`,
  `rsync`, and `cryptsetup` are inside the squashfs; the Samurai CLIs and KDE
  color schemes are installed; the live menu auto-boots after 5 seconds with
  `console=ttyS0,115200n8` on the isolinux and GRUB entries; the Debian security
  pocket is configured exactly once, not zero and not twice; and the squashfs
  metadata records the policy files as `root:root` with the modes the security
  hook sets — read from the metadata rather than an extraction, because
  extracting as a non-root user rewrites ownership
- Checksums and GPG signature verify:
  ```bash
  cd dist
  sha256sum -c samurai-linux-*.iso.sha256
  gpg --verify samurai-linux-*.iso.sig samurai-linux-*.iso
  ```

### 3. Boot Tests (QEMU)
```bash
# Headless serial check (180 s timeout)
bash build/qemu-test.sh dist/samurai-linux-*-amd64.iso

# Interactive desktop check
bash build/qemu-test.sh dist/samurai-linux-*-amd64.iso --gui
```
Pass criteria: the serial log shows kernel/systemd boot messages. The hosted
workflow uses `QEMU_TIMEOUT=300`; the verified 2026-10-26 run reached
`sddm.service` and a `samurai login:` prompt. The VGA screenshot is captured at
120 seconds and may still show boot messages, so the serial log is authoritative.
For a GUI run, confirm that SDDM appears and the Plasma live session starts as
`samurai` with the **Install Samurai Linux** icon.

### 4. Installation Tests (automated, green in CI)
`bash build/install-test.sh <iso>` drives the real Calamares UI in QEMU and
checks the result over the serial console. How it reaches the installer is part
of the evidence: Calamares starts from a launcher that moves to the live
desktop's D-Bus session when root may use it and otherwise reports that it did
not, copies the live fstab aside and grants root the display the same way the
shipped `calamares-install-debian` wrapper does, and - because three runs ended
with `kwin_wayland` segfaulting when Calamares painted its partition preview -
switches the *live* session to Plasma on X11 before launching. The X11 switch is
a test-environment change the run log names explicitly; a green run therefore
proves the installer, not the Wayland live session it skipped. That switch has
its own override: run 42105485811 restarted SDDM into `plasmax11` with the X11
compositor installed and got a running Xorg with no desktop on it, and run
42112234958 showed why - the autologin drop-in was ignored, SDDM started the
Wayland session anyway, and when it exited SDDM put a display on VT3 for its own
greeter, so what looked like an empty X11 session was a login screen. The test
now prints the image's SDDM configuration, disables every `Session=` key in it
and states its own request last; if that still leaves no compositor it starts the
session file's `Exec=` itself, after killing the greeter so it cannot draw over
the installer, and says in the log that it did. A green run therefore proves the
installer on an X11 desktop, not that the live image can autologin into one by
itself.
Pass criteria:

- Guided partitioning completes and the disk is bootable (MBR, `grub.cfg`,
  `core.img` present)
- The installed system boots, logs in on the serial console, and reports the
  expected hostname, root filesystem, and `/home/samurai` owner
- The installed kernel and GRUB keep `console=ttyS0,115200n8`
- With `--branded`, the installed `os-release`, `/etc/default/grub`, GRUB menu,
  splash and motd are Samurai-branded
- With `--desktop` (default), SDDM auto-logs into Plasma on the test disk,
  `plasmashell` runs, the compositor renders a non-blank frame,
  `samurai-theme set shiro` applies to the live session and is recorded in
  `kdeglobals`, and GameMode/MangoHud are installed with the interposer library
- Security state is read back off the installed system rather than inferred from
  installed packages: nftables, AppArmor and the apt timers are enabled units,
  the *running* ruleset contains the default-deny ingress policy, the kernel has
  AppArmor on and loaded more than zero profiles (how many are in enforcing mode
  is reported, not claimed), no sudoers file grants passwordless root, the
  `trixie-security` pocket is configured and named by `unattended-upgrades`'
  effective `Allowed-Origins`, and the policy files are root-owned
- The package tools run on the installed system: `samurai-profile list/plan`
  resolves every shipped profile and refuses an unknown one, `samurai-recovery`
  takes a snapshot, verifies its checksums, restores a modified `/etc` file
  without losing it, reports that nothing needs removing, and prunes old
  snapshots

Still manual, and not automatable here: LUKS unlock on real firmware, UEFI on
real hardware, Secure Boot, and an actual Proton title with the overlay visible
(no GPU in QEMU).

### 5. Desktop and Theme Tests

The `--desktop` phase proves that a scheme can be applied to a live Plasma
session; it does not prove both palettes. What it asserts today:

- `samurai-theme set shiro` runs in the installed session and the selection is
  read back out of `kdeglobals`
- the matching wallpaper is read back from Plasma and the compositor rendered a
  non-blank frame
- both scheme files parse and carry their expected `ColorScheme` name
  (`tests/smoke.sh`)
- the Customization Hub's logic (`tests/smoke.sh`): all 22 wallpapers are
  3840x2160 (read from the JPEG frame headers), every preset resolves to a
  committed scheme that is exactly what `presets.json` renders, and a theme
  package imports when valid while being refused for a script, a traversal
  path, a symlink, an executable bit, an absolute path and an incomplete
  manifest

Not automated yet, and therefore not claimed:

- Kuro and Shiro each apply with every published colour; only the scheme file
  and the applied scheme name are checked, not the rendered palette
- theme persistence across logout or reboot
- `samurai-theme auto` switching by time of day
- contrast ratios and visible focus states: the palettes are *targeted* at WCAG
  AA, and the Hub now computes the ratios and warns below 4.5:1, but no
  rendered palette has been measured against them
- the Customization Hub window itself: it has been rendered offscreen and
  inspected, but no automated test drives its buttons, and none of its Plasma
  calls has run against a live session

### 6. AI Runtime Tests

None of these run in CI. The image ships no AI runtime, the guest has no model
and no network, and cloud chat, the router and resource limits are not
implemented (see [`ai-system.md`](ai-system.md)); this is the target list, not a
suite:

- `samurai-ai chat` works with a configured local model - needs Ollama and a
  pulled model on a real machine
- Local mode works with no cloud API key present - true by construction: the
  chat path only calls `ollama` and never reads a provider credential
- Cloud mode discloses external data transmission before sending - not
  implemented
- Model router documents selection criteria and honors user overrides - not
  implemented
- Resource limits pause inference under high system load - not implemented

### 7. Gaming Tests (on declared supported configurations)

Automated today: the desktop phase requires GameMode and MangoHUD to be
installed and preloads the MangoHUD interposer in a live session. Everything
else needs a GPU and a game:

- Steam installs and launches via `samurai-gaming steam` - not exercised; the
  test guest has no network and the image does not enable `non-free`
- Proton runs at least one Windows title - never run
- GameMode engages (`systemctl --user status gamemoded`) - only the package is
  checked, not an engaged game
- MangoHUD overlay displays (`MANGOHUD=1 %command%`) - only the interposer load
  is checked, not a rendered overlay
- Controller detected and usable - no test touches a controller

### 8. Performance Measurements
There are no documented baselines to compare against, and there will not be any
until a run produces them. `build/measure-performance.sh` measures boot time,
enabled and running unit counts, memory in use, idle CPU, a fixed SHA-256
throughput, a compiler probe, disk write speed, the GL renderer and root
filesystem size, and writes each value next to the command and the machine that
produced it:

```bash
bash build/measure-performance.sh --out-dir /tmp/perf
```

The install test runs it inside the live Plasma session and fails when a core
metric (`memory_used`, `cpu_idle`, `units_enabled`, `services_running`,
`sha256_mib_per_s`, `rootfs_used`) comes back `unavailable`, so a green run
always carries a `performance.txt`. Quoting a number anywhere else requires the
command, host and run alongside it - see
[`performance.md`](performance.md).

## Release Test Matrix
| Component | Minimum coverage |
|---|---|
| ISO boot | QEMU, 1 VM per architecture |
| Installation | Calamares guided install automated in QEMU (`build/install-test.py`), plus manual LUKS and one manual partition on hardware |
| Themes | Kuro, Shiro, auto-switch |
| AI | One local model, local-only mode |
| Gaming | Steam + Proton + GameMode + MangoHUD |
| Performance | `build/measure-performance.sh` inside the install-test desktop phase: boot time, unit counts, idle RAM, idle CPU, compute and disk throughput |

## Automating Tests
- `tests/smoke.sh` runs in GitHub Actions (`.github/workflows/ci.yml`) on every push and pull request
- The `live-build` job validates `build/auto/config` in a `debian:trixie` container
- The hosted ISO workflow (`.github/workflows/build-iso-hosted.yml`) builds the image in a privileged Debian container, runs `build/verify-iso.sh`, and then runs the headless QEMU boot test. Run `40346119925` on commit `028a2ac` passed both stages and reached SDDM.
- Signed release builds and full install tests run on a self-hosted runner (`.github/workflows/build-iso.yml`)
- A full Calamares install-to-disk test is automated (`build/install-test.py`,
  driven by `.github/workflows/install-test.yml`); run `42392182476` completed
  green at commit `89ed5cf` against the ISO built by run `42296526484`, and the
  release gate now refuses a tag without such a run
- Defects found are logged and triaged; critical defects block release
