#!/usr/bin/env python3
"""
Validation suite for scripts/report_results.py (round-9 C1).

Self-contained: every fixture is generated programmatically in a
temp directory.

Cases:
    1. Two runs of one RTOS (chibios) -> per-run + aggregate + compare
    2. Multi-RTOS aggregate: chibios + freertos, 2 runs each
       -> aggregate has 2 RTOS rows per test, compare has 2 columns

Run:
    python -m unittest tests.test_report_results -v
or:
    python tests/test_report_results.py
"""

import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT    = REPO_ROOT / "scripts" / "report_results.py"
SYS_CLOCK = 480_000_000


# === Synthetic fixture writer =========================================

DATASETS = {
    "t1_irq":        ("dwt_a4_minus_a1",
                      10000, lambda i, off: 200 + (i % 10) + off),
    "t2_handoff":    ("dwt_thread_to_thread",
                      10000, lambda i, off: 300 + (i % 5) + off),
    "t3_mtx_uncont": ("dwt_lock_unlock_pair",
                      10000, lambda i, off: 60 + (i % 4) + off),
    "t4_mtx_pi":     ("dwt_low_unlock_to_high_acquire",
                      100,   lambda i, off: 250 + i + off),
}
WARMUP_N = {"t1_irq": 1000, "t2_handoff": 1000, "t3_mtx_uncont": 1000}


def _us(c: int) -> str:
    return f"{c * 1_000_000.0 / SYS_CLOCK:.6f}"


# Synthetic kernel labels written into the fake banner. They are
# fixture data, NOT contracts on the real firmware: changing the
# real CH_KERNEL_VERSION (or any other RTOS macro) does not require
# updating these strings — the tests verify the propagation of the
# string they write, whatever it is.
KERNELS = {"chibios":  "ChibiOS RT 7.0.6",
           "freertos": "FreeRTOS V11.3.0",
           "zephyr":   "Zephyr 4.4.0"}


def write_run(in_dir: Path, rtos: str, profile: str, run_id: str,
              cycle_offset: int = 0) -> None:
    """Emit <prefix>.csv, <prefix>.t4_pi.csv and <prefix>.banner.txt
    coherent with the contract collect_results.py would have written.
    The banner carries the RTOS version line so report_results.py
    can surface it in the published summaries."""
    prefix = in_dir / f"{rtos}_{profile}_run{run_id}"
    csv_path  = prefix.with_suffix(".csv")
    t4pi_path = prefix.parent / (prefix.name + ".t4_pi.csv")
    bnr_path  = prefix.parent / (prefix.name + ".banner.txt")

    csv_lines = ["rtos,profile,test_name,metric,phase,iteration,"
                 "cycles,microseconds"]
    for test, (metric, n_valid, gen) in DATASETS.items():
        for i in range(1, WARMUP_N.get(test, 0) + 1):
            c = 100 + (i % 10) + cycle_offset
            csv_lines.append(f"{rtos},{profile},{test},{metric},"
                             f"warmup,{i},{c},{_us(c)}")
        for i in range(1, n_valid + 1):
            c = gen(i, cycle_offset)
            csv_lines.append(f"{rtos},{profile},{test},{metric},"
                             f"valid,{i},{c},{_us(c)}")
    csv_path.write_text("\n".join(csv_lines) + "\n", encoding="utf-8")

    t4_lines = ["rtos,profile,test_name,iteration,pi_ok"]
    for i in range(1, 101):
        t4_lines.append(f"{rtos},{profile},t4_mtx_pi,{i},1")
    t4pi_path.write_text("\n".join(t4_lines) + "\n", encoding="utf-8")

    bar = "=" * 42
    banner = [
        bar,
        "  RTOS Benchmark",
        f"  RTOS         : {rtos}",
        f"  RTOS kernel  : {KERNELS[rtos]}",
        f"  Profile      : {profile}",
        "  Board        : STM32H750B-DK",
        "  SystemClock  : 480000000 Hz",
        "  FLASH_ACR    : 0x00000034",
        "  Optimization : -O2  LTO=no",
        bar,
    ]
    bnr_path.write_text("\n".join(banner) + "\n", encoding="utf-8")


# === Test harness =====================================================

class ReportResultsTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp  = Path(self._tmp.name)
        self.in_dir  = self.tmp / "raw"
        self.out_dir = self.tmp / "summary"
        self.in_dir.mkdir()
        # Codex round 2026-05-14-bucket-c4-...-002
        # IMPORTANT 1 — the publication gate now requires
        # a VALIDATED run00 capture (CSV + matching
        # .validated.json with the standard manifest +
        # ELF/MAP SHA = run01..05 SHA) for every
        # publishable (rtos, profile) per ADR-013.
        # Pre-populate both files for all 3 RTOSes × 2
        # publishable profiles so existing tests focused
        # on the run01..05 PASS path do not need to add
        # warmup boilerplate per-test. Tests that
        # exercise the missing-run00 / mismatched-SHA
        # failure paths delete or overwrite the relevant
        # files in their body. The default warmup uses
        # `publication_mode="la"`, which matches the
        # default of `_write_validated_json`; tests that
        # change the run01..05 mode also need to
        # overwrite the warmup validated.json — the SHA
        # match is preserved by the helper's deterministic
        # (rtos, profile)-only SHA seed.
        for r in ("chibios", "freertos", "zephyr"):
            for p in ("fair_perf", "realistic_tickless"):
                self._write_warmup_run_csv(r, p)
                self._write_validated_json(r, p, "00")

    def _write_warmup_run_csv(self, rtos: str,
                              profile: str) -> None:
        """Minimal run00 CSV: the reporter discovers it via
        RUN_FILE_RE, excludes it from aggregation, and
        confirms its file-system presence in the
        publication gate per ADR-013."""
        out = (self.in_dir
               / f"{rtos}_{profile}_run00.csv")
        out.write_text(
            ("rtos,profile,test_name,metric,phase,"
             "iteration,cycles,microseconds\n"
             f"{rtos},{profile},t1_irq,"
             "dwt_a4_minus_a1,warmup,1,100,0.208333\n"),
            encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def _run(self, *, profile: str | None = None
             ) -> subprocess.CompletedProcess:
        cmd = [sys.executable, str(SCRIPT),
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir)]
        if profile:
            cmd += ["--profile", profile]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)

    # --- Case 1: single RTOS, 2 runs ---------------------------------

    def test_01_one_rtos_two_runs(self):
        write_run(self.in_dir, "chibios", "fair_perf", "01",
                  cycle_offset=0)
        write_run(self.in_dir, "chibios", "fair_perf", "02",
                  cycle_offset=2)
        proc = self._run(profile="fair_perf")
        self.assertEqual(proc.returncode, 0,
                         f"stdout:\n{proc.stdout}\n"
                         f"stderr:\n{proc.stderr}")
        # Per-run files
        self.assertTrue((self.out_dir /
            "chibios_fair_perf_run01_summary.md").is_file())
        self.assertTrue((self.out_dir /
            "chibios_fair_perf_run01_summary.csv").is_file())
        self.assertTrue((self.out_dir /
            "chibios_fair_perf_run02_summary.md").is_file())
        # Aggregate + compare files for the profile
        self.assertTrue((self.out_dir /
            "fair_perf_aggregate.csv").is_file())
        self.assertTrue((self.out_dir /
            "fair_perf_aggregate.md").is_file())
        self.assertTrue((self.out_dir /
            "fair_perf_compare.md").is_file())

    # --- Case 2: multi-RTOS aggregate --------------------------------

    def test_02_multi_rtos_compare(self):
        write_run(self.in_dir, "chibios",  "fair_perf", "01")
        write_run(self.in_dir, "chibios",  "fair_perf", "02",
                  cycle_offset=1)
        write_run(self.in_dir, "freertos", "fair_perf", "01",
                  cycle_offset=50)
        write_run(self.in_dir, "freertos", "fair_perf", "02",
                  cycle_offset=52)
        proc = self._run(profile="fair_perf")
        self.assertEqual(proc.returncode, 0, proc.stderr)

        # Aggregate CSV must list two RTOSes for each test.
        agg_csv = (self.out_dir / "fair_perf_aggregate.csv").read_text(
            encoding="utf-8").splitlines()
        # Header + 2 RTOS x 4 tests = 9 lines minimum
        self.assertEqual(len(agg_csv), 1 + 2 * 4)
        # Compare MD must contain both RTOS columns
        cmp_md = (self.out_dir / "fair_perf_compare.md").read_text(
            encoding="utf-8")
        self.assertIn("chibios", cmp_md)
        self.assertIn("freertos", cmp_md)
        # Kernels section in compare MD must surface the kernel
        # labels that the synthetic banner declared.
        self.assertIn("## Kernels", cmp_md)
        self.assertIn(KERNELS["chibios"],  cmp_md)
        self.assertIn(KERNELS["freertos"], cmp_md)
        # Same in aggregate MD ("RTOS kernels (this profile)" table).
        agg_md = (self.out_dir / "fair_perf_aggregate.md").read_text(
            encoding="utf-8")
        self.assertIn("RTOS kernels", agg_md)
        self.assertIn(KERNELS["chibios"],  agg_md)
        self.assertIn(KERNELS["freertos"], agg_md)

    # --- Case 3: aggregation is robust to a single bad run -----------

    def test_03_aggregate_uses_median_of_medians(self):
        # Three runs: two normal (offset 0, 2), one outlier (+1000).
        # The aggregate median across the 3 must NOT be biased by
        # the outlier (median of medians is robust to one outlier).
        write_run(self.in_dir, "chibios", "fair_perf", "01",
                  cycle_offset=0)
        write_run(self.in_dir, "chibios", "fair_perf", "02",
                  cycle_offset=2)
        write_run(self.in_dir, "chibios", "fair_perf", "03",
                  cycle_offset=1000)   # outlier
        proc = self._run(profile="fair_perf")
        self.assertEqual(proc.returncode, 0, proc.stderr)

        agg_csv = (self.out_dir / "fair_perf_aggregate.csv").read_text(
            encoding="utf-8").splitlines()
        # Header layout:
        #   rtos,rtos_version,profile,test,n_runs,n,min,median,mean,...
        header = agg_csv[0].split(",")
        median_col = header.index("median")
        n_runs_col = header.index("n_runs")
        # Look for chibios t1_irq row
        t1_row = None
        for line in agg_csv[1:]:
            fields = line.split(",")
            if fields[0] == "chibios" and fields[3] == "t1_irq":
                t1_row = fields
                break
        self.assertIsNotNone(t1_row)
        self.assertEqual(t1_row[n_runs_col], "3")
        # The dataset gives: per run, t1 valid = 200..209 + offset.
        # Median of each run is offset+205. Three runs offsets 0,2,
        # 1000 -> medians 205,207,1205 -> median-of-medians = 207.
        self.assertEqual(t1_row[median_col], "207",
                         f"row was {t1_row}")
        # Bonus: rtos_version column populated from the banner
        # fixture. The asserted value comes from the same KERNELS
        # constant the fixture wrote — it is NOT a hardcoded
        # version-number contract on the real firmware.
        rtos_ver_col = header.index("rtos_version")
        self.assertEqual(t1_row[rtos_ver_col], KERNELS["chibios"])


    # --- Round-11 §4 — run00 always excluded -----------------------

    def test_04_run00_excluded(self):
        # run00 + run01 + run02 -> aggregate must report n_runs=2,
        # not 3 (run00 is global warmup).
        for run in ("00", "01", "02"):
            write_run(self.in_dir, "chibios", "fair_perf", run,
                      cycle_offset=int(run))
        proc = self._run(profile="fair_perf")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        agg_csv = (self.out_dir / "fair_perf_aggregate.csv").read_text(
            encoding="utf-8").splitlines()
        header = agg_csv[0].split(",")
        n_runs_col = header.index("n_runs")
        for line in agg_csv[1:]:
            fields = line.split(",")
            self.assertEqual(fields[n_runs_col], "2",
                             f"row {line!r} should not include run00")
        # And run00's per-run summary file must NOT have been written.
        self.assertFalse(
            (self.out_dir
             / "chibios_fair_perf_run00_summary.md").is_file())

    # --- Round-11 §5 — publication-gate -----------------------------

    def _write_validated_json(self, rtos: str, profile: str,
                              run_id: str,
                              publication_mode: str = "la") -> None:
        """Drop a stub validation manifest next to the .csv so the
        publication-gate accepts the run. The manifest must match
        the contract `check_validated_manifest` enforces in
        report_results.py (round-12 §4 + ADR-015 2026-05-12)."""
        import json as _json
        path = self.in_dir / (
            f"{rtos}_{profile}_run{run_id}.validated.json")
        # Stable fake SHA256 hashes per (rtos, profile) so the
        # publication-gate's cross-run homogeneity check passes by
        # default. Deterministic and naturally homogeneous across
        # runs of the same (rtos, profile). Individual tests
        # override these to exercise the mismatch path.
        import hashlib as _hl
        fake_elf = _hl.sha256(
            f"{rtos}/{profile}/elf".encode()).hexdigest()
        fake_map = _hl.sha256(
            f"{rtos}/{profile}/map".encode()).hexdigest()
        manifest = {
            "schema":                 "rtos-benchmark/collect/v1",
            "validated":              True,
            "rtos":                   rtos,
            "profile":                profile,
            "run_id":                 run_id,
            "publication_mode":       publication_mode,
            "elf_sha256":             fake_elf,
            "elf_size_bytes":         123456,
            "map_sha256":             fake_map,
            "map_size_bytes":         7890,
            "system_clock_hz":        480_000_000,
            "vos_level":              "VOS0",
            "vosrdy":                 "READY",
            "flash_acr":              "0x00000034",
            "tickless":               "OFF",
            "wfi_in_idle":            "OFF",
            "tim2_after_t1_setup_ok": True,
            "memory_placement_ok":    True,
            "iteration_sequences_ok": True,
            "n_dwt_rows":             3 * 11000 + 100,
            "n_t4_pi_rows":           100,
        }
        path.write_text(_json.dumps(manifest, indent=2) + "\n",
                        encoding="utf-8")

    def _write_campaign_lock(self, profile: str,
                             publication_mode: str,
                             rtos_shas: dict[str, str]) -> None:
        """2026-05-13 overview-md test helper: drop a campaign
        lock JSON under <tmp>/manifest/<profile>_campaign.lock.json.
        @p rtos_shas maps rtos name -> 64-char hex elf SHA."""
        import json as _json
        manifest_dir = self.tmp / "manifest"
        manifest_dir.mkdir(exist_ok=True)
        lock = {
            "schema":           "rtos-benchmark/campaign-lock/v1",
            "profile":          profile,
            "publication_mode": publication_mode,
            "timestamp_utc":    "2026-05-13T12:34:56Z",
            "rtoses":           {
                rtos: {
                    "elf":         f"build/{rtos}.elf",
                    "elf_sha256":  sha,
                    "map":         f"build/{rtos}.map",
                    "map_sha256":  "f" * 64,
                }
                for rtos, sha in rtos_shas.items()
            },
        }
        (manifest_dir
         / f"{profile}_campaign.lock.json").write_text(
            _json.dumps(lock, indent=2) + "\n",
            encoding="utf-8")

    def test_05_publication_gate_full_set_passes(self):
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run,
                          cycle_offset=int(run))
                self._write_validated_json(rtos, "fair_perf", run)
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir", str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")

    def test_06_publication_gate_missing_rtos_fails(self):
        # Only chibios + freertos (5 runs each), zephyr missing.
        for rtos in ("chibios", "freertos"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run)
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir", str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("zephyr", proc.stderr)

    def test_07_publication_gate_missing_run_fails(self):
        # All 3 RTOSes, but zephyr is missing run04.
        for rtos in ("chibios", "freertos", "zephyr"):
            runs = ("01", "02", "03", "04", "05")
            if rtos == "zephyr":
                runs = ("01", "02", "03", "05")
            for run in runs:
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run)
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir", str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("'04'", proc.stderr)

    def test_08b_publication_gate_validated_json_wrong_run_id_fails(self):
        # Manifest claims to be run 99 but it is sitting next to run 01.
        # round-12 §4: gate must catch this.
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run)
        # Tamper the chibios run01 manifest: claim run_id "99".
        import json as _json
        path = (self.in_dir
                / "chibios_fair_perf_run01.validated.json")
        m = _json.loads(path.read_text(encoding="utf-8"))
        m["run_id"] = "99"
        path.write_text(_json.dumps(m, indent=2) + "\n",
                        encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir", str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("run_id=", proc.stderr)

    def test_08c_publication_gate_validated_json_flash_acr_wrong_fails(self):
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run)
        # Tamper one manifest with the pre-ADR-018 Zephyr value.
        import json as _json
        path = (self.in_dir
                / "zephyr_fair_perf_run03.validated.json")
        m = _json.loads(path.read_text(encoding="utf-8"))
        m["flash_acr"] = "0x00000032"
        path.write_text(_json.dumps(m, indent=2) + "\n",
                        encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir", str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("flash_acr=", proc.stderr)

    def test_08_publication_gate_missing_validated_json_fails(self):
        # Full 3 RTOS x 5 runs but ZERO validated.json files.
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir", str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("validated.json", proc.stderr)

    # --- Round-12 §5 — exploratory banner without publication gate --

    def test_08d_exploratory_banner_present_without_gate(self):
        write_run(self.in_dir, "chibios", "fair_perf", "01")
        proc = self._run(profile="fair_perf")
        self.assertEqual(proc.returncode, 0)
        for fname in ("fair_perf_aggregate.md",
                      "fair_perf_compare.md",
                      "chibios_fair_perf_run01_summary.md"):
            text = (self.out_dir / fname).read_text(encoding="utf-8")
            self.assertIn("EXPLORATORY ONLY", text,
                          f"missing exploratory banner in {fname}")

    def test_08e_no_exploratory_banner_with_gate(self):
        # Need a full publication-grade input set so the gate
        # actually passes.
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run)
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir", str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        for fname in ("fair_perf_aggregate.md",
                      "fair_perf_compare.md"):
            text = (self.out_dir / fname).read_text(encoding="utf-8")
            self.assertNotIn("EXPLORATORY ONLY", text,
                             f"unexpected exploratory banner in {fname}")

    # --- 2026-05-12 — debug_dev refusal + T4 PI gate ----------------

    def test_08f_publication_gate_debug_dev_fails(self):
        # ADR-011: debug_dev is non-publishable. If any debug_dev
        # run enters the gate, the publication build must fail.
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run)
                write_run(self.in_dir, rtos, "debug_dev", run)
                self._write_validated_json(rtos, "debug_dev", run)
        cmd = [sys.executable, str(SCRIPT),
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("debug_dev", proc.stderr)
        self.assertIn("ADR-011", proc.stderr)

    def test_08g_publication_gate_t4_pi_failure_fails(self):
        # ADR-014: any pi_ok == 0 in any run invalidates the PI
        # claim. Gate must fail even when every other manifest is
        # sound.
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run)
        # Tamper one T4 PI file: flip iteration 7 to pi_ok=0.
        path = (self.in_dir
                / "freertos_fair_perf_run02.t4_pi.csv")
        lines = path.read_text(encoding="utf-8").splitlines()
        for i, line in enumerate(lines):
            if line.startswith("freertos,fair_perf,t4_mtx_pi,7,"):
                lines[i] = "freertos,fair_perf,t4_mtx_pi,7,0"
                break
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("T4 PI failure", proc.stderr)
        self.assertIn("ADR-014", proc.stderr)

    # --- 2026-05-12 — publication_mode field (ADR-015) --------------

    def test_08h_publication_gate_missing_publication_mode_fails(self):
        # All runs valid but one manifest is missing the
        # publication_mode key.
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run)
        import json as _json
        path = (self.in_dir
                / "chibios_fair_perf_run01.validated.json")
        m = _json.loads(path.read_text(encoding="utf-8"))
        del m["publication_mode"]
        path.write_text(_json.dumps(m, indent=2) + "\n",
                        encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("publication_mode", proc.stderr)

    def test_08i_publication_gate_invalid_publication_mode_fails(self):
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run)
        import json as _json
        path = (self.in_dir
                / "freertos_fair_perf_run04.validated.json")
        m = _json.loads(path.read_text(encoding="utf-8"))
        m["publication_mode"] = "bogus_mode"
        path.write_text(_json.dumps(m, indent=2) + "\n",
                        encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("publication_mode", proc.stderr)

    def test_08j_publication_gate_mixed_mode_fails(self):
        # 14 runs declare "la", 1 declares "dwt_only" — gate must
        # refuse the mix per ADR-015.
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                mode = ("dwt_only"
                        if (rtos, run) == ("zephyr", "03")
                        else "la")
                self._write_validated_json(
                    rtos, "fair_perf", run,
                    publication_mode=mode)
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("mixed publication", proc.stderr)
        self.assertIn("ADR-015", proc.stderr)

    # --- 2a (Codex round-3) — ELF / MAP SHA in validated.json -------

    def test_08k_publication_gate_missing_elf_sha_fails(self):
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run)
        import json as _json
        path = (self.in_dir
                / "chibios_fair_perf_run01.validated.json")
        m = _json.loads(path.read_text(encoding="utf-8"))
        del m["elf_sha256"]
        path.write_text(_json.dumps(m, indent=2) + "\n",
                        encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("elf_sha256", proc.stderr)

    def test_08l_publication_gate_malformed_elf_sha_fails(self):
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run)
        import json as _json
        path = (self.in_dir
                / "freertos_fair_perf_run02.validated.json")
        m = _json.loads(path.read_text(encoding="utf-8"))
        m["elf_sha256"] = ""   # empty -> malformed
        path.write_text(_json.dumps(m, indent=2) + "\n",
                        encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("elf_sha256", proc.stderr)

    def test_08l2_publication_gate_uppercase_elf_sha_fails(self):
        # Validated JSON contains an otherwise-well-formed
        # elf_sha256 but in uppercase hex. SHA256_RE is
        # lowercase-only, so the publication gate must reject it.
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run)
        import json as _json
        path = (self.in_dir
                / "freertos_fair_perf_run02.validated.json")
        m = _json.loads(path.read_text(encoding="utf-8"))
        # 64 uppercase hex chars -- well-formed length, wrong case.
        m["elf_sha256"] = "A" * 64
        path.write_text(_json.dumps(m, indent=2) + "\n",
                        encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("elf_sha256", proc.stderr)

    def test_08m_publication_gate_cross_run_sha_mismatch_fails(self):
        # 5 chibios runs but run03 has a different elf_sha256 -> a
        # different firmware was flashed mid-campaign. The error
        # message must mention the file and the hashes.
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run)
        import json as _json
        path = (self.in_dir
                / "chibios_fair_perf_run03.validated.json")
        m = _json.loads(path.read_text(encoding="utf-8"))
        m["elf_sha256"] = "f" * 64
        path.write_text(_json.dumps(m, indent=2) + "\n",
                        encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("elf_sha256 mismatch", proc.stderr)
        self.assertIn("chibios_fair_perf_run03.csv", proc.stderr)
        self.assertIn("f" * 64, proc.stderr)

    def test_08n_publication_gate_sha_homogeneous_passes(self):
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run)
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")

    def test_08o_publication_gate_missing_map_sha_fails(self):
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run)
        import json as _json
        path = (self.in_dir
                / "zephyr_fair_perf_run05.validated.json")
        m = _json.loads(path.read_text(encoding="utf-8"))
        del m["map_sha256"]
        path.write_text(_json.dumps(m, indent=2) + "\n",
                        encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("map_sha256", proc.stderr)

    def test_08p_publication_gate_malformed_map_sha_fails(self):
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run)
        import json as _json
        path = (self.in_dir
                / "chibios_fair_perf_run04.validated.json")
        m = _json.loads(path.read_text(encoding="utf-8"))
        m["map_sha256"] = ""
        path.write_text(_json.dumps(m, indent=2) + "\n",
                        encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("map_sha256", proc.stderr)

    def test_08q_publication_gate_cross_run_map_sha_mismatch_fails(self):
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run)
        import json as _json
        path = (self.in_dir
                / "freertos_fair_perf_run02.validated.json")
        m = _json.loads(path.read_text(encoding="utf-8"))
        m["map_sha256"] = "e" * 64
        path.write_text(_json.dumps(m, indent=2) + "\n",
                        encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("map_sha256 mismatch", proc.stderr)
        self.assertIn("freertos_fair_perf_run02.csv", proc.stderr)
        self.assertIn("e" * 64, proc.stderr)

    # --- Round-11 §6 — source column --------------------------------

    def test_09_source_column_la_mode(self):
        # Mode LA: T1 / T4 are DWT_validation (LA-primary), T2/T3 DWT.
        write_run(self.in_dir, "chibios", "fair_perf", "01")
        self._write_validated_json("chibios", "fair_perf", "01",
                                   publication_mode="la")
        proc = self._run(profile="fair_perf")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        agg_csv = (self.out_dir / "fair_perf_aggregate.csv").read_text(
            encoding="utf-8").splitlines()
        header = agg_csv[0].split(",")
        self.assertIn("source", header)
        src_col = header.index("source")
        for line in agg_csv[1:]:
            fields = line.split(",")
            if fields[3] in ("t1_irq", "t4_mtx_pi"):
                self.assertEqual(fields[src_col], "DWT_validation")
            elif fields[3] in ("t2_handoff", "t3_mtx_uncont"):
                self.assertEqual(fields[src_col], "DWT")
        agg_md = (self.out_dir / "fair_perf_aggregate.md").read_text(
            encoding="utf-8")
        self.assertIn("DWT_validation", agg_md)
        self.assertIn("DWT", agg_md)

    def test_09b_source_column_dwt_only_mode(self):
        # Phase 1 Mode DWT-only: every test reports source "DWT".
        # "DWT_validation" must NOT appear in either CSV or MD.
        write_run(self.in_dir, "chibios", "fair_perf", "01")
        self._write_validated_json("chibios", "fair_perf", "01",
                                   publication_mode="dwt_only")
        proc = self._run(profile="fair_perf")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        agg_csv = (self.out_dir / "fair_perf_aggregate.csv").read_text(
            encoding="utf-8").splitlines()
        header = agg_csv[0].split(",")
        src_col = header.index("source")
        for line in agg_csv[1:]:
            fields = line.split(",")
            if fields[3] in ("t1_irq", "t2_handoff",
                             "t3_mtx_uncont", "t4_mtx_pi"):
                self.assertEqual(fields[src_col], "DWT",
                                 msg=f"row was: {line}")
        agg_md = (self.out_dir / "fair_perf_aggregate.md").read_text(
            encoding="utf-8")
        self.assertNotIn("DWT_validation", agg_md)
        self.assertIn("DWT", agg_md)

    # --- Round-11 §7 — run_min / run_max / run_spread ---------------

    def test_10_run_spread_columns(self):
        # Three runs with cycle_offset 0 / 1 / 5 — t1 medians should
        # be 205, 206, 210; spread = 5.
        write_run(self.in_dir, "chibios", "fair_perf", "01",
                  cycle_offset=0)
        write_run(self.in_dir, "chibios", "fair_perf", "02",
                  cycle_offset=1)
        write_run(self.in_dir, "chibios", "fair_perf", "03",
                  cycle_offset=5)
        proc = self._run(profile="fair_perf")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        agg_csv = (self.out_dir / "fair_perf_aggregate.csv").read_text(
            encoding="utf-8").splitlines()
        header = agg_csv[0].split(",")
        c_min, c_max, c_spread = (header.index("run_min"),
                                  header.index("run_max"),
                                  header.index("run_spread"))
        for line in agg_csv[1:]:
            fields = line.split(",")
            if fields[3] == "t1_irq":
                self.assertEqual(fields[c_min],    "205")
                self.assertEqual(fields[c_max],    "210")
                self.assertEqual(fields[c_spread], "5")

    # --- 2a-bis followup — compare-md attribution -------------------

    def test_11_compare_md_dwt_only_attribution(self):
        write_run(self.in_dir, "chibios", "fair_perf", "01")
        self._write_validated_json("chibios", "fair_perf", "01",
                                   publication_mode="dwt_only")
        proc = self._run(profile="fair_perf")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        md = (self.out_dir / "fair_perf_compare.md").read_text(
            encoding="utf-8")
        self.assertIn("Phase 1 (DWT-only)", md)
        self.assertIn("A4 - A1", md)
        self.assertIn("dwt_a4_minus_a1", md)
        self.assertIn("EXCLUDED", md)
        self.assertIn("ADR-015", md)
        # Must NOT promise LA-equivalent.
        self.assertNotIn("A4 - A0_HW", md)
        self.assertNotIn("Mode LA", md)

    def test_12_compare_md_la_attribution(self):
        write_run(self.in_dir, "chibios", "fair_perf", "01")
        self._write_validated_json("chibios", "fair_perf", "01",
                                   publication_mode="la")
        proc = self._run(profile="fair_perf")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        md = (self.out_dir / "fair_perf_compare.md").read_text(
            encoding="utf-8")
        self.assertIn("Mode LA", md)
        self.assertIn("A4 - A0_HW", md)
        self.assertIn("ADR-015", md)
        # Must NOT promise DWT-only Phase 1 wording.
        self.assertNotIn("Phase 1 (DWT-only)", md)

    # --- 2026-05-13 overview-md (Codex round-3 PLAN APPROVE) -------

    def test_13_overview_dwt_only_full_set(self):
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run,
                                           publication_mode="dwt_only")
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        md = (self.out_dir / "fair_perf_overview.md").read_text(
            encoding="utf-8")
        # Header.
        self.assertIn("publication-gated = yes", md)
        self.assertIn("publication mode = dwt_only", md)
        # Attribution.
        self.assertIn("Phase 1 (DWT-only)", md)
        self.assertIn("dwt_a4_minus_a1", md)
        self.assertIn("EXCLUDED", md)
        self.assertIn("ADR-015", md)
        # Configuration snapshot.
        self.assertIn("## Configuration snapshot", md)
        self.assertIn("flash_acr", md)
        self.assertIn("0x00000034", md)
        # Headline table — 3 RTOS x 4 tests = 12 rows.
        for rtos in ("chibios", "freertos", "zephyr"):
            for test in ("t1_irq", "t2_handoff",
                         "t3_mtx_uncont", "t4_mtx_pi"):
                self.assertRegex(
                    md,
                    rf"\|\s*{rtos}\s*\|\s*{test}\s*\|",
                    msg=f"missing headline row {rtos}/{test}")
        # PI section + pointers.
        self.assertIn("TEST 4 priority inheritance", md)
        self.assertIn("`fair_perf_aggregate.md`", md)
        self.assertIn("`fair_perf_compare.md`", md)

    def test_14_overview_la_full_set(self):
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run,
                                           publication_mode="la")
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        md = (self.out_dir / "fair_perf_overview.md").read_text(
            encoding="utf-8")
        self.assertIn("publication mode = la", md)
        self.assertIn("Mode LA", md)
        self.assertIn("A4 - A0_HW", md)
        self.assertNotIn("Phase 1 (DWT-only)", md)

    def test_15_overview_exploratory_single_run(self):
        # No validated.json => exploratory, publication_mode
        # unresolved.
        write_run(self.in_dir, "chibios", "fair_perf", "01")
        proc = self._run(profile="fair_perf")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        md = (self.out_dir / "fair_perf_overview.md").read_text(
            encoding="utf-8")
        self.assertIn("EXPLORATORY ONLY", md)
        self.assertIn("publication-gated = no", md)
        self.assertIn("publication mode = unknown", md)
        self.assertIn("Source attribution — unresolved", md)
        self.assertIn(
            "Numbers MUST NOT be quoted as official benchmark data",
            md)
        # Lock not present.
        self.assertIn("(not recorded)", md)

    def test_16_overview_missing_lock_does_not_crash(self):
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run,
                                           publication_mode="dwt_only")
        # Intentionally do NOT call _write_campaign_lock.
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        md = (self.out_dir / "fair_perf_overview.md").read_text(
            encoding="utf-8")
        # No Campaign lock timestamp row.
        self.assertNotIn("Campaign lock timestamp", md)
        # ELF SHA row should show "(not recorded)" for every RTOS.
        self.assertIn("(not recorded)", md)

    def test_17_overview_lock_shows_short_sha(self):
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run,
                                           publication_mode="dwt_only")
        self._write_campaign_lock(
            "fair_perf", "dwt_only",
            {
                "chibios":  "a" * 64,
                "freertos": "b" * 64,
                "zephyr":   "c" * 64,
            })
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        md = (self.out_dir / "fair_perf_overview.md").read_text(
            encoding="utf-8")
        self.assertIn("Campaign lock timestamp: 2026-05-13", md)
        # Short ELF SHA prefixes, one per RTOS.
        self.assertIn("`aaaaaaaa...`", md)
        self.assertIn("`bbbbbbbb...`", md)
        self.assertIn("`cccccccc...`", md)

    def test_18_overview_malformed_valid_json_lock_does_not_crash(self):
        # Lock file is syntactically valid JSON but not an object;
        # the overview must render with "(not recorded)" rather
        # than crashing on a `.get()` call (Codex round-3
        # overview-md PASS_WITH_FIXES followup).
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run,
                                           publication_mode="dwt_only")
        manifest_dir = self.tmp / "manifest"
        manifest_dir.mkdir(exist_ok=True)
        (manifest_dir / "fair_perf_campaign.lock.json").write_text(
            "[]\n", encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        md = (self.out_dir / "fair_perf_overview.md").read_text(
            encoding="utf-8")
        self.assertNotIn("Campaign lock timestamp", md)
        self.assertIn("(not recorded)", md)

    def test_19_overview_lock_mode_mismatch_warns_and_keeps_validated(self):
        # Validated runs say dwt_only; the lock claims la.
        # Validated mode wins; a WARNING line is appended.
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf", run,
                                           publication_mode="dwt_only")
        self._write_campaign_lock(
            "fair_perf", "la",
            {"chibios":  "a" * 64,
             "freertos": "b" * 64,
             "zephyr":   "c" * 64})
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        md = (self.out_dir / "fair_perf_overview.md").read_text(
            encoding="utf-8")
        # Validated mode wins.
        self.assertIn("publication mode = dwt_only", md)
        # WARNING line referencing both modes.
        self.assertIn("WARNING", md)
        self.assertIn("'la'", md)
        self.assertIn("'dwt_only'", md)
        # Attribution stays DWT-only.
        self.assertIn("Phase 1 (DWT-only)", md)
        self.assertNotIn("Mode LA", md)


    # --- Codex round 2026-05-14-bucket-c4-...-001
    # IMPORTANT 1 — run00 warmup enforcement ---

    def test_20_missing_run00_for_one_rtos_fails(self):
        # Full 5x3 run01..05 set, but the pre-populated
        # zephyr run00 is deleted. Publication gate must
        # fail with an ADR-013 reference.
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf",
                                           run)
        # Remove zephyr's run00 only.
        (self.in_dir
         / "zephyr_fair_perf_run00.csv").unlink()
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True,
                              text=True, encoding="utf-8",
                              env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("zephyr/fair_perf", proc.stderr)
        self.assertIn("missing run00", proc.stderr)
        self.assertIn("ADR-013", proc.stderr)

    def test_21_missing_run00_for_all_rtoses_fails(self):
        # Full 5x3 run01..05 set, but EVERY pre-populated
        # run00 is deleted.
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf",
                                           run)
        for rtos in ("chibios", "freertos", "zephyr"):
            (self.in_dir
             / f"{rtos}_fair_perf_run00.csv").unlink()
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True,
                              text=True, encoding="utf-8",
                              env=env)
        self.assertNotEqual(proc.returncode, 0)
        # All 3 RTOSes flagged.
        for rtos in ("chibios", "freertos", "zephyr"):
            self.assertIn(f"{rtos}/fair_perf", proc.stderr)
        self.assertIn("missing run00", proc.stderr)

    def test_22_run00_present_full_set_passes(self):
        # Sanity: the existing PASS path still works under
        # the new gate (run00 was pre-populated in setUp).
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf",
                                           run)
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True,
                              text=True, encoding="utf-8",
                              env=env)
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")

    # --- Codex round 2026-05-14-bucket-c4-...-002
    # IMPORTANT 1 — validated warmup enforcement ---

    def test_23_missing_run00_validated_fails(self):
        # Full 5x3 run01..05 set + run00 CSV present (from
        # setUp) but the zephyr run00 validated.json is
        # deleted.
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf",
                                           run)
        (self.in_dir
         / "zephyr_fair_perf_run00.validated.json").unlink()
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True,
                              text=True, encoding="utf-8",
                              env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("zephyr/fair_perf", proc.stderr)
        self.assertIn(
            "run00 CSV present but missing companion",
            proc.stderr)
        self.assertIn("zephyr_fair_perf_run00.validated.json",
                      proc.stderr)

    def test_24_run00_sha_mismatch_fails(self):
        # Full 5x3 run01..05 set with consistent SHA; the
        # zephyr run00 validated.json is overwritten with a
        # different elf_sha256.
        import json as _json
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf",
                                           run)
        warmup_path = (self.in_dir
                       / "zephyr_fair_perf_run00.validated.json")
        m = _json.loads(warmup_path.read_text(
            encoding="utf-8"))
        m["elf_sha256"] = "e" * 64
        warmup_path.write_text(
            _json.dumps(m, indent=2) + "\n",
            encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True,
                              text=True, encoding="utf-8",
                              env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("zephyr/fair_perf", proc.stderr)
        self.assertIn(
            "run00 elf_sha256 = ee", proc.stderr)
        self.assertIn(
            "does not match run01..05 elf_sha256",
            proc.stderr)
        self.assertIn(
            "different firmware build", proc.stderr)

    def test_25_run00_manifest_wrong_run_id_fails(self):
        # Run00 validated.json carries the wrong run_id
        # field (e.g. operator copied a run01 manifest by
        # mistake). The manifest contract check must catch
        # it.
        import json as _json
        for rtos in ("chibios", "freertos", "zephyr"):
            for run in ("01", "02", "03", "04", "05"):
                write_run(self.in_dir, rtos, "fair_perf", run)
                self._write_validated_json(rtos, "fair_perf",
                                           run)
        warmup_path = (self.in_dir
                       / "zephyr_fair_perf_run00.validated.json")
        m = _json.loads(warmup_path.read_text(
            encoding="utf-8"))
        m["run_id"] = "01"  # wrong — should be "00"
        warmup_path.write_text(
            _json.dumps(m, indent=2) + "\n",
            encoding="utf-8")
        cmd = [sys.executable, str(SCRIPT),
               "--profile", "fair_perf",
               "--input-dir",  str(self.in_dir),
               "--output-dir", str(self.out_dir),
               "--publication-gate"]
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        proc = subprocess.run(cmd, capture_output=True,
                              text=True, encoding="utf-8",
                              env=env)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn(
            "zephyr_fair_perf_run00.validated.json",
            proc.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=2)
