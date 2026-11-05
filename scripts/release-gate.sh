#!/usr/bin/env bash
# Decide whether a tag may be published, and gather exactly what it publishes.
#
# The rule this script exists to enforce is release-process.md step 5: "do not
# tag until the install test for that commit is green". As a sentence it is a
# promise a person has to remember, and the repository history shows what
# happens otherwise - the ISO artifact an install test used was several builds
# old, so a green run proved an image nobody would have downloaded. Here the
# promise is mechanical: the release names the install-test run that passed,
# reads from that run's own log which build produced the ISO it installed, and
# publishes that artifact or nothing.
#
# --check needs `gh`, GH_TOKEN and GITHUB_REPOSITORY; --self-test needs none of
# them and is what tests/smoke.sh runs.
set -euo pipefail

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
log() { printf '%s\n' "$*"; }

# The scratch directory the self-test makes. Global because the EXIT trap runs
# after the function that created it has returned, where a local name no longer
# exists and `set -u` turns cleanup itself into a failure.
GATE_TMP=""
cleanup() {
    [[ -z "$GATE_TMP" ]] || rm -rf "$GATE_TMP"
    return 0
}
trap cleanup EXIT

# Newest completed-successful run of install-test.yml at this commit. Prints its
# run id, or nothing when there is no such run.
#
# The build workflow's own conclusion says nothing about the installer: its
# "Build live ISO" job succeeds whether or not the install test chained to it
# passed, so filtering on the build would publish an ISO that was never
# installed. Only install-test.yml counts, and only when it finished - a run
# still in progress has no conclusion to read and its ISO is unproven.
green_install_run_at() {
    local runs_json=$1 sha=$2
    printf '%s\n' "$runs_json" | python3 -c '
import json, sys
wanted = sys.argv[1]
try:
    runs = json.load(sys.stdin).get("workflow_runs", [])
except Exception:
    sys.exit(0)
for run in runs:
    if (
        run.get("name") == "Install test"
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
        and run.get("head_sha") == wanted
    ):
        print(run["id"])
        break
' "$sha"
}

# What the visible install-test runs actually were, for the operator who is told
# "no green run exists" and needs to know whether that means "red", "still
# running" or "green but at a commit that is not this one".
describe_runs() {
    python3 -c '
import json, sys
for run in json.load(sys.stdin).get("workflow_runs", []):
    if run.get("name") != "Install test":
        continue
    print("  %s %s %s %s" % (run["id"], run.get("head_sha", "")[:8],
                             run.get("status"), run.get("conclusion")))
'
}

# The build run whose ISO artifact a green install test actually installed.
# install-test.yml prints this line after resolving its run id, and it is the
# only place that names the artifact the installer booted.
select_iso_run_from_log() {
    local log_text=$1
    printf '%s\n' "$log_text" | sed -n 's/.*Using ISO artifact from run \([0-9][0-9]*\).*/\1/p' | head -n 1
}

# Whether the ISO is small enough for the host the release would live on.
#
# This belongs in the gate because it is a real answer, not a hypothetical: the
# samurai-linux-iso artifact of build run 42105485811 is 2.74 GiB, and GitHub
# refuses a release asset larger than 2 GiB. Everything else can pass - green
# install test, signed and paired assets - and the publish step still fail, at
# which point the tag exists and the release does not. Shrinking the image or
# choosing another host is a decision, so the number is stated instead of a
# choice being made here. The limit is an environment variable so the
# self-test can exercise both directions without building a 2 GiB file.
max_asset_bytes() { printf '%s\n' "${SAMURAI_MAX_ASSET_BYTES:-2147483648}"; }

