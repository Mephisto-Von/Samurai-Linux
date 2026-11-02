# Samurai Linux security status

The project requirements forbid claiming a control is enabled because its
package is installed, so every row below says what the image actually configures
and how that is proven. **Tested** means an automated check in
`build/install-test.py` reads the state back from a system installed by the CI
ISO; **implemented** means the configuration ships and the build would fail if
it were missing or malformed, but no installed-system check reads it yet.

| Control | Status | How it is proven |
| --- | --- | --- |
| Non-root daily account, admin through `%sudo` | tested | the harness logs in as `samurai`, and `sudo -i` needs the user's password |
| No passwordless sudo on an installed system | tested | `grep -rEl '^[^#]*NOPASSWD' /etc/sudoers /etc/sudoers.d/` must find nothing |
| sudo behaviour (`env_reset`, 5-minute ticket, 3 tries) | implemented | `visudo -c` in `0120-security.hook.chroot`; file must be `0440 root` or the build fails |
| Default-deny inbound firewall (IPv4 **and** IPv6) | tested | `systemctl is-enabled nftables` and `nft list table inet samurai` must show `chain ingress` with `policy drop` |
| Mandatory access control (AppArmor) | partly tested | kernel parameter must be `Y` and at least one profile must be loaded; enforce/complain counts are recorded, not asserted |
| Automatic security upgrades | tested | `APT::Periodic::Unattended-Upgrade` must be `"1"`, both apt timers must be `enabled`, the package `unattended-upgrades` must be installed, and the effective `Allowed-Origins` must name `Debian:trixie-security` |
| Authenticated package sources | tested at build time, configured at install time | `0120-security.hook.chroot` aborts the build unless `apt-get update` authenticates a `trixie-security` archive *and* that archive's own `Origin:` field matches the origin `20samurai-security` names; the installed system must still configure the pocket, which it does from the shipped `/etc/apt/sources.list.d/samurai-security.list` (`verify-iso.sh` fails the build if the image carries no security source, or carries the same one twice) |
| APT pinning that keeps security preferred | implemented | `99samurai` ships in the image; the installed system's `apt-cache policy` priorities are not yet asserted |
| Persistent system journal | tested | `/var/log/journal` must exist after first boot, which only happens if `Storage=persistent` was read |
| Release artifact integrity | implemented | the build signs the ISO, its checksum and the package manifest and verifies each signature as it writes it; `install-test.yml` re-imports the key from `samurai/keys/`, checks it against the committed fingerprint and verifies all three. No green run of that step exists yet |
| Rollback / recovery after a failed update | partly tested | `samurai-recovery snapshot`, `verify` and `restore-etc` run on the installed system in CI; restoring a *package* set needs a networked guest, and this is not a filesystem snapshot - see `known-limitations.md` |
| Full-disk (LUKS) encryption during install | **not verified** | Calamares ships Debian's partition module configuration, which the project does not modify; no Samurai test has completed an encrypted installation |
| Secure Boot | **not supported** | no shim signing exists, so the ISO boots only with Secure Boot off or with a user-supplied MOK key |
| Vulnerability intake and patch process | **incomplete** | private reporting is described below, but there is no security contact, advisory feed, or documented CVE pipeline yet |

## Network exposure

`/etc/nftables.conf` implements the policy: drop unsolicited inbound, allow
outbound, accept what the conntracker recognises as a reply to something we
started, and keep the protocols a machine cannot configure itself without
(DHCPv4, DHCPv6, IPv6 neighbour/router discovery, rate-limited ICMP echo).
Dropped packets are logged at ten per minute with the prefix `samurai-drop: `.

The default is deliberately the *workstation* default: a developer machine
listens on nothing until the developer starts something. Opening a port is an
explicit act, done by dropping a file in `/etc/nftables.d/`:

```
# /etc/nftables.d/10ssh.nft
add rule inet samurai ingress_exceptions tcp dport 22 ct state new accept
```

`forward` is dropped as well, so the machine never becomes a router or a bridge
between networks without a rule saying so.

