# Samurai Performance Engineering

This document describes how Samurai Linux measures performance and what it is
allowed to claim. It contains no boot time, no idle-memory figure and no
"typical" CPU load, because none has been recorded from an installed system
that anyone has published. Earlier revisions of this file carried invented
numbers; they have been removed and must not come back without a measurement
behind them.

## How a number gets published

`build/measure-performance.sh` runs on a booted Samurai system and prints one
line per metric, each paired with the command that produced it:

```
bash build/measure-performance.sh                       # writes to a temp dir
bash build/measure-performance.sh --out-dir /tmp/perf --cpu-mib 64 --disk-mib 64
```

It produces `performance.txt` (human-readable) and `performance-metrics.tsv`
(`label<TAB>value<TAB>unit<TAB>command`). The installer test copies the script
into the installed guest, runs it inside the live Plasma session, and uploads
the report as part of the `install-test-diagnostics` artifact. If a core metric
comes back `unavailable` the install test fails, so a release cannot be green
without actual measurements attached to it.

The core set is: `memory_used`, `cpu_idle`, `units_enabled`,
`services_running`, `sha256_mib_per_s`, `rootfs_used`. Boot time, compiler
throughput, disk write speed and the GL renderer are recorded as well but are
not gated, because they depend on hardware the test VM does not have.

A number may be quoted anywhere else only with all four of: the value, the
command, the machine that ran it (CPU model, cores, RAM, real or virtual), and
the run it came from. A metric that cannot be measured is written
`unavailable`, never estimated.

## What the image does for performance today

- **Graphics providers are pinned, not left to recommends.** `libgl1-mesa-dri`,
  `libegl-mesa0`, `mesa-utils` and `mesa-vulkan-drivers` are listed explicitly
  in `build/config/package-lists/samurai.list.chroot`. `kde-standard` pulls Qt
  and Plasma but no DRI driver, and without one KWin cannot create a GL context
  at all (`egl: failed to create dri2 screen`) - that omission cost a whole
  desktop verification run.
- **A build toolchain that is fast where it matters.** `build-essential`,
  `cmake` and `ninja-build` ship in the base image; the compiler is GCC, the
  Debian default.
- **Logging keeps the journal across reboots** (`Storage=persistent` in
  `etc/systemd/journald.conf.d/99samurai.conf`) so firewall drops and service
  failures can be read after a restart. On the live medium the root filesystem
  is memory-backed, so the journal exists but does not survive a reboot; that
  is intended.
- **Gaming helpers ship, but the store does not.** `gamemode` and `mangohud`
  are in the image; Steam is installed after first boot by `samurai-gaming`.
- **The background service set is Debian's plus KDE's `kde-standard` task**, and
  its size is now a measured metric (`units_enabled`, `services_running`) rather
  than an adjective.

## What is not implemented

Claiming these would repeat the mistake this file was written to fix:

- **No power-profile switching.** Neither `power-profiles-daemon` nor TLP is in
  the package lists, so there is no balanced / performance / power-saving mode
  and no hardware-aware profile. What exists is whatever `cpufreq` defaults
  Debian picks.
- **No compositor tuning.** The image ships no `kwinrc`; KWin runs with Plasma's
  own defaults. Effects are neither enabled nor disabled by Samurai.
- **No AI resource limits.** Memory ceilings, load-triggered pauses and
  inference monitoring all depend on an AI runtime that is not part of the
  image yet (see `ai-system.md`).
- **No dedicated resource monitor is pinned.** Whether a system-monitor applet
  is present depends on what `kde-standard` pulls, and nothing verifies it.
- **No gaming benchmarks.** MangoHUD is checked as installed and preloadable on
  a real session; no frame-rate workload has ever been measured, and QEMU's
  software renderer could not produce a meaningful one.

## Measurements

Empty by design. The first values arrive with the install-test artifact that
runs this harness; a release may copy them into this section, with the run
that produced them named alongside.
