# Samurai Linux

A Debian-based operating system combining AI-assisted computing, software development,
cybersecurity, gaming, daily desktop productivity, privacy, and high performance.

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
│   ├── scripts/                 - samurai-ai, samurai-theme, samurai-gaming
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
samurai-gaming install-profile   # Install Steam, Proton, GameMode, MangoHUD
samurai-gaming steam             # Launch Steam with MangoHUD
samurai-gaming lutris            # Launch Lutris with MangoHUD
```

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
| Architecture & design documentation | ✅ Complete (aspirational in places) |
| Kuro / Shiro KDE `.colors` schemes | ✅ Implemented; 22 wallpapers shipped; icons/cursors pending |
| `samurai-ai` CLI | ✅ Implemented, smoke-tested; cloud chat not implemented |
| `samurai-theme` CLI | ✅ Applies real KDE color schemes (live-session check new) |
| `samurai-gaming` CLI | ✅ Fixed for Debian (Steam via `steam-installer`) |
| `live-build` ISO pipeline | ✅ Hosted workflow builds a bootable hybrid ISO |
| CI (ShellCheck + smoke tests) | ✅ Passing on GitHub Actions |
| Bootable ISO boot-tested | ✅ QEMU boot to SDDM verified in run `40346119925` |
| Calamares installer | ⚠️ Ships and branded; the scripted install-to-disk driver (`build/install-test.py`) has not yet produced a green run |
| Installed-system verification | ⚠️ Drives Calamares over VNC/OCR, boots the disk, checks GRUB branding; new in this tree |
| Plasma desktop + MangoHUD verification | ⚠️ New CI phase (`--desktop`): auto-logs into Plasma, applies the theme in a live session, checks GameMode/MangoHud. Not yet run |
| Signed ISO + release key | ⚠️ `Sign the ISO` step added; needs `SAMURAI_SIGN_*` repository secrets |
| First-boot setup wizard | ❌ Not implemented |
| Signed APT repository | ❌ Not implemented |

### Release status

No tag and no GitHub Release exist yet. The last pipeline that was green end to
end is [Build ISO (hosted) run `40346119925`](https://github.com/Mephisto-Von/Samurai-Linux/actions/runs/40346119925)
(commit `028a2ac`, 2026-10-26) — it predates every installer fix since. Later
runs built the ISO successfully but failed in the install test, so the newest
usable ISO artifact is from run `40965845634` (2026-10-29).

`RELEASE_DESCRIPTION.md` is retained as a historical build log. Its commands are
superseded by `build/README.md` and should not be used.

## Post-Build Tooling

```bash
# Analyze a built ISO with REA
./scripts/analyze-iso.sh path/to/samurai.iso

# Run the combined post-build workflow (REA + Heretic)
./scripts/post-build-workflow.sh path/to/samurai.iso

# Decensor a model with Heretic (requires: pip install heretic-llm)
python3 scripts/use-heretic.py google/gemma-3-12b-it
```

## Testing

```bash
# ShellCheck + CLI smoke tests (Debian container in CI)
bash tests/smoke.sh
```

The workflow at `.github/workflows/ci.yml` runs the same checks in a
`debian:trixie` container and validates the live-build configuration.

## License

See [LICENSE](LICENSE).

---
*Samurai Linux — AI-Powered, Secure, High-Performance Developer and Gaming OS*
