#!/usr/bin/env bash
# Validate a release package manifest: package<TAB>version<TAB>architecture, one
# per line. build/verify-iso.sh gates a build on this and signs the result, so a
# manifest that is malformed or silently short would be published to users who
# triage vulnerabilities against it.
#
# This file exists as a script rather than as lines inside verify-iso.sh because
# the check itself once failed upwards: `if awk 'END { exit bad }'` reports
# failure by exiting 1, and an `if` runs its body on 0, so a perfectly good
# manifest was rejected (run 41528368817). Both directions are now exercised by
# tests/smoke.sh, which needs a callable thing to exercise.
set -euo pipefail

die() { printf 'Error: %s\n' "$*" >&2; exit 1; }

[[ $# -eq 1 ]] || die "usage: check-manifest.sh MANIFEST"
manifest=$1
[[ -s "$manifest" ]] || die "the manifest $manifest is empty: dpkg status produced nothing"

# build/verify-iso.sh writes these markers for installed records it cannot name
# completely; they must never survive into a published manifest.
broken=$(grep '^# ' "$manifest" || true)
if [[ -n "$broken" ]]; then
    printf '%s\n' "installed packages this build cannot name precisely:" >&2
    printf '%s\n' "$broken" | head -n 10 >&2
    die "dpkg status has installed packages with no version or architecture"
fi

bad=$(awk -F'\t' 'NF != 3 { print FNR ": " $0 }' "$manifest" | head -n 5)
if [[ -n "$bad" ]]; then
    printf '%s\n' "manifest rows that are not package<TAB>version<TAB>architecture:" >&2
    printf '%s\n' "$bad" | cat -A >&2
    die "the manifest has a line without package, version and architecture"
fi

printf 'Manifest %s is well formed (%s rows)\n' "$manifest" "$(wc -l < "$manifest" | tr -d '[:space:]')"
