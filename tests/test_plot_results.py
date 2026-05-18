#!/usr/bin/env python3
"""
Validation suite for scripts/plot_results.py (round-9 D1).

Self-contained: builds raw fixtures, runs report_results.py to
produce the summaries, then runs plot_results.py against those
summaries and checks the expected PNG files appear.

Cases:
    1. Single profile, multi-RTOS, multi-run -> aggregate + per-run
       + t4 PI charts produced.
    2. --profile filter restricts the output.

Run:
    python -m unittest tests.test_plot_results -v
or:
    python tests/test_plot_results.py
"""

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT      = Path(__file__).resolve().parents[1]
REPORT_SCRIPT  = REPO_ROOT / "scripts" / "report_results.py"
PLOT_SCRIPT    = REPO_ROOT / "scripts" / "plot_results.py"

# Re-use the fixture writer from the report-results test suite.
sys.path.insert(0, str(REPO_ROOT / "tests"))
from test_report_results import write_run   # noqa: E402

try:
    import matplotlib   # noqa: F401
    _MPL_AVAILABLE = True
except ImportError:
    _MPL_AVAILABLE = False


@unittest.skipUnless(_MPL_AVAILABLE,
                     "matplotlib not available — install with "
                     "`pip install matplotlib`")
class PlotResultsTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp  = Path(self._tmp.name)
        self.raw_dir     = self.tmp / "raw"
        self.summary_dir = self.tmp / "summary"
        self.plots_dir   = self.tmp / "plots"
        self.raw_dir.mkdir()

    def tearDown(self):
        self._tmp.cleanup()

    def _env(self):
        e = os.environ.copy()
        e["PYTHONIOENCODING"] = "utf-8"
        return e

    def _build_summaries(self, profile: str = "fair_perf") -> None:
        """Synthesise raw fixtures for 3 RTOSes × 2 runs and run
        report_results.py to produce the summary CSVs."""
        for rtos, off in (("chibios", 0), ("freertos", 50),
                          ("zephyr", 80)):
            for run, run_off in (("01", 0), ("02", 1)):
                write_run(self.raw_dir, rtos, profile, run,
                          cycle_offset=off + run_off)
        proc = subprocess.run(
            [sys.executable, str(REPORT_SCRIPT),
             "--profile",    profile,
             "--input-dir",  str(self.raw_dir),
             "--output-dir", str(self.summary_dir)],
            capture_output=True, text=True, encoding="utf-8",
            env=self._env(),
        )
        self.assertEqual(proc.returncode, 0,
                         f"report_results.py failed:\n"
                         f"stdout: {proc.stdout}\nstderr: {proc.stderr}")

    def _run_plot(self, *, profile: str | None = None
                  ) -> subprocess.CompletedProcess:
        cmd = [sys.executable, str(PLOT_SCRIPT),
               "--summary-dir", str(self.summary_dir),
               "--output-dir",  str(self.plots_dir)]
        if profile:
            cmd += ["--profile", profile]
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=self._env())

    # --- Case 1 ------------------------------------------------------

    def test_01_full_pipeline_produces_charts(self):
        self._build_summaries("fair_perf")
        proc = self._run_plot()
        self.assertEqual(proc.returncode, 0,
                         f"stdout: {proc.stdout}\n"
                         f"stderr: {proc.stderr}")
        # 4 tests x (aggregate + per_run) + 1 PI chart = 9 PNGs
        for test in ("t1_irq", "t2_handoff", "t3_mtx_uncont",
                     "t4_mtx_pi"):
            self.assertTrue(
                (self.plots_dir / f"fair_perf_{test}_aggregate.png").is_file(),
                f"missing aggregate chart for {test}")
            self.assertTrue(
                (self.plots_dir / f"fair_perf_{test}_per_run.png").is_file(),
                f"missing per_run chart for {test}")
        self.assertTrue(
            (self.plots_dir / "fair_perf_t4_pi.png").is_file())

    # --- Case 2 ------------------------------------------------------

    def test_02_profile_filter(self):
        # Build summaries for both profiles then ask plot for only
        # one of them; charts for the other profile must NOT appear.
        self._build_summaries("fair_perf")
        self._build_summaries("realistic_tickless")
        proc = self._run_plot(profile="fair_perf")
        self.assertEqual(proc.returncode, 0)
        self.assertTrue(
            (self.plots_dir / "fair_perf_t1_irq_aggregate.png").is_file())
        self.assertFalse(
            (self.plots_dir
                / "realistic_tickless_t1_irq_aggregate.png").is_file())

    # --- Case 3: error path -----------------------------------------

    def test_03_missing_summary_dir_fails(self):
        proc = self._run_plot()  # no summaries built yet
        self.assertNotEqual(proc.returncode, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
