# Samurai Linux

A Debian-based operating system for software development, local and cloud AI
assistants, Linux gaming and daily desktop use, built as a live ISO with a
Calamares installer. It is not finished: read
[`samurai/docs/known-limitations.md`](samurai/docs/known-limitations.md) before
relying on any part of it.

- **Base**: Debian Stable (Trixie)
- **Desktop**: KDE Plasma
- **Themes**: Kuro (Dark, `#111214`) and Shiro (Light, `#F5F0E6`) KDE color
  schemes, with a Japanese Samurai-inspired palette (crimson and gold accents).
  22 Samurai wallpapers (1920x1080) are installed system-wide; icons and
  cursors are still planned.

## Repository Layout

```
.
├── README.md                    - This file
├── LICENSE                      - Project license
├── RELEASE_DESCRIPTION.md       - Historical build log (superseded)
├── build/                       - live-build ISO build system (start here)
│   ├── README.md                - Host requirements, build, signing, QEMU test
│   ├── build.sh                 - Preflight + lb clean + lb build + artifacts
│   ├── qemu-test.sh             - Headless or interactive boot test
│   ├── auto/config              - live-build configuration
│   └── config/                  - Package lists, hooks, includes.chroot
├── tests/smoke.sh               - ShellCheck + CLI smoke tests
├── samurai/
│   ├── README.md                - Edition overview and quick links
│   ├── docs/                    - Maintained specifications
│   ├── configs/                 - Legacy copies; prefer docs/
│   ├── scripts/                 - samurai-ai, samurai-theme, samurai-gaming,
│   │                              samurai-profile, samurai-recovery
│   └── themes/{kuro,shiro}/     - KDE .colors schemes + palette CSS
├── scripts/
│   ├── analyze-iso.sh           - Analyze a built ISO with REA
│   ├── post-build-workflow.sh   - Optional REA + Heretic workflow
│   └── use-heretic.py           - Heretic model wrapper
└── .github/workflows/           - CI + self-hosted ISO build
```

## Quick Start

### Themes
```bash
samurai-theme kuro     # Apply dark theme
samurai-theme shiro     # Apply light theme
samurai-theme auto      # Time-of-day automatic switching
samurai-theme list      # List available themes
```

### AI Assistant
```bash
samurai-ai chat "Hello"           # Chat with the default model
samurai-ai install-model <id>     # Pull a model via Ollama
samurai-ai delete-model <id>      # Remove a local model
samurai-ai list-models            # List installed models
samurai-ai set-default <model>    # Set the default model
samurai-ai get-default            # Print the default model
samurai-ai configure --model <id> --install   # Set and pull a model
samurai-ai status                 # Inference and credential status
samurai-ai gpu-info               # GPU detection
samurai-ai cpu-info               # CPU detection
samurai-ai memory-budget          # RAM and suggested AI budget
samurai-ai check-compatibility <id>  # Estimate whether a model fits
samurai-ai credentials get|set|remove <provider> [key]  # Secret Service / 0600 fallback
```

### Gaming
```bash
samurai-gaming install-profile   # steam-installer, GameMode, MangoHUD (+ optional tools)
samurai-gaming steam             # Launch Steam through GameMode and MangoHUD
samurai-gaming lutris            # Launch Lutris through GameMode and MangoHUD
samurai-gaming status            # What is actually installed right now
```

Steam's client lives in Debian's `non-free` archive, which the image does not
enable; `install-profile` says so and stops rather than failing on unmet
dependencies. Proton arrives with Steam and is configured by Steam, not here.

### Developer profiles and recovery
```bash
samurai-profile list                 # Names, packages, or why a profile has none
samurai-profile plan debug           # What would be installed, before installing it
samurai-profile install debug
samurai-profile remove debug         # Removes via APT's own orphan handling

samurai-recovery snapshot before-change
samurai-recovery list
samurai-recovery verify <snapshot>   # sha256-checks each stored payload file
samurai-recovery restore-etc <snapshot> /etc/nftables.conf
```

`samurai-recovery` restores files and package selections. It is not a system
snapshot: it cannot undo a kernel change, a database migration or a user edit
outside `/etc`.

