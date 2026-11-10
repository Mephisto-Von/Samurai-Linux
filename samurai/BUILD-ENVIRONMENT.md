# Samurai Linux Build Environment

This document outlines the requirements for building the Samurai Linux ISO.

## Requirements

### Host System
- Debian trixie (or Ubuntu 24.04 LTS) as the build host
- At least 20 GB free disk space
- 16 GB RAM recommended for ISO builds
- Internet access for package downloads

### Required Packages
Install the following packages on the build host:

```bash
sudo apt-get update
sudo apt-get install -y \
    cmake \
    extra-cmake-modules \
    qt6-base-dev \
    qt6-declarative-dev \
    libkf6config-dev \
    libkf6coreaddons-dev \
    libkf6kcmutils-dev \
    libkf6i18n-dev \
    live-build \
    debootstrap \
    squashfs-tools \
    git \
    wget \
    curl
```

### GitHub Actions CI

The project uses GitHub Actions for hosted ISO builds. The workflow `.github/workflows/build-iso-hosted.yml` runs in a `debian:trixie` container and:

1. Apt-installs the build dependencies listed above (plus any additional needed packages)
2. Checks out the repository
3. Runs `build/build.sh` which:
   - Configures CMake with `CMAKE_INSTALL_PREFIX=/usr` and `CMAKE_INSTALL_LIBDIR=lib/x86_64-linux-gnu`
   - Builds the `kcm_samurai` KCM module
   - Installs it into the live-build include tree
4. Runs `build/verify-iso.sh` which asserts:
   - `kcm_samurai.so` is present in `usr/lib/x86_64-linux-gnu/qt6/plugins/plasma/kcms/systemsettings`
   - Generated `kcm_samurai.desktop` is present
   - Hub files, schemes, and wallpapers are present

### Local Build (if live-build is available)

If `live-build` is installed natively, you can build locally:

```bash
# Clone the repository
git clone https://github.com/Mephisto-Von/Samurai-Linux.git
cd Samurai-Linux

# Run the build script
sudo bash build/build.sh
```

This will:
1. Configure and build the KCM module
2. Generate the ISO with live-build
3. Verify the ISO contents

### Five Local Commits

The following local commits contain the actual changes but are unpushed:

| Commit | Description |
|---|---|
| `fa54370` | feat(hub): ship 4K wallpapers and a desktop customization app |
| `b1d2e7a` | feat(kcm): add a System Settings entry for the customization hub |
| `b19f701` | feat(wallpapers): produce the 4K set through a neural upscaler |
| `f804e02` | feat(kcm): theme picker and colour controls on the System Settings page |
| `c19d6a9` | docs: compare Samurai against the three reference ISOs in ref/ |

These commits need to be pushed and the GitHub Actions workflow triggered to start a hosted ISO build.

### Build Output Verification

After a build completes, verify:

1. ISO size matches expected values (2.95 GB Samurai, 6.28 GB Ubuntu, 5.05 GB Kali)
2. Installed packages manifest contains the recommended packages:
   - `libreoffice-core`
   - `thunderbird`
   - `korganizer`
   - `system-config-printer`
   - `simple-scan`
   - `transmission-gtk`
   - `dragonplayer`
   - `shotwell`
   - `bup` or `borgbackup`
   - `cloud-init`
3. `kcm_samurai.so` plugin is present
4. `kcm_samurai.desktop` entry is generated
5. Hub theme files and color schemes are installed

### Troubleshooting

- **cmake not found**: Install `cmake` package
- **QT6 dev packages missing**: Install the QT6 development packages for your distro
- **live-build not found**: Install `live-build` from Debian repositories
- **KCM not compiling**: Ensure all `libkf6*` dev packages are installed
- **verify-iso.sh fails**: Check that the KCM was built and installed correctly

### Environment Variables

The build script uses these environment variables:

- `CMAKE_INSTALL_PREFIX=/usr` - Installation prefix
- `CMAKE_INSTALL_LIBDIR=lib/x86_64-linux-gnu` - Library directory
- `SAMURAI_THEME_DIR` - Theme directory (overrides default)
- `SAMURAI_WALLPAPER_DIR` - Wallpaper directory (overrides default)
- `SAMURAI_HUB_DIR` - Hub directory (overrides default)

### Notes

- The build environment is known to work on Debian trixie with the packages listed above
- ISO builds may take 30-60 minutes depending on host performance
- The verification script uses `set -euo pipefail`, so failures are hard errors
- See `build/README.md` for additional build instructions