#!/usr/bin/env python3
"""Collect native UI measurements and compare compatible performance reports."""

import argparse
from collections import defaultdict
import json
from pathlib import Path
from statistics import median
import sys
import time

from agent import Client, ClientError
from explore import UI
from workflow import read_mapping


def cpu_share(previous, current):
    if (not previous or previous.get("pid") is None or previous.get("pid") != current.get("pid") or
            any(key not in previous or key not in current for key in ("cpu_ms", "sample_monotonic_ms"))):
        return None
    consumed = current["cpu_ms"] - previous["cpu_ms"]
    elapsed = current["sample_monotonic_ms"] - previous["sample_monotonic_ms"]
    return round(consumed * 100 / elapsed, 3) if consumed >= 0 and elapsed > 0 else None


def measurements(observations, samples):
    grouped = defaultdict(list)
    for name, value in observations.get("startup", {}).items():
        grouped[f"startup.{name}"].append(value)
    for action in observations.get("actions", []):
        if action["ok"] and action["command"] != "app.metrics":
            grouped[f"driver.{action['command']}.milliseconds"].append(action["milliseconds"])
    for sample in samples:
        for metric in ("cpu_recent_percent", "cpu_one_core_percent", "rss_bytes", "pss_bytes", "working_set_bytes"):
            if metric in sample:
                grouped[f"app.{sample.get('source', 'native')}.{metric}"].append(sample[metric])
    return {name: {"samples": len(values), "median": median(values), "maximum": max(values)}
            for name, values in sorted(grouped.items())}


def profile(client, app_id, count, interval_ms):
    ui = UI(client)
    target = client.identify()["target"]
    capabilities = json.loads(client.fetch("/v2/capabilities"))["commands"]
    if "performance.observations" not in capabilities:
        raise ValueError("The action pin does not provide performance observations.")
    if app_id and "app.metrics" not in capabilities:
        raise ValueError("This session has no configured app metrics.")
    started = time.monotonic()
    samples = []
    if app_id:
        for index in range(count):
            deadline = started + index * interval_ms / 1000
            time.sleep(max(0, deadline - time.monotonic()))
            before = time.monotonic()
            sample = ui.call("app.metrics", {"id": app_id})
            after = time.monotonic()
            sample["at_ms"] = round(((before + after) / 2 - started) * 1000, 3)
            sample["client_poll_ms"] = round((after - before) * 1000, 3)
            percent = cpu_share(samples[-1] if samples else None, sample)
            if percent is not None:
                sample["cpu_one_core_percent"] = percent
            samples.append(sample)
    observed = ui.call("performance.observations", {})
    return {"version": 1, "target": target, "app_id": app_id, "samples": samples, "observations": observed,
            "metrics": measurements(observed, samples)}


def compare(baseline, candidate, limits):
    if (baseline.get("version") != 1 or candidate.get("version") != 1 or
            (baseline["target"], baseline["app_id"]) != (candidate["target"], candidate["app_id"])):
        raise ValueError("Compare reports for the same target, app and report version.")
    old, new = baseline["metrics"], candidate["metrics"]
    if set(limits) - (old.keys() & new.keys()):
        raise ValueError("A regression limit names a measurement missing from one of the reports.")
    differences = {}
    for name in sorted(old.keys() & new.keys()):
        before, after = old[name]["median"], new[name]["median"]
        delta = after - before
        entry = {"baseline_median": before, "candidate_median": after, "delta": delta}
        if before:
            entry["percent_change"] = round(delta * 100 / before, 3)
        if name in limits:
            maximum = limits[name]
            if type(maximum) not in (int, float) or not 0 <= maximum < float("inf"):
                raise ValueError("Each regression limit must be a finite nonnegative delta.")
            entry.update(maximum_delta=maximum, regression=delta > maximum)
        differences[name] = entry
    return {"version": 1, "target": baseline["target"], "measurements": differences,
            "regressed": any(item.get("regression") for item in differences.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="mode", required=True)
    collect = commands.add_parser("collect")
    collect.add_argument("connection", type=Path)
    collect.add_argument("--token-file", type=Path, required=True)
    collect.add_argument("--access-file", type=Path)
    collect.add_argument("--app-id")
    collect.add_argument("--count", type=int, default=6, choices=range(1, 121), metavar="1..120")
    collect.add_argument("--interval-ms", type=int, default=1000)
    diff = commands.add_parser("compare")
    diff.add_argument("baseline", type=Path)
    diff.add_argument("candidate", type=Path)
    diff.add_argument("--limits", type=Path)
    for sub in (collect, diff):
        sub.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.mode == "collect":
            if not 1000 <= args.interval_ms <= 60000:
                raise ValueError("The sampling interval must be between one and 60 seconds.")
            client = Client(read_mapping(args.connection), args.token_file, args.access_file)
            result = profile(client, args.app_id, args.count, args.interval_ms)
        else:
            result = compare(read_mapping(args.baseline), read_mapping(args.candidate),
                             read_mapping(args.limits) if args.limits else {})
        with args.output.open("x", encoding="utf-8") as report:
            report.write(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
        return 1 if result.get("regressed") else 0
    except (ClientError, ValueError, OSError, KeyError) as error:
        print(json.dumps({"error": str(error)}, ensure_ascii=False), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