## Building the ISO

The build uses Debian's `live-build`; the old hand-written `debootstrap` +
`xorriso` recipe was invalid and has been replaced. See
[`build/README.md`](build/README.md) for the full guide.

### Build host requirements

| Requirement | Minimum | Recommended |
|---|---|---|
| OS | Debian 13 (Trixie) | Debian 13 |
| Free disk | 50 GB | 100 GB |
| RAM | 4 GB | 8 GB |
| Architecture | x86_64 | x86_64 |
| Tools | `live-build`, `debootstrap`, `xorriso`, `squashfs-tools` | + QEMU, GNUPG |

### Build and test

```bash
sudo apt-get update
sudo apt-get install -y live-build debootstrap xorriso squashfs-tools gnupg

# Build the ISO and collect it under dist/
sudo bash build/build.sh

# Optional: sign it (SAMURAI_SIGN_KEY is your GPG key id)
sudo -E SAMURAI_SIGN_KEY="<key-id>" bash build/build.sh

# Boot-test in QEMU
bash build/qemu-test.sh dist/samurai-linux-*-amd64.iso --gui
```

Output: `dist/samurai-linux-YYYY.MM.DD-amd64.iso`, its `.sha256`, and an
armored detached `.sig` when signing is enabled.

> Build on a Linux filesystem, not on `/mnt/c` or `/mnt/d` under WSL.

## Current Status

| Component | Status |
|---|---|
| Architecture & design documentation | Corrected to describe what is built; the aspirational claims and invented baselines have been removed |
| Foundation decision | Debian 13 `live-build`, approved as a deviation from the Linux-from-Scratch requirement and recorded in [`samurai/docs/architecture.md`](samurai/docs/architecture.md) |
| Kuro / Shiro KDE `.colors` schemes | Implemented; 22 wallpapers at 1920x1080 shipped; icons/cursors pending |
| `samurai-ai` CLI | Implemented and smoke-tested; no AI runtime ships, cloud chat not implemented |
| `samurai-theme` CLI | Applies real KDE color schemes; the install test's desktop phase checks it against a live Plasma session, and that phase has not produced a green run yet |
| `samurai-gaming` CLI | Installs `steam-installer`, GameMode, MangoHUD and optional tools; refuses to pretend when `non-free` is off |
| `samurai-profile` / `samurai-recovery` | Implemented; the install test asserts against them on the installed system, though no install-test run has gone green end to end, and profile installs need network, which the test guest does not have |
| Security defaults in the image | sudo policy, AppArmor, `unattended-upgrades` for `Debian:trixie-security` and APT pinning ship and are read back off the installed system rather than asserted from package presence. **Those read-backs have now happened on a real installed system**: run `42121878962` installed to disk, booted it and reported nftables, AppArmor and the apt periodic timers all enabled, the running ruleset denying unsolicited inbound traffic, `apparmor profiles: profiles=130 complain=44`, `Allowed-Origins:: "Debian:trixie-security"` and a persistent journald. The live-session firewall history is closed at image level: the load failure had a real cause (kernel/modules split), the build prevents it, `verify-iso.sh` gates it and run `41896746985` read the running ruleset back. The run that produced this evidence still failed later, in the recovery phase, so the read-backs are evidence rather than a green release |
| `live-build` ISO pipeline | Hosted workflow builds a bootable hybrid ISO |
| CI (ShellCheck + smoke tests) | Passing on GitHub Actions |
| Bootable ISO boot-tested | QEMU boot to SDDM verified in run `41545976827` (earlier `40346119925`) |
| Calamares installer | ⚠️ Ships and branded. **Run `42121878962` is the first run to reach the execution page: it started the installation, wrote the disk, booted the installed system and verified its boot loader (`boot/grub/grub.cfg` and `i386-pc/core.img` present, `GRUB_DISTRIBUTOR='Samurai Linux'`, Samurai splash).** It then failed in the recovery phase on an argument-parsing bug in `samurai-recovery restore-etc` — an absolute snapshot path was sorted into the list of files to restore, so `tar` answered `Not found in archive` — which is fixed, tested both ways in `tests/smoke.sh`, and needs a rebuild to reach an installed system. Earlier history, kept because it is what the test now works around: in QEMU the live Plasma **Wayland** compositor (`kwin_wayland`) takes a SIGSEGV when the partition preview mounts targets and Calamares loses its display with it; the image used to offer an X11 session without installing `kwin-x11`; and the live image's `/etc/sddm.conf` is rewritten at boot by `live-config` to `Session=plasma.desktop`, which is the Wayland session — so the install test disables that key, states its own `Session=plasmax11`, and gets `x11=yes` (it no longer has to start the session by hand) |
| Installed-system verification | Drives Calamares over VNC/OCR, boots the disk, checks GRUB, security state, package tooling |
| Plasma desktop + MangoHUD verification | ⚠️ Automated (`--desktop` phase); not yet green |
| Performance measurement | `build/measure-performance.sh` runs inside the installed desktop session and its report gates the run; no numbers published yet |
| Signed ISO + release key | Implemented: the build signs ISO, checksum and package manifest, publishes the public key and refuses a key that differs from `samurai/keys/samurai-release.fpr`; install-test verifies the chain |
| First-boot setup wizard | ❌ Not implemented |
| Signed APT repository | ❌ Not implemented |
| Secure Boot | ❌ Not supported: nothing signs a bootloader, so the ISO needs Secure Boot off |

