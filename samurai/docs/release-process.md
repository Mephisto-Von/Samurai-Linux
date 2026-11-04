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
   the promise before the artifact exists.
6. Run the test suite (`testing.md`) and validate against the criteria below
7. Publish ISO, checksum, signatures, manifest and release notes together

## Release Acceptance Criteria

A release may ship only when every criterion passes or is explicitly waived
with a documented reason. Status is recorded here so nobody has to rediscover
it:

| # | Criterion | Status today |
| --- | --- | --- |
| 1 | Bootable ISO generated and validated | build and `verify-iso.sh` run in CI; a green install test is still outstanding |
| 2 | Installation and first boot tested | the automated install test drives the real wizard to `install started`, but Calamares then segfaults two seconds into its job list, so installation and first boot have never been reached and no green run has been recorded |
| 3 | KDE Plasma works as the primary desktop | asserted by the desktop phase once it runs |
| 4 | Kuro and Shiro themes persist and function | asserted by the desktop phase once it runs |
| 5 | Developer profile usable | `samurai-profile` is tested on the installed system, but the guest has no network so real installs are not exercised |
| 6 | Security defaults and update mechanisms documented and tested | **not met** - the install test reads nftables, AppArmor, sudo policy and unattended upgrades back off the installed system, but no run has ever reached that phase; the live session's firewall additionally failed to load (cause and gate in `security.md`) |
| 7-10 | AI assistant, local mode, cloud disclosure, model routing | **not met** - no AI runtime ships |
| 11 | Gaming tested on declared supported configurations | **not met** - only the MangoHUD interposer load is checked |
| 12 | Performance measurements reproducible | harness exists (`build/measure-performance.sh`) and is gated by the install test; no numbers published yet |
| 13 | Recovery and upgrade procedures documented | documented; `samurai-recovery` is tested for snapshot/verify/restore-etc, not for a full state rollback |
| 14 | Critical defects resolved or blocking release | tracked in `known-limitations.md` |
| 15 | Build and release instructions complete | yes |
| 16 | Checksums and GPG signature verify against the published ISO | signing and verification steps exist in CI and have never run on a green build |
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
