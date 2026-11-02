# Samurai Linux Architecture

> This document describes the target architecture. Implemented today: the
> `live-build` ISO pipeline, the `samurai-ai` / `samurai-theme` /
> `samurai-gaming` / `samurai-profile` / `samurai-recovery` CLIs, the Kuro/Shiro
> KDE color schemes, an nftables/AppArmor/unattended-upgrades security baseline,
> GPG-signed release artifacts, and a headless installer test that boots and
> inspects an installed system. Not implemented: the AI runtime and model router,
> the control center, a signed package repository, Secure Boot, and a first-boot
> wizard. See [`../../README.md`](../../README.md) for current status.

## Foundation Decision

The project brief required a from-scratch base ("The base MUST be Linux From
Scratch", "Do not silently replace LFS with Debian"). Samurai Linux does not do
that. **It is built on Debian 13 (trixie) with `live-build`, and that deviation
was chosen openly and approved by the project owner in November 2026** rather
than slipped in.

Why: an LFS base would have to supply, and then keep patched, the whole stack
this distribution is judged on - toolchain, KDE Plasma and Qt, Mesa and Vulkan
drivers, systemd, Calamares, the gaming layer and every library an AI runtime
needs. That is a security-responsibility transfer, not a build preference: the
result would be a distribution that ships unsolved CVEs in exchange for an
origin story. Debian's archive provides the same components with a maintained
CVE pipeline, signed Release files and a trixie-support window, which is what the
requirements about security updates and recoverability actually need.

What it costs, and what is therefore recorded as a known limitation:

- Samurai Linux inherits Debian's package set, its init system and its release
  cadence, so "custom distribution" here means a Debian-derived distribution with
  its own image, tooling, themes, policy defaults and release signing.
- The `DISTRIB_ID`/`lsb-release` rebrand is load-bearing and dangerous: it silently
  changed `${distro_id}` to `Samurai`, which made `unattended-upgrades`' default
  `Allowed-Origins` match no archive at all, so automatic security updates would
  have stopped working on every installed system. Security policy therefore names
  archive origins literally (`Debian:trixie-security`) and the build hook refuses
  to continue if the archive's own `Origin:` field disagrees.
- Any future change to this foundation requires the same explicit approval.

## Distribution
- **Name**: Samurai Linux
- **Base**: Debian Stable (starting with Debian 13 "Trixie")
- **Development Model**: Custom distribution based on an existing Linux distribution

## Base System
- **Architecture**: x86_64 initially
- **Package Format**: Debian packages (.deb) and compatible repository infrastructure

## Desktop Environment
- **Primary**: KDE Plasma
- **Themes**: 
  - **Kuro (Dark)**: 
    - Background: `#111214`
    - Panels: `#1B1D20`
    - Elevated surfaces: `#25272B`
    - Primary text: `#F2EEE5`
    - Secondary text: `#B8B4AC`
    - Crimson: `#B52832`
    - Gold: `#B89A59`
    - Borders: `#383A3D`
  - **Shiro (Light)**:
    - Background: `#F5F0E6`
    - Panels: `#ECE5D8`
    - Elevated surfaces: `#FFFDF8`
    - Primary text: `#242321`
    - Secondary text: `#686258`
    - Vermilion: `#B52832`
    - Gold: `#96733B`
    - Borders: `#D8D0C2`

## Product Objectives
1. Develop software and build applications
2. Run local AI models and interact with integrated AI assistant
3. Use optional cloud AI providers through explicit user configuration
4. Work securely with source code, credentials, containers, and development environments
5. Play supported games with practical Linux gaming tools
6. Use the machine for normal daily computing
7. Customize the desktop without sacrificing usability
8. Maintain and recover the system without advanced Linux expertise

## Modular Organization
- Base operating system and kernel
- Package and repository management
- Security and privacy layer
- KDE Plasma desktop and Samurai theme system
- AI runtime and assistant
- Developer toolchain
- Gaming environment
- System settings and performance manager
- Installer, updater, recovery, and diagnostics
- Build pipeline, tests, and release tooling

## AI-Powered Operating System
### 4.1 Local AI Runtime
- Evaluate maintained local inference engines (Ollama, llama.cpp)
- Implement model discovery, installation, storage, and deletion
- Hardware and memory detection (CPU/GPU capability)
- Model compatibility checks, context-length and memory-budget controls
- Inference status and resource monitoring
- Clear errors when model cannot run on available hardware

### 4.2 Samurai AI Assistant
- Desktop-accessible chat interface
- Conversation history with user-controlled retention
- Code explanation and debugging
- Project planning and implementation assistance
- File summarization and document analysis
- Terminal command explanations
- System troubleshooting
- Developer documentation assistance
- Optional speech input and output
- Configurable local model selection
- Optional cloud model integrations
- Modular provider interface

### 4.3 Intelligent Model Router
- Task category based selection (coding, reasoning, summarization, etc.)
- Available hardware consideration
- Model capabilities and measured quality
- Context-window requirements, memory and latency constraints
- Estimated cost, privacy requirements, provider availability
- User-selected preferences override

### 4.4 AI-Assisted System Operations
- Permissioned execution service
- Explicit confirmation for destructive/privileged operations
- Never silently upload files, source code, logs, credentials, or system info to cloud

### 4.5 Cloud and Offline Modes
- **Local mode**: Use locally available models without cloud API credentials
- **Cloud mode**: Configure supported providers with user's own credentials
- Secure credential storage, never hardcode secrets

## Developer Environment
### Core Tools
- Git and SSH, GCC and Clang, Make, CMake, Ninja
- Python and virtual environments, Node.js and npm-compatible workflows
- Rust and Cargo, Go, Java toolchains
- GDB and LLDB, Shell scripting utilities

### Editors and IDEs
- VS Code-compatible workflows
- VSCodium (open-source editor)
- Neovim/Vim
- Qt Creator
- JetBrains IDEs (supported installation methods)

### Containers and Virtualization
- Podman and rootless containers
- Docker-compatible workflows
- QEMU/KVM and libvirt
- Development containers, local databases, API-testing utilities

### AI/ML Development
- PyTorch and TensorFlow (optional)
- Jupyter, data science and scientific computing
- GPU compute, CUDA or ROCm when compatible
- Model development and evaluation, reproducible Python environments

## Security and Privacy
- Secure defaults without making development difficult
- Debian package signature verification
- Firewall configuration, least-privilege administration
- AppArmor mandatory access control
- Full-disk encryption support through installer
- Secure credential storage
- Application and container isolation
- SSH hardening guidance
- Audit logs and diagnostics
- Privacy-conscious defaults
- Recovery and backup procedures
- Dependency vulnerability scanning
- Build provenance and artifact integrity checks
- Secure Boot where signing workflow permits

## Gaming and Graphics
- Steam and Proton
- Vulkan, Mesa, AMD/Intel/NVIDIA graphics
- Lutris, Heroic Games Launcher
- GameMode, MangoHud, Gamescope
- Controllers and gaming audio devices

## Performance Engineering
- Minimal unnecessary startup applications
- Sensible background-service defaults
- Hardware-aware power profiles
- Balanced, performance, and power-saving modes
- Graphics and compositor configuration
- Storage and swap defaults
- Resource monitoring (CPU, RAM, GPU, disk, AI workloads)
- Optional AI resource limits
- Reproducible baselines for benchmarking

## KDE Plasma and Samurai Design System
- Kuro and Shiro themes as specified
- Original wallpapers, logos, icons, terminal colors, login branding, installer artwork
- Japanese Samurai-inspired motifs with restraint

## System Dashboard and Settings
- Samurai Control Center using KDE-compatible technologies
- System information, hardware/driver status, software/updates
- AI models and providers, development profiles, gaming configuration
- Performance profiles, security status, storage and backups
- Network settings, theme and personalization
- Diagnostics and logs

## Installer and First Boot
- Bootable ISO and installable system
- Live environment where feasible
- Hardware and network detection
- Partition selection, full-disk encryption options
- Bootloader configuration, user account creation
- Secure administrator configuration, package selection
- Developer and gaming profiles, AI runtime setup
- Theme selection, installation progress and actionable errors
- First-boot setup, recovery guidance
- Never erase disks without explicit user confirmation

## Package Management and Updates
- Debian's package ecosystem as the only APT source; nothing is published as a
  Samurai repository, because no Samurai `.deb` repository is built today
- Versioned ISO releases with signed ISO, checksum and installed-package manifest
- Security updates through Debian's `trixie-security` pocket, pinned at priority
  600 and applied by `unattended-upgrades`, verified on the installed system
- `samurai-profile` installs and removes grouped packages through APT and records
  what it did; `samurai-recovery` keeps checksummed `/etc` and package-list
  snapshots
- Rollback after a failed update is a documented manual procedure, not a feature:
  APT keeps no snapshot

## Build and Release Engineering
- `live-build` pipeline driven by `build/build.sh`
- Version-controlled build configuration
- Pinned versions and documented update procedures

## Required Project Documentation
- README.md
- docs/architecture.md
- docs/build-guide.md
- docs/security.md
- docs/ai-system.md
- docs/developer-environment.md
- docs/gaming.md
- docs/performance.md
- docs/desktop-and-themes.md
- docs/installation.md
- docs/testing.md
- docs/release-process.md
- docs/known-limitations.md

## Release Acceptance Criteria
- Bootable ISO generated and validated
- Installation and first boot tested
- KDE Plasma works as primary desktop
- Kuro and Shiro themes persist and function
- Developer profile usable
- Security defaults and update mechanisms documented and tested
- AI assistant can use at least one supported model backend when configured
- Local AI mode works without requiring cloud API key
- Cloud integrations clearly disclose external data transmission
- Model routing uses documented criteria and permits user overrides
- Gaming capabilities tested on declared supported configurations
- Performance measurements reproducible
- Recovery and upgrade procedures documented
- Critical known defects resolved or explicitly block release
- Build and release instructions complete
