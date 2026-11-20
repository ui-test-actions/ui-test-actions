"""Compare app assertions with independent native ICMP and relay evidence."""

import argparse
import json
from pathlib import Path
import re
from statistics import median


CLOCK = re.compile(r"^\d{10}$")
ROUND_TRIP = re.compile(r"\btime[=<]([\d.]+)\s*ms\b")
SUMMARY = re.compile(r"\b1 packets transmitted, (\d+) (?:packets )?received\b")


def parse_delivery(text):
    sample = None
    for line in text.splitlines():
        if CLOCK.fullmatch(line):
            sample = {"epoch": int(line), "rtt_ms": None}
        elif sample is not None:
            if match := ROUND_TRIP.search(line):
                sample["rtt_ms"] = float(match[1])
            if match := SUMMARY.search(line):
                received = int(match[1])
                if received not in (0, 1) or bool(received) != (sample["rtt_ms"] is not None):
                    raise ValueError("A native ping reported inconsistent delivery and timing.")
                yield {**sample, "received": bool(received)}
                sample = None


def summarize(journey, delivery, counters, runner_offset=0):
    profiles = journey["profiles"]
    samples = list(parse_delivery(delivery))
    delay = next(i for i, item in enumerate(profiles) if item["profile"]["delay_ms"])
    loss = next(i for i, item in enumerate(profiles) if item["profile"]["loss_percent"])
    offline = next(i for i, item in enumerate(profiles) if item["profile"]["offline"])
    restored = next(item for item in profiles[offline + 1:] if item["remaining_ms"] == 0)

    def epoch(item):
        if "controller_epoch_ms" in item:
            return item["controller_epoch_ms"] / 1000
        return item["epoch"] + runner_offset

    def interval(index):
        start = profiles[index]
        stop = min(epoch(start) + start["remaining_ms"] / 1000, epoch(profiles[index + 1]))
        # Exclude requests whose native deadline overlaps a change in profile.
        return [sample for sample in samples if epoch(start) + 1 <= sample["epoch"] <= stop - 4]

    delayed = interval(delay)
    lossy = interval(loss)
    interrupted = interval(offline)
    resumed = [sample for sample in samples if epoch(restored) + 1 <= sample["epoch"] <= epoch(restored) + 40
               and sample["received"]]
    observed = [sample["rtt_ms"] for sample in delayed if sample["received"]]
    if not observed or median(observed) < profiles[delay]["profile"]["delay_ms"] * 1.5:
        raise ValueError("Native probes did not observe the configured link delay.")
    if not interrupted or any(sample["received"] for sample in interrupted) or not resumed:
        raise ValueError("Native probes did not observe the outage and restored delivery.")
    if not sum(counters[direction].get("fault_drop", 0) for direction in ("sent", "received")):
        raise ValueError("The relay did not record any deliberate frame drops.")
    if not journey.get("outage_observation") or not journey.get("recovered_receiver_lines"):
        raise ValueError("Observable app outage and recovery assertions are missing.")
    return {"legacy_runner_time_offset_seconds": runner_offset, "slow_rtt_ms": observed,
            "loss_probe_results": [item["received"] for item in lossy],
            "offline_probe_results": [item["received"] for item in interrupted],
            "restored_rtt_ms": [item["rtt_ms"] for item in resumed], "counters": counters}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("journey", type=Path)
    parser.add_argument("delivery", type=Path)
    parser.add_argument("counters", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--legacy-runner-offset-seconds", type=float, default=0,
                        help="Clock offset for evidence recorded before link-controller timestamps were available")
    args = parser.parse_args()
    result = summarize(json.loads(args.journey.read_text(encoding="utf-8")), args.delivery.read_text(encoding="utf-8"),
                       json.loads(args.counters.read_text(encoding="utf-8")), args.legacy_runner_offset_seconds)
    args.output.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
