#!/usr/bin/env bash
# Measure the performance numbers this project is allowed to publish.
#
# Every value in the report travels with the exact command that produced it and
# with the machine that ran it, because a number whose conditions are unknown is
# not a baseline, it is marketing. Run this on a booted Samurai system:
#
#   bash build/measure-performance.sh
#   bash build/measure-performance.sh --out-dir /tmp/perf --cpu-mib 64
#
# Outputs, in the report directory:
#   performance.txt          human-readable report (also printed to stdout)
#   performance-metrics.tsv  label<TAB>value<TAB>unit<TAB>command, one metric per line
#
# The script makes no changes to the system: it reads counters and writes one
# temporary file inside --out-dir for the disk benchmark only.
set -euo pipefail

out_dir=""
cpu_mib=256
disk_mib=128
skip_disk=false
sample_seconds=5

die() { printf 'measure-performance: %s\n' "$*" >&2; exit 1; }

while [[ $# -gt 0 ]]; do
    case "$1" in
        --out-dir) [[ $# -ge 2 ]] || die "--out-dir needs a path"; out_dir=$2; shift 2 ;;
        --cpu-mib) [[ $# -ge 2 ]] || die "--cpu-mib needs a number"; cpu_mib=$2; shift 2 ;;
        --disk-mib) [[ $# -ge 2 ]] || die "--disk-mib needs a number"; disk_mib=$2; shift 2 ;;
        --sample-seconds) [[ $# -ge 2 ]] || die "--sample-seconds needs a number"; sample_seconds=$2; shift 2 ;;
        --skip-disk) skip_disk=true; shift ;;
        -h|--help) sed -n '2,18p' "$0"; exit 0 ;;
        *) die "unknown argument: $1" ;;
    esac
done

for number in "$cpu_mib" "$disk_mib" "$sample_seconds"; do
    [[ "$number" =~ ^[1-9][0-9]*$ ]] || die "sizes and sample times must be positive integers, got '$number'"
done

report_dir=${out_dir:-$(mktemp -d /tmp/samurai-performance.XXXXXX)}
mkdir -p "$report_dir" || die "cannot write to $report_dir"
report="$report_dir/performance.txt"
metrics="$report_dir/performance-metrics.tsv"
printf 'label\tvalue\tunit\tcommand\n' > "$metrics"

# A metric is a number plus the command that produced it. Anything that could
# not be measured is recorded as "unavailable" rather than guessed at, so a
# missing measurement can never be read as a passing one.
metric() {
    printf '%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" >> "$metrics"
    printf '%-24s %14s %s\n' "$1" "$2" "$3"
    printf '  by: %s\n\n' "$4"
}

text() {
    printf '%-24s %s\n' "$1" "$2"
    printf '  by: %s\n\n' "$3"
}

section() { printf '\n== %s ==\n\n' "$1"; }

run() {
    # Run a measurement command, swallowing its noise; an unavailable tool
    # yields an empty string, which the caller turns into "unavailable".
    local output
    output=$(bash -c "$1" 2>/dev/null) || output=""
    printf '%s' "$output"
}

main() {
    section "measurement conditions"

    local kernel cpu_model cpu_cores memory_total_kib root_fs virtualised
    kernel=$(run 'uname -r')
    cpu_model=$(awk -F': +' '/^model name/{print $2; exit}' /proc/cpuinfo || true)
    [[ -n "$cpu_model" ]] || cpu_model=$(run "lscpu -p=MODEL_NAME | grep -v '^#' | head -1")
    cpu_cores=$(run 'nproc')
    memory_total_kib=$(awk '/^MemTotal:/{print $2}' /proc/meminfo || true)
    root_fs=$(run 'df -Pk /' | awk 'NR==2{print $1}')
    virtualised=$(run 'systemd-detect-virt')

    text "host" "$(hostname) on $(date -Is)" 'hostname; date -Is'
    text "kernel" "${kernel:-unknown}" 'uname -r'
    text "cpu model" "${cpu_model:-unknown}" "awk '/^model name/' /proc/cpuinfo"
    text "cpu cores" "${cpu_cores:-unknown}" 'nproc'
    text "memory total" "${memory_total_kib:-unknown} KiB" 'MemTotal from /proc/meminfo'
    text "root filesystem" "${root_fs:-unknown}" 'df -Pk /'
    text "virtualisation" "${virtualised:-unknown}" 'systemd-detect-virt'
    text "measured as" "$(id -un)" 'id -un'

    section "startup"

    local analyze boot_kernel boot_userspace slow enabled running
    # Explicitly the system manager: this harness is run inside the desktop
    # session as an ordinary user, and systemd defaults to the *user* manager
    # there. Boot time and unit counts of the user session would be real numbers
    # about the wrong thing, which is the mistake this file exists to prevent.
    analyze=$(run 'systemd-analyze --system')
    boot_kernel=$(printf '%s' "$analyze" | grep -Eo '[0-9.]+(ms|s) *\(kernel\)' | tr -dc '0-9.' || true)
    boot_userspace=$(printf '%s' "$analyze" | grep -Eo '[0-9.]+(ms|s) *\(userspace\)' | tr -dc '0-9.' || true)
    if [[ -n "$analyze" ]]; then
        text "startup" "$(printf '%s' "$analyze" | tr '\n' ' ')" 'systemd-analyze --system'
    else
        text "startup" 'unavailable (systemd-analyze produced no output)' 'systemd-analyze --system'
    fi
    metric "boot_kernel" "${boot_kernel:-unavailable}" 's' 'systemd-analyze --system | grep "(kernel)"'
    metric "boot_userspace" "${boot_userspace:-unavailable}" 's' 'systemd-analyze --system | grep "(userspace)"'

    slow=$(run 'systemd-analyze --system blame | head -n 5')
    [[ -n "$slow" ]] && text "slowest units" "$(printf '%s' "$slow" | tr '\n' '; ')" 'systemd-analyze --system blame | head -5'

    # These counts are what "minimal services" has to mean: a number that can be
    # compared between releases, not an adjective.
    enabled=$(run 'systemctl --system list-unit-files --state=enabled --no-legend | grep -c .')
    running=$(run 'systemctl --system list-units --type=service --state=running --no-legend | grep -c .')
    metric "units_enabled" "${enabled:-unavailable}" 'units' 'systemctl --system list-unit-files --state=enabled | grep -c .'
    metric "services_running" "${running:-unavailable}" 'units' 'systemctl --system list-units --type=service --state=running | grep -c .'

    section "at rest"

    local used_kib ps_sample
    used_kib=$(awk '$1=="MemTotal:"{t=$2} $1=="MemAvailable:"{a=$2} END{if (t && a) print t-a}' /proc/meminfo || true)
    metric "memory_used" "${used_kib:-unavailable}" 'KiB' 'MemTotal minus MemAvailable from /proc/meminfo'

    ps_sample=$(run "ps -eo rss=,comm= --sort=-rss | head -n 5 | awk '{printf \"%s KiB %s; \", \$1, \$2}'")
    [[ -n "$ps_sample" ]] && text "largest processes" "$ps_sample" 'ps -eo rss=,comm= --sort=-rss | head -5'

    # Two /proc/stat reads with a delta between them: this reports what the
    # machine was really doing while idle instead of trusting one instant.
    local cpu_program="/^cpu /{print \$5+\$6, \$2+\$3+\$4+\$7+\$8+\$9+\$10}"
    sample_cpu() { awk "$cpu_program" /proc/stat 2>/dev/null || true; }
    local s1 s2 idle1 busy1 idle2 busy2 total cpu_idle loadavg
    s1=$(sample_cpu)
    sleep "$sample_seconds"
    s2=$(sample_cpu)
    read -r idle1 busy1 <<< "$s1" || true
    read -r idle2 busy2 <<< "$s2" || true
    if [[ "$idle1 $busy1 $idle2 $busy2" =~ ^[0-9]+\ [0-9]+\ [0-9]+\ [0-9]+$ ]] && (( idle2 > idle1 )); then
        total=$(( (idle2 + busy2) - (idle1 + busy1) ))
        cpu_idle=$(awk -v i="$((idle2 - idle1))" -v t="$total" 'BEGIN{printf "%.1f", i * 100 / t}')
    else
        cpu_idle=unavailable
    fi
    metric "cpu_idle" "$cpu_idle" '%' "two /proc/stat samples ${sample_seconds}s apart"

    loadavg=$(awk '{print $1}' /proc/loadavg || true)
    metric "load_1min" "${loadavg:-unavailable}" 'avg' 'cat /proc/loadavg'

    section "compute and storage"

    # One fixed workload so two releases can be compared on one host: hashing a
    # known quantity of bytes is bound by CPU and memory bandwidth, and shows a
    # regression without needing a GPU or a game.
    local cpu_bytes hash_cmd started ended digest elapsed_ms rate
    cpu_bytes=$(( cpu_mib * 1024 * 1024 ))
    hash_cmd="dd if=/dev/zero bs=1M count=$cpu_mib 2>/dev/null | sha256sum | cut -d' ' -f1"
    started=$(date +%s%N)
    digest=$(run "$hash_cmd")
    ended=$(date +%s%N)
    if [[ -n "$digest" ]] && (( ended > started )); then
        elapsed_ms=$(( (ended - started) / 1000000 ))
        rate=$(awk -v b="$cpu_bytes" -v ms="$elapsed_ms" 'BEGIN{printf "%.1f", b * 1000 / ms / 1048576}')
        metric "sha256_mib_per_s" "$rate" 'MiB/s' "$hash_cmd"
        text "workload" "${cpu_mib} MiB hashed in ${elapsed_ms} ms" "$hash_cmd"
    else
        metric "sha256_mib_per_s" 'unavailable' 'MiB/s' "$hash_cmd"
    fi

    if command -v gcc >/dev/null 2>&1; then
        local probe_dir
        probe_dir=$(mktemp -d)
        cat > "$probe_dir/probe.c" << 'EOF'
#include <stdio.h>
int main(void) {
    volatile long sum = 0;
    for (long i = 0; i < 40000000; i++) sum += i;
    printf("%ld\n", sum);
    return 0;
}
EOF
        started=$(date +%s%N)
        if gcc -O2 -o "$probe_dir/probe" "$probe_dir/probe.c" 2>/dev/null; then
            ended=$(date +%s%N)
            metric "gcc_compile_probe_ms" "$(( (ended - started) / 1000000 ))" 'ms' \
                'gcc -O2 probe.c (a 40M-iteration volatile loop)'
        else
            metric "gcc_compile_probe_ms" 'unavailable' 'ms' 'gcc -O2 -o probe probe.c'
        fi
        rm -rf "$probe_dir"
    else
        metric "gcc_compile_probe_ms" 'unavailable' 'ms' 'gcc -O2 (gcc is not installed)'
    fi

    if [[ "$skip_disk" == true ]]; then
        metric "disk_write" 'skipped' 'per second' '--skip-disk'
    else
        local probe write_cmd dd_out speed
        probe="$report_dir/disk-probe.tmp"
        write_cmd="dd if=/dev/zero of='$probe' bs=1M count=$disk_mib conv=fdatasync 2>&1 | tail -n 1"
        dd_out=$(run "$write_cmd")
        rm -f "$probe"
        speed=$(printf '%s' "$dd_out" | grep -Eo '[0-9.]+ [A-Za-z]+/s' | head -n 1)
        metric "disk_write" "${speed:-unavailable}" 'per second' "$write_cmd"
    fi

    section "graphics"

    local renderer compositor rootfs_used
    if command -v glxinfo >/dev/null 2>&1 && [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
        renderer=$(run 'glxinfo -B' | awk -F': +' '/OpenGL renderer string/{print $2; exit}')
        metric "gl_renderer" "${renderer:-unavailable}" '' 'glxinfo -B'
    else
        metric "gl_renderer" 'unavailable' '' 'glxinfo -B (needs glxinfo and a display)'
    fi

    compositor=$(run "pgrep -f 'kwin_x11|kwin_wayland' | head -1")
    metric "compositor_pid" "${compositor:-none}" '' "pgrep -f 'kwin_x11|kwin_wayland'"

    rootfs_used=$(run 'df -Pkm /' | awk 'NR==2{print $3}')
    metric "rootfs_used" "${rootfs_used:-unavailable}" 'MiB' 'df -Pkm /'

    section "done"
    printf 'report:  %s\nmetrics: %s\n\n' "$report" "$metrics"
    printf 'Every number above is paired with the command that produced it, on\n'
    printf 'the machine named under "measurement conditions". None of it is a\n'
    printf 'target, an estimate, or a typical value: it is what this run measured.\n'
}

# The report file must hold the same text the console saw, so the run is
# auditable from the CI artifact alone.
{
    printf '# Samurai Linux performance measurement\n\n'
    printf 'Produced by build/measure-performance.sh on the host named below.\n\n'
    printf '```\n'
    cat "$metrics"
    printf '```\n\n'
    printf '```\n'
    main
    printf '```\n'
} | tee "$report"
