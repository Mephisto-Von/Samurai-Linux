# Samurai Linux - Release Build Description

> **Historical document.** This records the original Codespace attempt. The
> `debootstrap`/`xorriso` commands below are superseded and some were invalid
> (for example `debootstrap --arch=x86_64`, `xorriso -as iso`, and a `gpg --armor
> --output file.sig file` that is missing `--detach-sign`). Use
> [`build/README.md`](build/README.md) and `build/build.sh` instead.
>
> Paths under `/opt/samurai/` and `/samurai/rootfs` were that scratch
> environment's layout. They are not part of the repository and nothing in the
> image installs there; the maintained copies live in `samurai/docs/`,
> `samurai/scripts/` and `samurai/themes/`.
>
> Claims below that were never backed by a recorded test are marked
> **[retracted]** with what is actually true now.

## Historical State and Continuation Instructions

### Build Environment Status
- **Current system**: Codespace environment (32GB disk, 2.3GB free, 7.8GB RAM total, 174MB free)
  **[retracted]** - a one-machine snapshot from that Codespace, not a spec or a baseline
- **Architecture**: x86_64
- **Samurai rootfs**: Partially created at `/samurai/rootfs` (partial debootstrap attempted)
- **Configuration**: Complete at `/opt/samurai/` **[retracted]** - the configuration
  that ships is the live-build tree under `build/`

### What Has Been Built (Complete at /opt/samurai/)

#### Directory Structure
```
/opt/samurai/
├── README.md - Project overview and quick start
├── configs/ - 9 documentation files
│   ├── ai-system.md - AI runtime, assistant, model router, cloud/offline modes
│   ├── build-pipeline.md - 12-step reproducible build pipeline
│   ├── desktop-and-themes.md - Kuro/Shiro themes with full color specs
│   ├── developer-environment.md - Core tools, editors, containers
│   ├── gaming.md - Steam/Proton/Lutris/GameMode/MangoHUD
│   ├── installation.md - Full-disk encryption, profiles, AI setup
│   ├── package-management.md - Repo structure, signing, upgrades
│   ├── performance.md - Baselines, monitoring, AI resource limits
│   └── (security.md, testing.md, known-limitations.md - planned)
├── themes/ - Kuro (#111214) / Shiro (#F5F0E6) color schemes
│   └── kuro/colors.css - Dark theme spec
│   └── shiro/colors.css - Light theme spec
├── scripts/ - CLI tools (present in this repository as samurai/scripts/*)
│   ├── samurai-ai - 13 commands (chat, install-model, status, gpu/cpu-info,
│   │             memory-budget, set-default, check-compatibility,
│   │             credentials get|set|remove)
│   ├── samurai-theme - kuro/shiro/auto/list commands
│   └── samurai-gaming - install-profile, steam, lutris
├── iso/ - ISO build directory structure (empty, ready for rootfs rsync)
└── packages/ - Custom .deb package directory (empty, ready for build output)
```

#### Documentation Files (Full content at /opt/samurai/configs/)
- `ai-system.md` - Complete AI system specification (5 subsections: local runtime,
  Samurai AI Assistant, intelligent model router, AI-assisted system operations,
  cloud/offline modes)
- `build-pipeline.md` - 12-step pipeline from host verification to release signing
- `desktop-and-themes.md` - Kuro/Shiro color palettes, Japanese Samurai motifs,
  theme selector, installation artwork
- `developer-environment.md` - **[retracted]** what actually ships is GCC via
  `build-essential`, CMake, Ninja, Git, Python 3 and Vim; Clang, VSCodium,
  Neovim, Qt Creator, JetBrains, Podman, Docker and QEMU/KVM are not in the
  image. `samurai/docs/developer-environment.md` lists the real contents and the
  `samurai-profile` names that install the rest.
- `gaming.md` - Steam + Proton, Vulkan/Mesa, AMD/Intel/NVIDIA, GameMode, MangoHUD,
  Gamescope, controllers, gaming profile with documented configuration
  **[partly retracted]** - only GameMode, MangoHUD and the Mesa/Vulkan drivers
  ship; see `samurai/docs/gaming.md`
- `installation.md` - **[retracted]** no first-boot wizard exists, and no encrypted
  installation has ever been completed or tested by this project; see
  `samurai/docs/installation.md` for what the installer actually does
- `package-management.md` - **[retracted]** there is no Samurai APT repository, no
  versioned repository and no pinning of Samurai packages, because none of that is
  built. What exists is Debian's own archives plus security-pocket pinning in
  `build/config/includes.chroot/etc/apt/preferences.d`, `unattended-upgrades`
  configured for `Debian:trixie-security`, and the `samurai-profile` /
  `samurai-recovery` CLIs. See `samurai/docs/security.md` and
  `samurai/docs/known-limitations.md`.
