#!/usr/bin/env bash
# Install a Samurai Linux ISO into a blank QEMU disk and verify the result.
#
# Usage: bash build/install-test.sh <iso> [--branded] [--no-desktop]
#                                     [--desktop-session NAME]
#                                     [--timeout SECONDS]
#
# Requires QEMU, vncdotool, tesseract-ocr, and Python 3 with Pillow. The driver
# writes its disk, screenshots, and logs to build/install-test/.
set -euo pipefail

REPO_ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." >/dev/null 2>&1 && pwd)
ISO="${1:-}"

if [[ -z "$ISO" || "$ISO" == "-h" || "$ISO" == "--help" ]]; then
    printf 'Usage: %s <iso> [--branded] [--no-desktop] [--timeout SECONDS]\n' "$0" >&2
    exit 1
fi
[[ -f "$ISO" ]] || { printf 'Error: ISO not found: %s\n' "$ISO" >&2; exit 1; }
shift

export SAMURAI_INSTALL_WORK_DIR="${SAMURAI_INSTALL_WORK_DIR:-$REPO_ROOT/build/install-test}"

exec python3 "$REPO_ROOT/build/install-test.py" "$ISO" \
    --work-dir "$SAMURAI_INSTALL_WORK_DIR" "$@"
