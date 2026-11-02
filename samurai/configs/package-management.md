# Samurai Package Management and Updates

> **Legacy design document.** None of the commands below exist: there is no
> `samurai-repo`, `samurai-packages`, `samurai-upgrade`, `samurai-repo-report`
> or `samurai-repo-update`, no `/var/log/samurai/` and no Samurai APT
> repository. What actually ships (`samurai-profile`, `samurai-recovery`, apt
> pinning and unattended security upgrades) is described in
> [`../docs/architecture.md`](../docs/architecture.md) and
> [`../docs/known-limitations.md`](../docs/known-limitations.md).

## Debian Foundation
- **Package ecosystem**: Debian's APT system
- **Repository foundation**: Official Debian repositories
- **Package format**: .deb files with .control, .postinst, etc.

## Samurai Repository

### Custom Repository Structure
```
samurai-repo/
├──dists/
│  ├──trixie/
│  │  ├──main/
│  │  │  ├──binary-amd64/Packages
│  │  │  └──Sources/
│  │  ├──contrib/
│  │  │  └──non-free/
│  │  └──samurai/
│  │     ├──appinfo/
│     │     └ivedependencies/
│  │     └── translated/
│  ├──testing/
│  └──unstable/
├──pool/
│  ├──main/
│  │  └──s/samurai-theme/
│  ├──contrib/
│  └──non-free/
├──dists/
│  └──inrelease
└──inrelease
```

### Package Manifests
```bash
# Update package lists
sudo samurai-repo-update

# View available Samurai packages
samurai-packages list

# View package details
samurai-packages info <package-name>
```

### Versioned Releases
- **samurai-1.0** - Initial release
- **samurai-1.1** - Feature updates
- **samurai-1.2** - Bug fixes and security updates

### Dependency Management
- All Samurai packages declare `Samurai` as a meta-package dependency
- Controlled strategy for mixing repository types
- Pinning priorities for stable base + Samurai additions

```bash
# Pin priorities in /etc/apt/preferences.d/samurai
Package: samurai-theme
Pin: release o=Samurai Linux
Pin-Priority: 600

Package: *
Pin: release o=Debian
Pin-Priority: 500
```

### Package Signature Verification
```bash
# Verify package signatures
dpkg-sig --verify <package>.deb

# Repository metadata signing
apt-ftparchive sign
```

### Security Updates
- Debian security tracker integration
- Samurai-specific security advisories
- Automatic security update configuration

```bash
# Enable security updates
sudo samurai-security enable

# Check for pending security updates
samurai-security pending

# Apply security updates
sudo samurai-security apply
```

### Upgrade Testing
- Staged rollout: testing → stable
- Release notes for each update
- Rollback guidance

```bash
# Safe upgrade
sudo samurai-upgrade safe

# Full upgrade with testing
sudo samurai-upgrade testing

# Rollback if needed
sudo samurai-upgrade rollback
```

### Conflict and Failure Reporting
- Clear error messages
- Suggested resolutions
- Log collection for debugging

```bash
# Report package conflict
samurai-repo-report --conflict <package1> <package2>

# View failure logs
sudo less /var/log/samurai/package-manager.log
```
