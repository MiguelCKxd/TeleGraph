# Isolated contact-card checks

Run from the source directory in a graphical desktop with the application's
dependencies installed:

```text
python tools/verify_contact_card.py --output contact-card-result.json
```

This uses temporary demo data and a synthetic profile. It checks dark/light
themes, density, avatar size, responsive geometry, colors/borders, section/action
order and hiding, protected recovery, the appearance editor, saved layouts,
restoration and clean shutdown. It never connects an account. A successful run
contains `success: true` and `closed_cleanly: true`.

On Windows, use the optional process-only budget runner:

```text
python tools/run_limited_windows.py --memory-mib 384 --cpu-percent 20 --timeout 120 --output limited-384.json
python tools/run_limited_windows.py --memory-mib 256 --cpu-percent 10 --timeout 120 --output limited-256.json
```

It creates a Windows Job Object with memory and hard CPU limits, starts the demo
suspended, attaches it to the job, then resumes it. It does not change Windows,
VM hardware settings, other processes or saved account data. No features are
disabled. If the OS rejects the job configuration, the demo does not run without
limits. Closing the runner's job terminates its processes. A watchdog ends a
stalled run after the requested timeout.

The output consists of the runner JSON, a `.child.json` functional report and a
`.child.log`. `success` requires both clean process completion and a passing
functional report. `attached_before_start` must be true. Use `job_cpu_seconds` and
`peak_job_commit_bytes` for the entire process group. `launcher_*` counters measure
only the initial process: a virtual environment may launch Python in a child, so
those counters alone can substantially understate application use. The report
also includes the number of job processes, the peak commitment of a single job
process, and whether job accounting was available. Inspect limits, job peaks,
CPU time, wall time and errors together;
out-of-memory and watchdog failures are findings, not passing benchmarks.

Use `--script verify_customization_images.py` or `--script verify_layout.py` for
the other packaged demo checks. Arbitrary scripts and account sessions are not
accepted by the runner. Run one graphical check at a time.

Memory is committed private virtual memory, not simulated system RAM or an RSS
limit. CPU is a hard share of the job's processor budget, not an emulation of a
particular processor. See Microsoft's [memory limit documentation](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_extended_limit_information)
and [CPU rate documentation](https://learn.microsoft.com/en-us/windows/win32/api/winnt/ns-winnt-jobobject_cpu_rate_control_information).
Passing these checks does not establish universal minimum hardware, network
speed, or performance relative to another Telegram client.
