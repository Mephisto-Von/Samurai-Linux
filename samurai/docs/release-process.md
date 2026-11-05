# Samurai Linux Release Process

## Versioning
- **Format**: `YYYY.MM` (calendar versioning, e.g. `2026.10`)
- **Point releases**: security and critical-bug fixes only
- **What a release consists of today**: a signed ISO, its SHA-256 checksum, the
  detached signatures over both, and the installed-package manifest produced by
  `build/verify-iso.sh`. There is **no Samurai APT repository**, so there are no
  versioned repositories and no `stable`/`unstable` channels; upgrades happen by
  installing a newer ISO or through Debian's own archives.

## Release Pipeline
1. Verify the build host (50 GB+ disk, 4 GB+ RAM, x86_64)
2. Run `bash build/build.sh --check`
3. Build the ISO with `sudo bash build/build.sh` (writes `dist/*.iso` and `.sha256`)
4. Sign the artifacts with the project key. CI does this in
   `.github/workflows/build-iso-hosted.yml`; locally:
   ```bash
   cd dist
   gpg --local-user SAMURAI_RELEASE_KEY_ID --armor --detach-sign \
       --output samurai-linux-YYYY.MM.DD-amd64.iso.sig \
       samurai-linux-YYYY.MM.DD-amd64.iso
   gpg --local-user SAMURAI_RELEASE_KEY_ID --armor --detach-sign \
       --output samurai-linux-YYYY.MM.DD-amd64.iso.sha256.sig \
       samurai-linux-YYYY.MM.DD-amd64.iso.sha256
   ```
   Every `dist/*.packages.tsv` manifest is signed the same way. The build fails
   if a checksum or manifest exists without its signature, and it fails if the
   key in the `SAMURAI_RELEASE_GPG_PRIVATE_KEY` secret does not match
   `samurai/keys/samurai-release.fpr`, so a published ISO is always traceable to
   the key committed in this repository.
5. **Do not tag until the install test for that commit is green.** A tag is the
   promise that the ISO installs and boots; tagging an unverified build breaks
   the promise before the artifact exists. `scripts/release-gate.sh --check SHA
   DIST [TAG]` enforces the sentence: it takes the newest completed-successful
   **Install test** run whose `head_sha` is this commit, reads the
   `Using ISO artifact from run <id>` line out of that run's own log, requires
   that build run to be completed and successful, downloads and authenticates
   exactly that artifact, and dies otherwise - including when a green run exists
   at a *different* commit, which is the mistake the artifact-reuse history
   actually made. It publishes nothing that the install test did not install.
6. Run the test suite (`testing.md`) and validate against the criteria below
7. Publish ISO, checksum, signatures, manifest and release notes together.
   `.github/workflows/release.yml` does this, and only on a human dispatch: it
   runs the gate, then `gh release create` with the notes the gate wrote
   (`--target` the checked commit, never the workflow's own HEAD). `dry_run`
   defaults to **true**, so dispatching it by habit publishes nothing.

### What the gate cannot yet satisfy

The `samurai-linux-iso` artifact of build run `42105485811` is 2.74 GiB. GitHub
refuses a release asset larger than 2 GiB, so on today's image steps 5-7 pass
their checks and then fail at the upload - a tag with no release behind it, the
worst of the two outcomes. `check_asset_pairing` therefore compares the ISO
against `SAMURAI_MAX_ASSET_BYTES` (default 2147483648) and stops before the tag.
Resolving it means either slimming the image below 2 GiB - the desktop, firmware
and language packagings are where the size is - or publishing the ISO somewhere
that has no such limit and letting the GitHub Release link to it. That choice
belongs to the project owner and is recorded here rather than made silently by
a script.

## Release Acceptance Criteria

A release may ship only when every criterion passes or is explicitly waived
with a documented reason. Status is recorded here so nobody has to rediscover
it:

| # | Criterion | Status today |
| --- | --- | --- |
| 1 | Bootable ISO generated and validated | build and `verify-iso.sh` run in CI; a green install test is still outstanding |
| 2 | Installation and first boot tested | the automated install test drives the real wizard past every mandatory requirement and onto the partition page (run `41989352435`); the earlier job-2 segfault is gone. No run has reached the execution page yet, because in QEMU the live Wayland compositor SIGSEGVs when the partition preview mounts targets and Calamares loses its display with it, and the X11 session the test falls back to had no compositor installed (`kwin-x11`, now added and gated by `verify-iso.sh`); switching to it then left SDDM's **greeter** on the display, because the autologin drop-in the test wrote was ignored and the Wayland session it started in its place exited (runs `42105485811`, `42112234958`). Installation and first boot therefore remain unreached, and no green run has been recorded |
| 3 | KDE Plasma works as the primary desktop | asserted by the desktop phase once it runs |
| 4 | Kuro and Shiro themes persist and function | asserted by the desktop phase once it runs |
| 5 | Developer profile usable | `samurai-profile` is tested on the installed system, but the guest has no network so real installs are not exercised |
| 6 | Security defaults and update mechanisms documented and tested | **not met** - the install test reads nftables, AppArmor, sudo policy and unattended upgrades back off the installed system, but no run has ever reached that phase because no run has finished an installation. The firewall's own history is closed at image level: the live-session load failure had a real cause (kernel/modules split), the build now prevents it, `verify-iso.sh` gates it, and run `41896746985` read the running ruleset back (`table inet samurai`, `chain ingress ... policy drop`, `nftables.service` exit `0/SUCCESS`). Evidence and the remaining gap are in `security.md` |
| 7-10 | AI assistant, local mode, cloud disclosure, model routing | **not met** - no AI runtime ships |
| 11 | Gaming tested on declared supported configurations | **not met** - only the MangoHUD interposer load is checked |
| 12 | Performance measurements reproducible | harness exists (`build/measure-performance.sh`) and is gated by the install test; no numbers published yet |
| 13 | Recovery and upgrade procedures documented | documented; `samurai-recovery` is tested for snapshot/verify/restore-etc, not for a full state rollback |
| 14 | Critical defects resolved or blocking release | tracked in `known-limitations.md` |
| 15 | Build and release instructions complete | yes |
| 16 | Checksums and GPG signature verify against the published ISO | signing and verification steps exist in CI and have never run on a green build; `scripts/release-gate.sh` now verifies both against `samurai/keys/` before anything is published, and refuses an ISO larger than the release host accepts |
| 17 | APT repository publication and upgrade path tested | **not met** - no Samurai APT repository exists |

## Signing and Publication
- **ISO**: SHA-256 checksum plus a GPG-armored detached signature over the ISO
  and over its checksum file
- **Manifest**: the installed-package list is signed, so a report of what the
  image contains is attributable
- **Trust chain**: `samurai/keys/samurai-release.asc` and
  `samurai/keys/samurai-release.fpr` are committed, so a reader who trusts only
  this repository can import the key and check the artifacts; `install-test.yml`
  does exactly that before it boots the ISO
- **Release notes**: known limitations, upgrade instructions, checksums
- **Archive**: previous releases stay available for recovery
- **Not published**: APT repositories, because none are built

## Hotfix and Rollback
- **Hotfixes**: point release built from the tagged source with only the fix applied
- **Package rollback**: APT keeps no snapshot. `samurai-recovery` can restore
  `/etc` files and replay a selection list from a snapshot, which is a partial
  mitigation, not a rollback; see `known-limitations.md`
- **ISO rollback**: previous ISO remains downloadable until superseded and verified
