# Samurai Developer Environment

> **Legacy design document.** The `samurai-editor` helper, the "SSH configured
> with secure defaults" and the GitHub/GitLab CLI integrations below are not
> implemented: the image ships `openssh-client` only, with no SSH server and no
> SSH configuration, and no `gh` or `glab`. See
> [`../docs/developer-environment.md`](../docs/developer-environment.md) for what
> ships and what `samurai-profile` adds.

## Core Tools

### Version Control and SSH
- Git - pre-installed with Samurai developer profile
- SSH - configured with secure defaults
- GitHub/GitLab CLI integration

### Compilers and Build Systems
- GCC - system compiler
- Clang - alternative compiler with better C++ support
- Make - standard build automation
- CMake - cross-platform build system
- Ninja - fast build system for C++ projects

### Package Managers and Languages
- Python 3.x with venv support
- Node.js LTS with npm
- Rust (rustup) and Cargo
- Go (goenv or gvm)
- Java JDK with javac
- Shell utilities (bash, zsh, fish)

**Recommended for day-1 usability**:
- `libreoffice` - office suite
- `thunderbird` - email
- `korganizer` - calendar
- `system-config-printer` + `simple-scan` - printing/scan
- `transmission-gtk` - torrent
- `dragonplayer` - video
- `shotwell` - photos
- `bup` or `borgbackup` - backup
- `cloud-init` - automated provisioning

## Editors and IDEs

### VS Code-Compatible Workflows
- VSCodium - open-source VS Code fork (pre-installed or easy install)
- VS Code with Samurai extensions

### Native Editors
- Neovim - configured with lazy.nvim package manager
- Vim - enhanced vi editor
- Qt Creator - for Qt/C++ development
- JetBrains IDEs (IntelliJ, PyCharm, WebStorm) via snaps or scripts

### Editor Configuration

The Samurai editor configuration bundle is not shipped yet. Until it is,
install and configure editors yourself (for example `apt-get install neovim`
followed by your own `~/.config/nvim`).
