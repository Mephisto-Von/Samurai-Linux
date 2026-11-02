# Samurai Developer Environment

> **What the image actually contains** is `build-essential` (GCC, Make), CMake,
> Ninja, Git, OpenSSH client, Python 3 with `venv`, Vim, curl and wget.
> Everything else on this page is installed, not shipped: `samurai-profile`
> adds it, and `samurai-profile plan <name>` shows what apt would do first.
> `samurai-editor` is a planned helper and does not exist.

## Profiles instead of a fat image

Shipping every toolchain turns a 3 GB desktop into a 12 GB one and pins the
release to the union of twelve upstream cadences. So the base carries the
toolchain needed to build what ships, and named profiles carry the rest:

| Profile | What it adds |
| --- | --- |
| `c` | Clang, LLDB, ccache, pkg-config |
| `python` | dev headers, pip, venv, pipx, tox |
| `web` | Node.js and npm |
| `rust` | rustc and cargo |
| `go` | the Go toolchain |
| `java` | the default JDK |
| `databases` | PostgreSQL, MariaDB, Redis, SQLite |
| `containers` | rootless Podman with its networking helpers |
| `docker` | the Docker daemon |
| `virtualization` | QEMU/KVM, libvirt, virt-manager |
| `debug` | gdb, valgrind, strace, ltrace, elfutils |
| `ml` | nothing: see below |

```bash
samurai-profile list                 # the profiles above
samurai-profile show rust            # what it means, package by package
samurai-profile plan rust            # apt's own resolver, changes nothing
sudo samurai-profile install rust    # install and record a manifest
samurai-profile installed            # which profiles are complete
sudo samurai-profile remove rust     # remove it and what only it pulled in
```

`containers` and `docker` are deliberately separate: Podman and the Docker
daemon conflict over `/var/lib/containers` expectations and subuid ranges, and
a profile that installs both produces a machine whose behaviour depends on
which one started first.

**`ml` has no package list on purpose.** PyTorch and TensorFlow in Debian are
CPU builds behind the release, and the CUDA wheels people actually want come
from a vendor index that is not a Debian archive. A profile that pretended
otherwise would install something that cannot use the GPU it was installed
for. `samurai-profile show ml` prints the venv and index-url commands instead.

## Core tools that ship

### Version control and remote access
- Git; `openssh-client` for `git+ssh` and remotes. No SSH *server* is
  configured, and the firewall default-drops inbound anyway - see
  [`security.md`](security.md).

### Compilers and build systems
- GCC, Make (in `build-essential`), CMake, Ninja.
- Clang and LLDB are the `c` and `debug` profiles.

### Languages
- Python 3 and `python3-venv` ship. pip, pipx, tox and the rest of the
  interpreters are profiles.

## Editors and IDEs

Nothing beyond Vim ships, and no editor configuration is applied to a new user.
VS Code and VSCodium are not in Debian's archives at all - they are downloaded
from third-party repositories, which this project does not sign, mirror or
test, so there is no `samurai-profile` for them either. Install them the way
their own documentation says and treat updates as your responsibility.
Qt Creator, Neovim and JetBrains IDEs are ordinary apt or vendor installs.

## Checking that a profile really worked

`samurai-profile install` records the versions dpkg reported after apt
finished, and `installed` re-reads each one rather than trusting its own
record, so a package that apt "installed" but dpkg left unconfigured shows as
incomplete with the package named. Before touching anything, `samurai-recovery
snapshot` captures `/etc` and the exact package set, and `restore-packages`
removes whatever appeared after it - see
[`known-limitations.md`](known-limitations.md) for what that cannot undo.