# Every artifact a release must carry, paired with the files that authenticate
# it, and sized against what the release host accepts. Split out of the network
# work so tests/smoke.sh can exercise every direction: a complete set passes, a
# missing signature fails, an over-sized ISO fails.
check_asset_pairing() {
    local dist=$1
    local iso
    iso=$(find "$dist" -maxdepth 1 -name '*.iso' -print -quit)
    [[ -n "$iso" ]] || die "no ISO to publish in $dist"
    [[ -e "$iso.sha256" ]] || die "the ISO $iso has no checksum beside it"
    [[ -e "$iso.sig" ]] || die "the ISO $iso is not signed"
    [[ -e "$iso.sha256.sig" ]] || die "the checksum beside $iso is not signed"
    local manifest found_manifest=0
    for manifest in "$dist"/*.packages.tsv; do
        [[ -e "$manifest" ]] || continue
        found_manifest=1
        [[ -e "$manifest.sig" ]] || die "the package manifest $manifest is not signed"
    done
    ((found_manifest)) || die "no package manifest in $dist: a release without a signed \
installed-package list cannot be triaged for security holes"
    local limit bytes
    limit=$(max_asset_bytes)
    bytes=$(wc -c < "$iso" | tr -d '[:space:]')
    [[ "$bytes" =~ ^[0-9]+$ ]] || die "cannot read the size of $iso"
    if ((bytes > limit)); then
        die "$iso is $bytes bytes and the release host allows $limit per asset. Either
slim the image below that or publish it somewhere else; a tag pushed before
that choice is made names a release that cannot exist"
    fi
    printf 'ISO %s is %s bytes (the release host allows %s per asset)\n' \
        "$(basename "$iso")" "$bytes" "$limit" >&2
    printf '%s\n' "$iso"
}

# What the release body says. It names the evidence rather than describing the
# product, because every claim a user cannot check is a claim nobody can falsify.
write_release_notes() {
    local out=$1 iso=$2 iso_run=$3 install_run=$4 sha=$5 tag=$6
    local checksum
    checksum=$(awk '{ print $1 }' "$iso.sha256")
    {
        printf '## Samurai Linux %s\n\n' "${tag#v}"
        printf 'Image: `%s`\n\n' "$(basename "$iso")"
        printf -- '- SHA-256: `%s`\n' "$checksum"
        printf -- '- Size: %s bytes\n' "$(wc -c < "$iso" | tr -d '[:space:]')"
        printf -- '- Signed with the release key published in `samurai/keys/`.\n'
        printf -- '- Built by run <https://github.com/%s/actions/runs/%s>\n' "$GITHUB_REPOSITORY" "$iso_run"
        printf -- '- Installed and booted by run <https://github.com/%s/actions/runs/%s>\n' \
            "$GITHUB_REPOSITORY" "$install_run"
        printf -- '- Commit: `%s`\n\n' "$sha"
        printf 'Verify before installing:\n\n'
        printf '```bash\n'
        printf 'gpg --import samurai-release-key.asc\n'
        printf 'gpg --verify %s.sig %s\n' "$(basename "$iso")" "$(basename "$iso")"
        printf 'sha256sum -c %s.sha256\n' "$(basename "$iso")"
        printf '```\n\n'
        printf 'What this release does not claim: no Samurai APT repository exists, Secure Boot\n'
        printf 'is not supported, and the first-boot setup wizard is not implemented. See\n'
        printf '`samurai/docs/known-limitations.md` in the tagged commit for the full list.\n'
    } > "$out"
}

check_release() {
    local sha=$1 dist=$2 tag=${3:-${GITHUB_REF_NAME:-}}
    # release-process.md fixes the version format as YYYY.MM with point
    # releases, so the gate refuses anything else rather than minting a tag no
    # document describes.
    [[ "$tag" =~ ^v[0-9]{4}\.[0-9]{2}(\.[0-9]+)?$ ]] || die "the release tag '$tag' is not a
Samurai version: release-process.md defines vYYYY.MM or vYYYY.MM.N, and a tag
is what users quote when they report what they installed"
    command -v gh >/dev/null 2>&1 || die "gh is required to check a release"
    [[ -n "${GH_TOKEN:-}${GITHUB_TOKEN:-}" ]] || die "GH_TOKEN is required to check a release"
    [[ -n "${GITHUB_REPOSITORY:-}" ]] || die "GITHUB_REPOSITORY is required to check a release"
    local repo=$GITHUB_REPOSITORY
    mkdir -p "$dist"

    # green_install_run_at compares full SHAs, so a dispatch that names a commit
    # shortly - or a branch - is resolved once here rather than silently
    # matching nothing and reporting "no green install test exists".
    if [[ ! "$sha" =~ ^[0-9a-f]{40}$ ]]; then
        sha=$(gh api "repos/$repo/commits/$sha" --jq '.sha' 2>/dev/null || true)
        [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || die "the requested commit cannot be resolved to a full SHA"
    fi
    log "release candidate commit: $sha"

    local runs_json install_run
    runs_json=$(gh api "repos/$repo/actions/workflows/install-test.yml/runs?per_page=50")
    install_run=$(green_install_run_at "$runs_json" "$sha")
    if [[ -z "$install_run" ]]; then
        printf 'install-test runs this script can see:\n' >&2
        printf '%s\n' "$runs_json" | describe_runs >&2
        die "no green install test exists for commit $sha; a tag is the promise that the ISO installs"
    fi
    log "green install test for $sha: run $install_run"

    local iso_run
    iso_run=$(select_iso_run_from_log "$(gh run view --repo "$repo" "$install_run" --log 2>/dev/null || true)")
    [[ -n "$iso_run" ]] || die "install-test run $install_run does not name the build run its ISO came from"
    log "that install test installed the artifact of build run $iso_run"

    local build_conclusion
    build_conclusion=$(gh api "repos/$repo/actions/runs/$iso_run" \
        --jq '{status: .status, conclusion: .conclusion} | "\(.status) \(.conclusion)"' 2>/dev/null || echo "unknown none")
    [[ "$build_conclusion" == "completed success" ]] \
        || die "build run $iso_run is '$build_conclusion', not a completed successful build"

    local artifact_id
    artifact_id=$(gh api "repos/$repo/actions/runs/$iso_run/artifacts?per_page=100" \
        --jq '.artifacts[] | select(.name == "samurai-linux-iso" and .expired == false) | .id' | head -n 1)
    if [[ -z "$artifact_id" ]]; then
        die "build run $iso_run has no unexpired samurai-linux-iso artifact; GitHub keeps it for
seven days, so tag within that window or re-run the build and the install test"
    fi

    # The artifact is downloaded with curl rather than actions/download-artifact
    # because that action fails on the 301 a renamed repository answers with.
    local zip=$dist/release-artifact.zip
    curl -fsSL --retry 3 --retry-delay 5 \
        -H "Authorization: Bearer ${GH_TOKEN:-${GITHUB_TOKEN:-}}" \
        -H "Accept: application/vnd.github+json" \
        -o "$zip" "https://api.github.com/repos/$repo/actions/artifacts/$artifact_id/zip"
    unzip -q -o "$zip" -d "$dist"
    rm -f "$zip"

    local iso
    # `|| exit 1` rather than trusting errexit through the command
    # substitution: the check below reports its own reason and a release must
    # not continue when it does.
    iso=$(check_asset_pairing "$dist") || exit 1

    # Authenticate with the key the repository documents, not the key that
    # travelled beside the ISO: the artifact's own .asc proves only that a
    # bundle is self-consistent, and an attacker who can replace the artifact
    # can replace that too.
    local gnupg
    gnupg=$(mktemp -d)
    chmod 700 "$gnupg"
    GNUPGHOME=$gnupg gpg --batch --import samurai/keys/samurai-release.asc
    local recorded actual
    recorded=$(tr -d '[:space:]' < samurai/keys/samurai-release.fpr)
    actual=$(GNUPGHOME=$gnupg gpg --with-colons --list-keys | awk -F: '$1 == "fpr" { print $10; exit }')
    [[ "$recorded" == "$actual" ]] || die "the repository key is not the key its fingerprint records:
  recorded $recorded
  imported $actual"
    (cd "$dist" && sha256sum -c "$(basename "$iso").sha256")
    GNUPGHOME=$gnupg gpg --verify "$iso.sig" "$iso"
    GNUPGHOME=$gnupg gpg --verify "$iso.sha256.sig" "$iso.sha256"
    local manifest
    shopt -s nullglob
    for manifest in "$dist"/*.packages.tsv; do
        GNUPGHOME=$gnupg gpg --verify "$manifest.sig" "$manifest" || die "the manifest $manifest is not signed by the release key"
    done
    # Publish the public half beside the release so a user can verify without
    # cloning this repository first - while the keyring still exists.
    GNUPGHOME=$gnupg gpg --armor --export > "$dist/samurai-release-key.asc"
    cp samurai/keys/samurai-release.fpr "$dist/samurai-release-key.fpr"
    rm -rf "$gnupg"

    write_release_notes "$dist/release-notes.md" "$iso" "$iso_run" "$install_run" "$sha" "$tag"
    log "ready to publish: $(basename "$iso"), its checksum and signatures, the signed manifest, the public key"
    log "gate: install-test run $install_run on commit $sha"
    printf '%s\n' "$install_run" > "$dist/release-gate.txt"
}

self_test() {
    local fixture fail=0
    GATE_TMP=$(mktemp -d)
    local tmp=$GATE_TMP

    cat > "$tmp/runs.json" <<'JSON'
{"workflow_runs": [
 {"id": 100, "name": "CI", "head_sha": "aaa", "status": "completed", "conclusion": "success"},
 {"id": 200, "name": "Install test", "head_sha": "aaa", "status": "completed", "conclusion": "failure"},
 {"id": 300, "name": "Install test", "head_sha": "aaa", "status": "completed", "conclusion": "success"},
 {"id": 400, "name": "Build ISO (hosted)", "head_sha": "aaa", "status": "completed", "conclusion": "success"}
]}
JSON
    fixture=$(cat "$tmp/runs.json")
    local picked
    picked=$(green_install_run_at "$fixture" aaa)
    if [[ "$picked" != "300" ]]; then
        log "FAIL: the green install run selector picked '$picked', expected '300'"
        fail=1
    else
        log "ok - a successful install-test run is picked and CI/build runs are not"
    fi

    # The same green run does not vouch for a different commit: publishing an
    # ISO because "the install test passed" two commits back is exactly the
    # mistake the artifact-reuse history made.
    if [[ -n "$(green_install_run_at "$fixture" bbb)" ]]; then
        log "FAIL: a green run at another commit was picked"
        fail=1
    else
        log "ok - a green run at another commit does not open this release"
    fi

    local none
    none=$(green_install_run_at '{"workflow_runs": [{"id": 200, "name": "Install test", "head_sha": "aaa", "status": "completed", "conclusion": "failure"}]}' aaa)
    if [[ -n "$none" ]]; then
        log "FAIL: a run that failed was still picked: '$none'"
        fail=1
    else
        log "ok - a failed install-test run is not green"
    fi

    # A run whose workflow is still going has no conclusion yet; picking it
    # would publish an ISO whose installer was still on the welcome page.
    local running
    running=$(green_install_run_at '{"workflow_runs": [{"id": 500, "name": "Install test", "head_sha": "aaa", "status": "in_progress", "conclusion": null}]}' aaa)
    if [[ -n "$running" ]]; then
        log "FAIL: an in-progress install-test run was picked: '$running'"
        fail=1
    else
        log "ok - an install-test run that has not finished is not green"
    fi

    local iso_run
    iso_run=$(select_iso_run_from_log "$(printf 'Using ISO artifact from run 42105485811\nself-hosted runner noise\n')")
    if [[ "$iso_run" != "42105485811" ]]; then
        log "FAIL: the artifact resolver read '$iso_run' out of the install log"
        fail=1
    else
        log "ok - the release names the ISO the green run installed"
    fi
    if [[ -n "$(select_iso_run_from_log 'no resolver line here at all')" ]]; then
        log "FAIL: a log without the resolver line still produced a build run"
        fail=1
    else
        log "ok - a log that does not name its ISO stops the release"
    fi

    # Both directions of the asset pairing, because a half-signed bundle is the
    # failure mode a checksum file invites: the ISO is there, and the hash that
    # would catch a replaced ISO is not.
    mkdir -p "$tmp/good" "$tmp/nosig"
    : > "$tmp/good/samurai-linux-2026.11.05-amd64.iso"
    : > "$tmp/good/samurai-linux-2026.11.05-amd64.iso.sha256"
    : > "$tmp/good/samurai-linux-2026.11.05-amd64.iso.sig"
    : > "$tmp/good/samurai-linux-2026.11.05-amd64.iso.sha256.sig"
    : > "$tmp/good/samurai-linux-2026.11.05-amd64.packages.tsv"
    : > "$tmp/good/samurai-linux-2026.11.05-amd64.packages.tsv.sig"
    if [[ "$(check_asset_pairing "$tmp/good" 2>/dev/null)" != *".iso" ]]; then
        log "FAIL: a complete asset set was not accepted"
        fail=1
    else
        log "ok - a complete signed asset set is accepted"
    fi
    cp -a "$tmp/good/." "$tmp/nosig/"
    rm -f "$tmp/nosig/samurai-linux-2026.11.05-amd64.iso.sha256.sig"
    if (check_asset_pairing "$tmp/nosig") >/dev/null 2>&1; then
        log "FAIL: an unsigned checksum file was published anyway"
        fail=1
    else
        log "ok - an unsigned checksum stops the release"
    fi

    # The release host's per-asset ceiling, exercised in both directions rather
    # than assumed: the artifact this gate was written around is 2.74 GiB and
    # GitHub stops at 2 GiB, so the size check is what turns a late publish
    # failure into an early one. A lowered limit stands in for a big ISO.
    mkdir -p "$tmp/big"
    cp -a "$tmp/good/." "$tmp/big/"
    awk 'BEGIN { for (i = 0; i < 4096; i++) printf "x" }' \
        > "$tmp/big/samurai-linux-2026.11.05-amd64.iso"
    if (SAMURAI_MAX_ASSET_BYTES=1024 check_asset_pairing "$tmp/big") >/dev/null 2>&1; then
        log "FAIL: an ISO larger than the release host accepts was still published"
        fail=1
    else
        log "ok - an ISO larger than the release host accepts stops the release"
    fi
    if [[ "$(SAMURAI_MAX_ASSET_BYTES=999999 check_asset_pairing "$tmp/big" 2>/dev/null)" \
        == *".iso" ]]; then
        log "ok - the same ISO is publishable when the ceiling allows it"
    else
        log "FAIL: an ISO within the ceiling was rejected"
        fail=1
    fi

    if (check_asset_pairing "$tmp") >/dev/null 2>&1; then
        log "FAIL: an empty dist directory looked publishable"
        fail=1
    else
        log "ok - nothing to publish is not a release"
    fi

    # The notes are the release's claims, so the gate checks it names the
    # evidence a reader can follow rather than describing the product.
    printf 'deadbeef  %s\n' "$(basename "$tmp/good/samurai-linux-2026.11.05-amd64.iso")" \
        > "$tmp/good/samurai-linux-2026.11.05-amd64.iso.sha256"
    GITHUB_REPOSITORY=owner/repo write_release_notes "$tmp/notes.md" \
        "$tmp/good/samurai-linux-2026.11.05-amd64.iso" 42105485811 42112234958 deadbeefsha v2026.11
    if grep -q 'runs/42112234958' "$tmp/notes.md" && grep -q 'runs/42105485811' "$tmp/notes.md" \
        && grep -q 'SHA-256: `deadbeef`' "$tmp/notes.md"; then
        log "ok - the release notes name the install run, the build run and the checksum"
    else
        log "FAIL: the release notes do not name their own evidence:"
        sed -n '1,30p' "$tmp/notes.md" >&2
        fail=1
    fi

    ((fail == 0)) || die "the release gate self-test failed"
    log "release gate self-test passed"
}

main() {
    [[ $# -ge 1 ]] || die "usage: release-gate.sh --check SHA DIST [TAG] | --self-test"
    case $1 in
        --self-test) self_test ;;
        --check)
            [[ $# -ge 3 && $# -le 4 ]] || die "usage: release-gate.sh --check SHA DIST [TAG]"
            check_release "$2" "$3" "${4:-}"
            ;;
        *) die "unknown mode $1 (use --check SHA DIST [TAG] or --self-test)" ;;
    esac
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