- `performance.md` - **[retracted]** the baselines this file once published
  (boot time 8-12s SSD / 30-45s HDD, idle memory 400-600MB, CPU 2-5% at desktop)
  were never measured by anything. `samurai/docs/performance.md` now explains how
  `build/measure-performance.sh` produces real numbers and forbids publishing any
  other kind. Power profiles, KWin tuning and AI resource limits are not
  implemented.
- `build-pipeline.md` - 12-step process (verified in documentation, execution blocked
  by environment constraints)

#### Scripts as they were first written
**[corrected]** "ALL VERIFIED WORKING" was never a verified statement: at the time
nothing in the project ran them beyond a shell session on one Codespace. Today the
automated checks are `tests/smoke.sh` (argument handling, failure paths, profile
resolvers, recovery guards) and the install-test phases that run the CLIs on an
installed system. Hardware strings below are that one Codespace's readings, not
expected output.

1. `samurai-theme` - Theme manager
   - `samurai-theme kuro` - Applies dark theme (#111214 with crimson #B52832,
     gold #B89A59 accents)
   - `samurai-theme shiro` - Applies light theme (#F5F0E6 with vermilion #B52832,
     gold #96733B accents)
   - `samurai-theme auto` - Automatic light/dark switching based on time of day
   - `samurai-theme list` - Lists available themes

2. `samurai-ai` - AI assistant CLI (13 commands)
   - `samurai-ai chat "Hello"` - Chat with local Ollama model
   - `samurai-ai gpu-info` - Hardware detection (on that Codespace: no discrete GPU)
   - `samurai-ai cpu-info` - CPU details from `lscpu` (that Codespace reported a
     2-core AMD EPYC 7763)
   - `samurai-ai memory-budget` - Memory status (that Codespace had 7.8GB total and
     174MB free)
   - `samurai-ai set-default llama2` - Configures default model
   - `samurai-ai install-model <id>` - Pull model via Ollama
   - `samurai-ai list-models` - List available models
   - `samurai-ai status` - Show inference status
   - `samurai-ai set-default <model>` - Set default model (writes to
     ~/.config/samurai/ai-default)
   - `samurai-ai check-compatibility` - Check model/hardware compatibility
   - `samurai-ai credentials set/get/remove` - Credential storage at mode 0600;
     the fallback file holds the key in plain text and the CLI says so itself
     (`mode 600, not encrypted`). Keyring-backed storage runs through
     `secret-tool` when a Secret Service is answering.
   - `samurai-ai` (no args) - Usage/help output with all commands listed

3. `samurai-gaming` - Gaming profile manager
   - `samurai-gaming install-profile` - Enables i386, installs `steam-installer`,
     GameMode and MangoHUD, plus Lutris/Gamescope/winetricks/protontricks when the
     configured archives have them. It does not configure Proton, and it stops with
     instructions if Debian's `non-free` archive (where the Steam client lives) is
     not enabled.
   - `samurai-gaming steam` - Launches Steam through GameMode and MangoHUD
   - `samurai-gaming lutris` - Launches Lutris through GameMode and MangoHUD

### What Needs to Happen Next (to Generate Bootable ISO)

#### Step 1: Provision Build Host
- 50GB+ free disk space (minimum), 100GB+ recommended
- 8GB+ RAM (16GB+ recommended for build)
- x86_64 architecture
- Linux host with debootstrap, sbuild/xorriso installed

#### Step 2: Initialize Debian Base System
```bash
# On build host
debootstrap --arch=x86_64 trixie /samurai/rootfs http://deb.debian.org/debian/
```
This creates the customized Debian rootfs. Requires ~15-20GB after completion.

#### Step 3: Integrate KDE Plasma and Samurai Configuration
```bash
chroot /samurai/rootfs apt-get update
chroot /samurai/rootfs apt-get install -y kde-plasma-desktop

# Apply Samurai themes
cp -r /opt/samurai/themes/kuro /usr/share/themes/samurai-kuro
cp -r /opt/samurai/themes/shiro /usr/share/themes/samurai-shiro

# Configure Samurai welcome script and sessions
cp /opt/samurai/scripts/welcome.desktop /usr/share/xsessions/
echo "Exec=/opt/samurai/scripts/start-plasma.sh" >> /usr/share/xsessions/samurai-kuro.desktop
```

#### Step 4: Generate ISO
```bash
# Create ISO directory structure
mkdir -p iso/boot/grub iso/live

# Copy root filesystem
rsync -a /samurai/rootfs/ iso/

# Configure GRUB for live system
cat > iso/boot/grub/grub.cfg << 'GRUB_CFG'
menuentry 'Samurai Linux' {
    set isofile=/samurai.iso
    linux (isofile)/boot/vmlinuz boot=live config quiet
    initrd (isofile)/boot/initrd.img
}
GRUB_CFG

# Generate ISO
xorriso -as iso -r -fjoliet-long -l -V "Samurai Linux" \
  -o samurai.iso iso/
```

#### Step 5: Calculate Checksums and Validate
```bash
sha256sum samurai.iso > samurai.sha256
sha1sum samurai.iso > samurai.sha1
gpg --armor --output samurai.iso.sig samurai.iso

# Verify
sha256sum -c samurai.sha256

# QEMU boot-test
qemu-system-x86_64 -cdrom samurai.iso -m 4096 -display none -boot d
```

#### Step 6: Run Automated Tests (per docs/testing.md)
- Boot-test in QEMU
- Test installation
- Verify KDE Plasma works
- Verify themes apply correctly
- Verify AI runtime components

#### Step 7: Validate Against Release Acceptance Criteria (17 points from docs/release-process.md)
- Bootable ISO generated and validated - **not met**: the ISO builds and boots in
  CI, but no automated install run has been green yet. The per-criterion status now
  lives in `samurai/docs/release-process.md`, not here.
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

### Continuation Checklist for User's Device

#### If continuing on a different build host:

1. **Clone the configuration**:
   ```bash
   # Copy /opt/samurai/ to the build host
   scp -r codespace:/opt/samurai/ /path/to/build/
   # Or clone if using git
   git clone <repo-url> /opt/samurai/
   ```

2. **Verify disk space**: `df -h /` should show 50GB+ free

3. **Verify RAM**: `free -h` should show 8GB+ available

4. **Install build tools** (if not present):
   ```bash
   sudo apt-get update
   sudo apt-get install -y debootstrap xorriso gnupg dpkg-dev
   ```

5. **Start the build pipeline** (from docs/build-guide.md Step 1):
   ```bash
   # Step 1: Verify host environment
   df -h /path/to/build
   free -h
   uname -m
   which debootstrap sbuild xorriso
   
   # Step 2: Retrieve source
   debootstrap --arch=x86_64 trixie /samurai/rootfs http://deb.debian.org/debian/
   
   # Step 5: Assemble filesystem
   chroot /samurai/rootfs apt-get install -y kde-plasma-desktop
   
   # Step 7: Generate ISO
   xorriso -as iso -r -fjoliet-long -l -V "Samurai Linux" -o samurai.iso iso/
   
   # Step 8: Checksums
   sha256sum samurai.iso > samurai.sha256
   gpg --armor --output samurai.iso.sig samurai.iso
   
   # Step 10: Run tests
   qemu-system-x86_64 -cdrom samurai.iso -m 4096 -display none
   ```

6. **Test the resulting ISO**:
   - Boot in QEMU: `qemu-system-x86_64 -cdrom samurai.iso -m 4096`
   - Log in and test KDE Plasma
   - Apply theme: `samurai-theme kuro` or `samurai-theme shiro`
   - Chat with AI: `samurai-ai chat "Hello"`
   - Launch gaming: `samurai-gaming steam`

### Known Limitations (Current Build)
- Environment constrained: 32GB disk (2.3GB free), 7.8GB RAM (174MB free)
- ISO generation NOT possible on current environment
- Full debootstrap requires 50GB+ disk and 8GB+ RAM
- Some gaming packages may not install in this constrained test
- AI model downloads require separate Ollama setup on target system

### Contact / Support
**[corrected]** those paths were the Codespace scratch layout. The real locations:

- Documentation: `samurai/docs/` (maintained) and `samurai/configs/` (legacy design docs)
- Scripts: `samurai/scripts/` (samurai-ai, samurai-theme, samurai-gaming,
  samurai-profile, samurai-recovery)
- Build pipeline: `build/` and `build/README.md`
- Themes: `samurai/themes/kuro/` and `samurai/themes/shiro/`
- Release signing key material: `samurai/keys/` (public half only)

---
*Samurai Linux - AI-Powered, Secure, High-Performance Developer and Gaming OS*
*Base: Debian Stable (Trixie), Desktop: KDE Plasma, Themes: Kuro (Dark) / Shiro (Light)*
*Japanese Samurai-inspired design with restraint: brushstroke artwork, waves, mountains,
moonlight, lacquered black surfaces, crimson and gold accents*
