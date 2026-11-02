# Samurai Performance Engineering

> **Legacy design document.** Nothing below was implemented or measured. The
> "Reproducible Baselines" numbers at the end of this file were written without
> any system being booted, benchmarked or observed, and must not be quoted; the
> same goes for the power profiles, KWin tuning and AI resource limits described
> here. See [`../docs/performance.md`](../docs/performance.md) for how a real
> number is produced by `build/measure-performance.sh`.

## System Optimization

### Startup and Services
- **Minimal unnecessary startup applications** - only essential services enabled
- **Sensible background-service defaults** - dbus, NetworkManager, cron
- **Hardware-aware power profiles** - balanced by default

### Power Management
- **Balanced mode** - default for most users
- **Performance mode** - maximum responsiveness when on AC power
- **Power-saving mode** - extended battery life on laptops

### Graphics and Compositor
- **KWin effects** - enabled with performance optimization
- **Threading** - optimized for available CPU cores
- **Hardware acceleration** - checked and enabled for compatible GPUs

### Resource Monitoring
- **CPU, RAM, GPU, disk, AI workloads** - real-time monitoring
- **System monitor applet** - KDE integrated
- **Resource limits** - optional AI inference limits to prevent desktop unresponsiveness

### Diagnostics
- **Boot time analysis** - reproducible baseline measurement
- **Idle memory measurement** - typical RAM usage at desktop
- **Application launch time** - tracked for common applications
- **Build performance** - tracked for developer workflows
- **Gaming workload benchmarks** - supported configurations documented

### AI Resource Limits
- Maximum AI inference memory % of system RAM
- Automatic pause when system load exceeds threshold
- Warning when approaching resource limits

### Reproducible Baselines
```
Boot time:      8-12 seconds (SSD), 30-45 seconds (HDD)
Idle memory:    400-600 MB (KDE Plasma)
CPU utilization: 2-5% at desktop
Build time:     varies by hardware
Game launch:    varies by title
```
