#!/usr/bin/env python3
"""Render the committed KDE color schemes from presets.json.

presets.json is the one place a theme's colours are defined; this script writes
``samurai/themes/<slug>/samurai-<slug>.colors`` from it, and the chroot hook
installs every ``*.colors`` it finds there into /usr/share/color-schemes. Run it
after editing a preset, and run it with ``--check`` to prove the committed
schemes still match the presets (tests/smoke.sh does exactly that).

    python3 samurai/desktop/hub/render-schemes.py
    python3 samurai/desktop/hub/render-schemes.py --check
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import samurai_hub_core as core


def main(argv: list[str]) -> int:
    check = "--check" in argv
    paths = core.core_paths()
    problems = 0
    written = 0

    for preset in core.load_presets(paths):
        text = core.render_scheme(preset.scheme_id, f"Samurai {preset.name}", preset.palette)
        issues = core.scheme_problems(text, preset.scheme_id)
        if issues:
            print(f"{preset.slug}: rendered scheme is invalid: {'; '.join(issues)}")
            problems += 1
            continue
        target = paths.themes / preset.slug / f"{preset.scheme_id}.colors"
        if check:
            if not target.is_file():
                print(f"{preset.slug}: {target} is missing")
                problems += 1
                continue
            if target.read_text(encoding="utf-8") != text:
                print(f"{preset.slug}: {target} does not match presets.json")
                problems += 1
                continue
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8", newline="\n")
        written += 1

    if check:
        if problems:
            return 1
        print(f"all {len(core.load_presets(paths))} schemes match presets.json")
        return 0

    print(f"wrote {written} schemes under {paths.themes}")
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
