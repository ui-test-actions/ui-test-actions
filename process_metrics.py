"""Read actual resource counters for a runner-owned or allowlisted app process."""

import json
import os
from pathlib import Path
import re
import subprocess
import sys


def linux_process(pid):
    path = Path("/proc") / str(pid) / "stat"
    try:
        fields = path.read_text(encoding="utf-8").rsplit(")", 1)[1].split()
    except FileNotFoundError:
        return None
    ticks = int(fields[11]) + int(fields[12])
    return {
        "pid": pid, "state": fields[0],
        "cpu_ms": round(ticks * 1000 / os.sysconf("SC_CLK_TCK"), 3),
        "rss_bytes": int(fields[21]) * os.sysconf("SC_PAGE_SIZE"),
        "source": "linux:/proc/pid/stat",
    }


def ps_cpu_ms(text):
    days, separator, clock = text.partition("-")
    elapsed = int(days) * 86400 if separator else 0
    fields = (clock if separator else text).split(":")
    elapsed += sum(float(field) * 60 ** index for index, field in enumerate(reversed(fields)))
    return round(elapsed * 1000, 3)


def mac_process(pid):
    probe = subprocess.run(["/bin/ps", "-p", str(pid), "-o", "stat=", "-o", "time=", "-o", "rss="],
                           capture_output=True, text=True, timeout=4, check=False,
                           env={**os.environ, "LC_ALL": "C"})
    if probe.returncode == 1 and not probe.stdout.strip():
        return None
    probe.check_returncode()
    state, cpu, size = probe.stdout.split()
    return {"pid": pid, "state": state, "cpu_ms": ps_cpu_ms(cpu), "rss_bytes": int(size) * 1024,
            "source": "macos:ps"}


def windows_process(pid):
    script = (
        f"$p=Get-Process -Id {int(pid)} -ErrorAction SilentlyContinue; "
        "if($null -ne $p){ "
        "$responding=$null; if($p.MainWindowHandle -ne 0){$responding=$p.Responding}; "
        "[ordered]@{pid=$p.Id;cpu_ms=$p.TotalProcessorTime.TotalMilliseconds;"
        "working_set_bytes=$p.WorkingSet64;window_responding=$responding;source='windows:Get-Process'} "
        "| ConvertTo-Json -Compress }"
    )
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", script],
                            capture_output=True, text=True, timeout=8, check=True)
    return json.loads(result.stdout) if result.stdout.strip() else None


def host_process(pid):
    if sys.platform == "win32":
        return windows_process(pid)
    if sys.platform == "darwin":
        return mac_process(pid)
    return linux_process(pid)


def android_metrics(shell, identifier):
    processes = shell("ps", "-A", "-o", "PID,NAME", timeout=5).decode("utf-8", errors="replace")
    pid = None
    for line in processes.splitlines()[1:]:
        fields = line.split()
        if len(fields) == 2 and fields[1] == identifier and fields[0].isdigit():
            pid = int(fields[0])
            break
    result = {"id": identifier, "running": pid is not None, "source": "android:dumpsys"}
    if pid is None:
        try:
            exits = shell("dumpsys", "activity", "exit-info", identifier, timeout=7).decode("utf-8", errors="replace")
        except (OSError, RuntimeError, subprocess.SubprocessError):
            return result
        reason = re.search(r"\breason=(\d+)\s*\(([A-Z0-9_ -]+(?:\([A-Z0-9_ -]+\))?)\)", exits)
        if reason:
            result["last_os_exit"] = {"reason_code": int(reason[1]), "reason": reason[2]}
        return result
    result["pid"] = pid
    sources = (("meminfo", str(pid)), ("cpuinfo",))
    for command in sources:
        try:
            output = shell("dumpsys", "-t", "4", *command, timeout=6).decode("utf-8", errors="replace")
        except (OSError, RuntimeError, subprocess.SubprocessError):
            continue
        if command[0] == "meminfo":
            for name in ("PSS", "RSS"):
                total = re.search(rf"\bTOTAL {name}:\s*([0-9]+)", output)
                if total:
                    result[f"{name.lower()}_bytes"] = int(total[1]) * 1024
        else:
            cpu = re.search(rf"^\s*\+?([0-9.]+)%\s+{pid}/{re.escape(identifier)}:", output, re.MULTILINE)
            if cpu:
                result["cpu_recent_percent"] = float(cpu[1])
    try:
        clock = shell("ps", "-p", str(pid), "-o", "PID,TIME", timeout=5).decode("ascii", errors="replace")
    except (OSError, RuntimeError, subprocess.SubprocessError):
        return result
    match = re.search(rf"^\s*{pid}\s+([0-9:.\-]+)\s*$", clock, re.MULTILINE)
    if match:
        result.update(cpu_ms=ps_cpu_ms(match[1]), cpu_source="android:ps TIME")
    return result


def simulator_metrics(simctl, identifier):
    listings = simctl("spawn", "launchctl", "list", timeout=7).decode("utf-8", errors="replace")
    process = re.search(rf"^(\d+)\s+-?\d+\s+UIKitApplication:{re.escape(identifier)}\[",
                        listings, re.MULTILINE)
    result = {"id": identifier, "running": process is not None, "source": "simulator:launchctl"}
    if process:
        sample = mac_process(int(process[1]))
        if sample is None:
            result["running"] = False
        else:
            result.update(sample, source="simulator:launchctl+macos:ps")
    return result
