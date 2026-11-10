# Samurai Linux Installation and First Boot

> **Legacy design document.** The `samurai-install` installer and the
> `samurai-backup` command below are not implemented; installation is Calamares,
> and there is no first-boot wizard - the system boots straight to SDDM. LUKS
> and UEFI on real firmware have never been installed to in a Samurai test, and
> Secure Boot is unsupported because the installed GRUB is unsigned. See
> [`../docs/installation.md`](../docs/installation.md) for the procedure that is
> actually exercised.

## Bootable ISO

### ISO Generation
```bash
# Build the ISO with the supported live-build pipeline
sudo bash build/build.sh
```

See [`build/README.md`](../../build/README.md).

### GRUB Configuration for Live System
```grub
menuentry 'Samurai Linux' {
    set isofile=/samurai.iso
    linux (isofile)/boot/vmlinuz boot=live config quiet
    initrd (isofile)/boot/initrd.img
}

menuentry 'Samurai Live (Failsafe)' {
    set isofile=/samurai.iso
    linux (isofile)/boot/vmlinuz boot=live config apm=off acpi=off nodma quiet
    initrd (isofile)/boot/initrd.img
}

menuentry 'Install Samurai Linux' {
    set isofile=/samurai.iso
    linux (isofile)/boot/vmlinuz boot=install quiet
    initrd (isofile)/boot/initrd.img
}
```

## Installation Steps

### 1. Language and Location
- Keyboard layout selection
- Locale settings

### 2. Network Detection
- Automatic hardware detection
- Wi-Fi or wired connection setup
- Proxy configuration if needed

### 3. Partition Selection
- **Guided partitioning** - recommended for new users
- **Manual partitioning** - advanced users
- **Full-disk encryption** - LUKS encrypted volumes supported
- **Separate /home** option

### 4. Full-Disk Encryption Options
- LUKS encryption during installation
- Prompt for passphrase
- Recovery key saved to user home (optional)
- No encryption option available

### 5. User Account Creation
- Username and password
- Strong password generation assistance
- Automatic login option (not recommended for security)
- Administrative user setup

### 6. Secure Administrator Configuration
- Sudo group membership
- SSH hardening guidance
- Root login disabled by default
- Sudo timeout configuration

### 7. Package Selection
- **Minimal install** - base system only
- **Developer profile** - core tools + editors
- **Gaming profile** - Steam, Proton, gaming tools
- **AI/Developer combo** - developer tools + AI runtime
- **Full install** - everything included

**Recommended add-ons for day-1 usability** (can be selected with developer/gaming profiles or added separately):

- `libreoffice` - office suite (Writer/Calc/Impress)
- `thunderbird` - email client
- `korganizer` - calendar
- `system-config-printer` + `simple-scan` - printing and scanning
- `transmission-gtk` - torrent client
- `dragonplayer` - video player
- `shotwell` - photo manager
- `bup` or `borgbackup` - backup tool
- `cloud-init` - automated provisioning

### 8. Developer and Gaming Profiles
```bash
# Select developer profile
samurai-install select-profile developer

# Select gaming profile
samurai-install select-profile gaming

# Select AI developer profile
samurai-install select-profile ai-dev
```

### 9. AI Runtime Setup
```bash
# Install Ollama
curl -s https://ollama.com/download/ollama-linux-amd64.tar.gz | tar -xz -C /usr/local/bin

# Pull default model
ollama pull llama3.2:3b

# Configure Samurai AI Assistant
samurai-ai configure --model llama3.2:3b

# Test inference
samurai-ai chat "Hello, how are you?"
```

### 10. Theme Selection
```bash
# Select Kuro (dark) theme
samurai-theme set kuro

# Select Shiro (light) theme  
samurai-theme set shiro

# Auto-switch based on time of day
samurai-theme auto
```

## First Boot Experience

### Initial Setup Wizard
1. Welcome and language selection
2. Network configuration
3. User account setup
4. Theme preference (Kuro/Shiro/Auto)
5. AI assistant setup (optional)
6. Developer tool installation prompt
7. Gaming profile installation prompt
8. Finish and login

### Post-Login Configuration
- Apply selected theme
- Initialize AI assistant
- Set up developer profile tools (if selected)
- Set up gaming profile (if selected)
- Check for updates
- Display introduction guide

### Recovery Guidance
- **Live ISO rescue** - boot from ISO and recover system
- **Backup configuration** - `/home/.samurai-backup/`
- **Repository recovery** - restore Samurai package repo
- **Theme recovery** - reinstall from `/usr/share/samurai/themes/`