### Release status

No tag and no GitHub Release exist yet, and none will be cut until an install
test is green end to end - a tag is a promise that the ISO installs. That rule
is now mechanical rather than remembered: `scripts/release-gate.sh` picks the
newest completed-successful **Install test** run at the commit being released,
reads out of that run's log which build produced the ISO it installed,
authenticates that artifact against `samurai/keys/`, and refuses anything else;
`.github/workflows/release.yml` runs it and publishes only on a human dispatch
with `dry_run` turned off. Two things stand between a green run and a published
release. The first is the obvious one: there are no green runs. The second is a
size limit nobody had checked - the `samurai-linux-iso` artifact of run
`42105485811` is 2.74 GiB and GitHub refuses a release asset above 2 GiB, so the
image has to shrink or the release has to live somewhere else, and that is a
decision rather than a detail. The gate reports the number instead of silently
failing at publish time.
The last pipeline that was green end to end is
[Build ISO (hosted) run `40346119925`](https://github.com/Mephisto-Von/Samurai-Linux/actions/runs/40346119925)
(commit `028a2ac`, 2026-10-26) — it predates every installer fix since. Later
runs built the ISO successfully but failed in the install test, so the newest
ISO an install test has been driven against is from run `41802792291`; run
`42105485811` is the first image carrying the `kwin-x11` fix, and the install
tests dispatched against that artifact are the ones that first completed an
installation and read the installed system back (`42121878962`). None of them
finished green, so there is still nothing to tag.

`RELEASE_DESCRIPTION.md` is retained as a historical build log. Its commands are
superseded by `build/README.md`, and the claims it made that were never measured
or tested are marked **[retracted]** there.

## Post-Build Tooling

```bash
# Analyze a built ISO with REA
./scripts/analyze-iso.sh path/to/samurai.iso

# Run the combined post-build workflow (REA; add --heretic <model> for Heretic)
./scripts/post-build-workflow.sh path/to/samurai.iso

# Decensor a model with Heretic (requires: pip install heretic-llm)
python3 scripts/use-heretic.py google/gemma-3-12b-it
```

## Testing

```bash
# ShellCheck + CLI smoke tests (Debian container in CI)
bash tests/smoke.sh

# Install the ISO to a virtual disk, boot it, and verify the result
python3 build/install-test.py dist/samurai-linux-*-amd64.iso   # add --desktop for the Plasma phase
```

`.github/workflows/ci.yml` runs the smoke checks in a `debian:trixie` container
and validates the live-build configuration; `install-test.yml` boots the built
ISO, checks its signature, installs it headlessly and reads the result back.
`build/measure-performance.sh` is the only source a performance number may come
from, and the install test fails if it cannot measure one.

## License

See [LICENSE](LICENSE).

---
*Samurai Linux - Debian 13 base, KDE Plasma desktop, Kuro (dark) and Shiro (light) themes*