The exception chain is jumped to from the input hook rather than hung on a
second, later hook: a `drop` verdict ends traversal of the hook chain, so an
accept chain at a lower priority would never be consulted.

## Package sources and updates

Samurai Linux installs no third-party APT repository. Every package comes from
a Debian archive, fetched over HTTP and authenticated by the `InRelease`
signature against `debian-archive-keyring` — Debian does not sign individual
`.deb` files, so archive signature is the trust boundary.

`/etc/apt/preferences.d/99samurai` pins `trixie-security` above the release and
holds `trixie-backports` and `trixie-proposed-updates` at priority 1, where they
can only be pulled in deliberately with `apt install -t`.

Security updates apply themselves: `APT::Periodic::Update-Package-Lists`,
`Download-Upgradeable-Packages` and `Unattended-Upgrade` are all `1`, driven by
the `apt-daily` and `apt-daily-upgrade` timers that the image enables, and
`unattended-upgrades` is installed to do the work.

Which archives that updater is allowed to touch is **not** left to Debian's
`50unattended-upgrades`, because its entries are built from `${distro_id}` —
which comes from `/etc/lsb-release`, and this project rebrands that file to
`DISTRIB_ID=Samurai`. Substituted here, Debian's default origin becomes
`Samurai:trixie-security`, an origin no Debian `Release` file has ever carried,
so the stock list matches nothing and no package would ever be upgraded while
every timer, switch and package in the table above still looked correct. So
`20samurai-security` names the origin literally (`Debian:trixie-security`), and
the build hook reads the `Origin:` field back out of the `Release` file apt
just authenticated and fails if the literal stops matching. What remains in that
file is the behaviour Debian's defaults aim at servers: never reboot
automatically, and drop dependencies an upgrade orphaned.

## Access control

The `samurai` account created by the installer is a normal user in `%sudo`.
`/etc/sudoers.d/90samurai` resets the environment, times a cached ticket out
after five minutes, and stops after three wrong passwords. The hook that
installs it runs `visudo -c` on both the fragment and the merged policy, and
`chmod 0440`, because sudo silently ignores a sudoers drop-in that is group- or
world-writable — a policy file with the wrong mode is a policy that is not
applied.

## Mandatory access control

AppArmor is enabled at boot and its profiles load from the read-only image.
Debian ships profiles in a mix of enforce and complain modes, so the automated
test asserts only what it can prove: that the kernel has AppArmor on and that
profiles were loaded. The enforce/complain counts are recorded in the install
test report so that a claim about coverage can be checked against a number
rather than assumed.

## Logging

`/etc/systemd/journald.conf.d/99samurai.conf` sets `Storage=persistent`, so the
firewall's dropped-packet records, failed sudo attempts and service errors
survive a reboot instead of dying with `/run/log`.

## Release artifact integrity

`build/build.sh` writes a `.sha256` and, when `SAMURAI_SIGN_KEY` is set, a
GPG-armored detached signature for the ISO; the hosted CI workflow signs with
the project release key and publishes the public key alongside the artifacts.
Verify a download with:

```
sha256sum -c samurai-linux-<version>-amd64.iso.sha256
gpg --import samurai-release-key.asc
gpg --verify samurai-linux-<version>-amd64.iso.sig
```

## AI feature credentials

`samurai-ai` stores provider keys through the Secret Service (`secret-tool`,
backed by KWallet) and says so in `samurai-ai status`. When no Secret Service is
running it falls back to a `0600` file under `~/.config/samurai-ai/` and labels
that fallback `NOT encrypted` rather than pretending it is a wallet. No AI
request leaves the machine without an explicit user action, and privileged
actions a model proposes require confirmation first.

## Secure Boot

Not implemented. Signing a shim requires a trusted CA key, a source of that
signature, and hardware or firmware enrolment to test against; none of that
exists here. Users who need it can enrol their own MOK key, which is a
per-machine decision the project cannot verify for them.

## Reporting issues

Report suspected vulnerabilities to the maintainers privately before public
disclosure. Critical defects block a release until they are fixed or explicitly
waived in writing (see `release-process.md`). A security contact address and an
advisory process are outstanding (§5 checklist above).
