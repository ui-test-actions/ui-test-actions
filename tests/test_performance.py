import os
import sys
import unittest
from unittest.mock import Mock, patch

from measure import compare, cpu_share
from process_metrics import android_metrics, linux_process, ps_cpu_ms, simulator_metrics


class NativeMetricsTest(unittest.TestCase):
    @unittest.skipUnless(sys.platform.startswith("linux"), "Linux procfs only")
    def test_reads_real_linux_process_resources(self):
        value = linux_process(os.getpid())
        self.assertEqual(value["pid"], os.getpid())
        self.assertGreater(value["rss_bytes"], 0)
        self.assertGreaterEqual(value["cpu_ms"], 0)

    def test_macos_cpu_clock_parsing_and_simulator_matching(self):
        self.assertEqual(ps_cpu_ms("0:14.52"), 14520)
        self.assertEqual(ps_cpu_ms("1-02:03:04"), 93784000)
        commands = Mock(return_value=b"PID\tStatus\tLabel\n123\t0\tUIKitApplication:com.example.actual[1][2]\n")
        with patch("process_metrics.mac_process", return_value={"pid": 123, "rss_bytes": 1048576}) as process:
            value = simulator_metrics(commands, "com.example.actual")
            process.assert_called_once_with(123)
        self.assertTrue(value["running"])
        commands.assert_called_once_with("spawn", "launchctl", "list", timeout=7)

    def test_android_preserves_os_pss_rss_and_recent_cpu(self):
        shell = Mock(side_effect=[
            b"PID NAME\n591 dev.example.app\n717 dev.example.app:worker\n",
            b"TOTAL PSS: 1855 TOTAL RSS: 11445 TOTAL SWAP PSS: 0\n",
            b"  2.7% 591/dev.example.app: 2.2% user + 0.5% kernel\n",
        ])
        result = android_metrics(shell, "dev.example.app")
        self.assertEqual(result["pss_bytes"], 1855 * 1024)
        self.assertEqual(result["rss_bytes"], 11445 * 1024)
        self.assertEqual(result["cpu_recent_percent"], 2.7)

    def test_android_exit_reason_is_labeled_by_the_os(self):
        shell = Mock(side_effect=[b"PID NAME\n43 other\n", b"reason=6 (ANR) subreason=0\n"])
        result = android_metrics(shell, "dev.example.app")
        self.assertFalse(result["running"])
        self.assertEqual(result["last_os_exit"], {"reason_code": 6, "reason": "ANR"})


class PerformanceReportTest(unittest.TestCase):
    def test_cpu_delta_uses_runner_time_and_same_process(self):
        previous = {"pid": 12, "cpu_ms": 140, "sample_monotonic_ms": 500}
        current = {"pid": 12, "cpu_ms": 440, "sample_monotonic_ms": 1500}
        self.assertEqual(cpu_share(previous, current), 30)
        self.assertIsNone(cpu_share(previous, {**current, "pid": 13}))
        self.assertIsNone(cpu_share(previous, {**current, "cpu_ms": 100}))

    def test_regression_limits_apply_only_to_measured_compatible_values(self):
        baseline = {"version": 1, "target": "linux", "app_id": "fixture",
                    "metrics": {"startup": {"median": 120}, "zero_cpu": {"median": 0}}}
        candidate = {**baseline, "metrics": {"startup": {"median": 150}, "zero_cpu": {"median": 5}}}
        report = compare(baseline, candidate, {"startup": 25})
        self.assertTrue(report["regressed"])
        self.assertEqual(report["measurements"]["startup"]["percent_change"], 25)
        self.assertNotIn("percent_change", report["measurements"]["zero_cpu"])
        with self.assertRaisesRegex(ValueError, "missing"):
            compare(baseline, candidate, {"battery": 1})
