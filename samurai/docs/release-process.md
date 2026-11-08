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

The gate compares full SHAs, which has a cost worth stating before someone
meets it: a commit after the green run - even a documentation-only one - makes
that run green for a commit that is no longer the release candidate, and the
release is refused. Re-run the install test against the same ISO artifact (the
dispatch takes `run_id`, and the artifact survives seven days) rather than
loosening the comparison, because "close enough" is exactly how a green run came
to describe an image nobody could download.

The `samurai-linux-iso` artifact of build run `42105485811` is 2,942,402,229
bytes (2.74 GiB). GitHub refuses a release asset larger than 2 GiB, so the
gate cannot upload that image as one file. The project's answer is to publish
it in parts: `check_asset_pairing` splits an ISO above
`SAMURAI_MAX_ASSET_BYTES` (default 2147483648) into pieces of at most
`SAMURAI_SPLIT_PART_BYTES` (default 1992294400, 1900 MiB), refuses to continue
unless the parts rebuild the SHA-256 recorded beside the ISO, writes a
`*.parts.sha256` file and `REASSEMBLE.txt`, and the release workflow uploads
the parts instead of the ISO. A user reassembles with `cat`, checks the parts
and the whole image, and verifies the signature. The gate self-test exercises
the split, a mismatched checksum, and the whole-file path with a lowered
ceiling, so this is a tested decision rather than a note.

## Release Acceptance Criteria

A release may ship only when every criterion passes or is explicitly waived
with a documented reason. Status is recorded here so nobody has to rediscover
it:

| # | Criterion | Status today |
| --- | --- | --- |
| 1 | Bootable ISO generated and validated | met: build and `verify-iso.sh` run in CI, and install-test run `42392182476` is green end to end |
| 2 | Installation and first boot tested | met in QEMU: run `42392182476` walked the wizard, wrote the disk, installed the bootloader, booted the installed system and verified it. Real-hardware partitioning, LUKS and Secure Boot remain manual checks |
| 3 | KDE Plasma works as the primary desktop | met: the desktop phase of run `42392182476` started `plasmashell`, found a renderer and captured a non-blank frame |
| 4 | Kuro and Shiro themes persist and function | met for applying and recording a scheme in a live session (`samurai-theme set shiro` read back from `kdeglobals` and the wallpaper read back from Plasma); persistence across a reboot is not separately asserted |
| 5 | Developer profile usable | `samurai-profile` is tested on the installed system, but the guest has no network so real installs are not exercised |
| 6 | Security defaults and update mechanisms documented and tested | met as configured state: run `42392182476` read the policy back off the installed system - nftables, AppArmor and the apt periodic timers enabled, the running ruleset denying unsolicited inbound traffic, `apparmor profiles: profiles=130 complain=44`, `Allowed-Origins:: "Debian:trixie-security"`, and a persistent journal. The firewall's own history is closed at image level: the live-session load failure had a real cause (kernel/modules split), the build now prevents it, `verify-iso.sh` gates it, and run `41896746985` read the running ruleset back (`table inet samurai`, `chain ingress ... policy drop`, `nftables.service` exit `0/SUCCESS`). What is still not tested is a real patch event arriving and being applied - see `security.md` |
| 7-10 | AI assistant, local mode, cloud disclosure, model routing | **not met** - no AI runtime ships |
| 11 | Gaming tested on declared supported configurations | **not met** - only the MangoHUD interposer load is checked |
| 12 | Performance measurements reproducible | harness exists (`build/measure-performance.sh`), is gated by the install test, and a green run carries a `performance.txt`; no numbers are published in the documentation yet |
| 13 | Recovery and upgrade procedures documented | documented; `samurai-recovery` is tested for snapshot/verify/restore-etc, not for a full state rollback |
| 14 | Critical defects resolved or blocking release | tracked in `known-limitations.md` |
| 15 | Build and release instructions complete | yes |
| 16 | Checksums and GPG signature verify against the published ISO | met for `v2026.11`: the install test verifies the ISO, its checksum and the package manifest against `samurai/keys/` before installing, `scripts/release-gate.sh` re-verifies them before anything is published, and an ISO larger than the release host accepts is split into parts whose reassembly the gate verifies |
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
