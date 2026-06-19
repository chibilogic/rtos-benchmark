#!/usr/bin/env python3
"""Validation suite for scripts/cflags_audit.py (C3-step1).

Covers:
  - FreeRTOS RTOS path (new in C3-step1).
  - Cross-RTOS sanity (wrapper backward compat, CMake export
    flag in FreeRTOS CMakeLists.txt).

The Zephyr-only coverage continues to live in
`tests/test_zephyr_cflags_audit.py`, which invokes the
backward-compatibility wrapper.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT    = REPO_ROOT / "scripts" / "cflags_audit.py"


GOOD_FLAGS = [
    "-mcpu=cortex-m7",
    "-mthumb",
    "-mfpu=fpv5-d16",
    "-mfloat-abi=hard",
    "-O2",
    "-fomit-frame-pointer",
    "-falign-functions=16",
    "-ffunction-sections",
    "-fdata-sections",
    "-fno-common",
    "-fno-strict-aliasing",
]


def make_command(*extra_flags: str) -> str:
    args = (["arm-none-eabi-gcc"] + GOOD_FLAGS + list(extra_flags)
            + ["-c", "-o", "out.o", "main.c"])
    return " ".join(args)


def freertos_app_entry(name: str, *extra_flags: str) -> dict:
    return {
        "directory": "/build",
        "command":   make_command(*extra_flags),
        "file":      f"/repo/freertos/benchmark_freertos/{name}",
    }


def freertos_vendor_entry(name: str) -> dict:
    # system/*.c are CubeH7 vendor files; the audit must IGNORE
    # them. Bad flags on purpose -- they must not fail the gate.
    return {
        "directory": "/build",
        "command":
            "arm-none-eabi-gcc -Os -flto -c -o sys.o sys.c",
        "file":
            f"/repo/freertos/benchmark_freertos/system/{name}",
    }


def freertos_kernel_entry(name: str) -> dict:
    # FreeRTOS kernel sources are out of scope.
    return {
        "directory": "/build",
        "command":
            "arm-none-eabi-gcc -Os -flto -c -o k.o k.c",
        "file":
            f"/repo/freertos/FreeRTOS-Kernel/{name}",
    }


def common_entry(name: str, *extra_flags: str) -> dict:
    return {
        "directory": "/build",
        "command":   make_command(*extra_flags),
        "file":      f"/repo/common/{name}",
    }


# Codex round 2026-05-14-bucket-c-track-001 IMPORTANT 1
# (publishable-profile source-set completeness gate).
APP_BASENAMES = (
    "main.c",
    "test_ctxsw_irq.c",
    "test_thread_handoff.c",
    "test_mutex_uncontended.c",
    "test_mutex_pi.c",
)
COMMON_BASENAMES = (
    "dwt_cycle_counter.c",
    "benchmark_stats.c",
    "bench_button.c",
)


def full_freertos_set() -> list[dict]:
    """All 8 expected FreeRTOS entries with clean flags."""
    return ([freertos_app_entry(n) for n in APP_BASENAMES]
            + [common_entry(n) for n in COMMON_BASENAMES])


def chibios_app_entry(name: str, *extra_flags: str) -> dict:
    return {
        "directory": "/build",
        "command":   make_command(*extra_flags),
        "file": (f"/repo/chibios/benchmark_chibios/{name}"),
    }


def full_chibios_set() -> list[dict]:
    return ([chibios_app_entry(n) for n in APP_BASENAMES]
            + [common_entry(n) for n in COMMON_BASENAMES])


def zephyr_app_entry(name: str, *extra_flags: str) -> dict:
    return {
        "directory": "/build",
        "command":   make_command(*extra_flags),
        "file":      f"/src/benchmark_zephyr/src/{name}",
    }


def full_zephyr_set() -> list[dict]:
    return ([zephyr_app_entry(n) for n in APP_BASENAMES]
            + [common_entry(n) for n in COMMON_BASENAMES])


def write_cc(build_dir: Path, *all_entries) -> None:
    flat: list = []
    for e in all_entries:
        if isinstance(e, list):
            flat.extend(e)
        else:
            flat.append(e)
    (build_dir / "compile_commands.json").write_text(
        json.dumps(flat), encoding="utf-8")


def run_audit(build_dir: Path, profile: str,
              rtos: str) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(SCRIPT),
           "--rtos", rtos,
           "--build-dir", str(build_dir),
           "--profile", profile]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", env=env)


class FreertosCflagsAuditTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.build_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_01_clean_fair_perf_passes(self):
        write_cc(self.build_dir, [
            freertos_app_entry("main.c"),
            freertos_app_entry("test_ctxsw_irq.c"),
            freertos_app_entry("test_thread_handoff.c"),
            freertos_app_entry("test_mutex_uncontended.c"),
            freertos_app_entry("test_mutex_pi.c"),
            common_entry("dwt_cycle_counter.c"),
            common_entry("benchmark_stats.c"),
            common_entry("bench_button.c"),
        ], [
            freertos_vendor_entry("system_stm32h7xx.c"),
            freertos_vendor_entry("stm32h7xx_it.c"),
            freertos_vendor_entry("syscalls_stubs.c"),
            freertos_kernel_entry("tasks.c"),
        ])
        proc = run_audit(self.build_dir, "fair_perf",
                         rtos="freertos")
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")
        self.assertIn("8 FreeRTOS application object",
                      proc.stdout)

    def test_02_missing_required_flag_fails(self):
        bad = freertos_app_entry("test_ctxsw_irq.c")
        bad["command"] = bad["command"].replace(
            "-fomit-frame-pointer ", "")
        write_cc(self.build_dir, [
            freertos_app_entry("main.c"),
            bad,
        ])
        proc = run_audit(self.build_dir, "fair_perf",
                         rtos="freertos")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("missing flag -fomit-frame-pointer",
                      proc.stderr)
        self.assertIn("test_ctxsw_irq.c", proc.stderr)

    def test_03_forbidden_lto_fails(self):
        bad = freertos_app_entry("main.c", "-flto")
        write_cc(self.build_dir, [bad])
        proc = run_audit(self.build_dir, "fair_perf",
                         rtos="freertos")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("forbidden flag -flto", proc.stderr)

    def test_04_lto_variant_fails(self):
        bad = freertos_app_entry("main.c", "-flto=auto")
        write_cc(self.build_dir, [bad])
        proc = run_audit(self.build_dir, "fair_perf",
                         rtos="freertos")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("forbidden flag -flto", proc.stderr)

    def test_05_vendor_system_not_audited(self):
        # FreeRTOS system/*.c files have garbage flags on
        # purpose. The audit must IGNORE them and pass on the
        # full in-scope set.
        write_cc(self.build_dir,
                 full_freertos_set(),
                 [freertos_vendor_entry("system_stm32h7xx.c"),
                  freertos_vendor_entry("stm32h7xx_it.c"),
                  freertos_vendor_entry("syscalls_stubs.c")])
        proc = run_audit(self.build_dir, "fair_perf",
                         rtos="freertos")
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")
        self.assertIn("8 FreeRTOS application object",
                      proc.stdout)

    def test_06_kernel_not_audited(self):
        write_cc(self.build_dir,
                 full_freertos_set(),
                 [freertos_kernel_entry("tasks.c"),
                  freertos_kernel_entry("queue.c"),
                  freertos_kernel_entry("portable/GCC/ARM_CM7/"
                                        "r0p1/port.c")])
        proc = run_audit(self.build_dir, "fair_perf",
                         rtos="freertos")
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")

    def test_07_common_audited(self):
        # full_freertos_set() already includes all 3 common
        # entries plus the 5 app entries required by the
        # publishable-profile completeness gate.
        write_cc(self.build_dir, full_freertos_set())
        proc = run_audit(self.build_dir, "fair_perf",
                         rtos="freertos")
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")
        self.assertIn("8 FreeRTOS application object",
                      proc.stdout)

    def test_08_common_bad_flag_fails(self):
        bad = common_entry("dwt_cycle_counter.c")
        bad["command"] = bad["command"].replace(
            "-fno-common ", "")
        write_cc(self.build_dir, [
            freertos_app_entry("main.c"),
            bad,
        ])
        proc = run_audit(self.build_dir, "fair_perf",
                         rtos="freertos")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("dwt_cycle_counter.c", proc.stderr)
        self.assertIn("missing flag -fno-common", proc.stderr)

    def test_09_realistic_tickless_same_contract(self):
        write_cc(self.build_dir, full_freertos_set())
        proc = run_audit(self.build_dir, "realistic_tickless",
                         rtos="freertos")
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")

    def test_10_debug_dev_skipped(self):
        bad = {"directory": "/build",
               "command":
                   "arm-none-eabi-gcc -Os -flto -c main.c",
               "file":
                   "/repo/freertos/benchmark_freertos/main.c"}
        write_cc(self.build_dir, [bad])
        proc = run_audit(self.build_dir, "debug_dev",
                         rtos="freertos")
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")
        self.assertIn("audit skipped", proc.stdout)

    def test_11_O1_fails(self):
        e = freertos_app_entry("main.c")
        e["command"] = e["command"].replace(" -O2 ", " -O1 ")
        write_cc(self.build_dir, [e])
        proc = run_audit(self.build_dir, "fair_perf",
                         rtos="freertos")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("-O1", proc.stderr)

    def test_12_Og_fails(self):
        e = freertos_app_entry("main.c")
        e["command"] = e["command"].replace(" -O2 ", " -Og ")
        write_cc(self.build_dir, [e])
        proc = run_audit(self.build_dir, "fair_perf",
                         rtos="freertos")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("-Og", proc.stderr)

    def test_13_O2_followed_by_O3_fails(self):
        # The last -O on the command line wins.
        e = freertos_app_entry("main.c", "-O3")
        write_cc(self.build_dir, [e])
        proc = run_audit(self.build_dir, "fair_perf",
                         rtos="freertos")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("wrong effective optimization",
                      proc.stderr)
        self.assertIn("-O3", proc.stderr)

    def test_14_no_app_entries_fails(self):
        # Only vendor entries -> audit must fail with explicit
        # "no application sources matched" error.
        write_cc(self.build_dir, [],
                 [freertos_vendor_entry("system_stm32h7xx.c"),
                  freertos_kernel_entry("tasks.c")])
        proc = run_audit(self.build_dir, "fair_perf",
                         rtos="freertos")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no application sources matched",
                      proc.stderr)

    def test_15_missing_cc_file_fails(self):
        proc = run_audit(self.build_dir, "fair_perf",
                         rtos="freertos")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("compile_commands.json", proc.stderr)
        self.assertIn("not found", proc.stderr)


class FreertosCompletenessTest(unittest.TestCase):
    """Codex round 2026-05-14-bucket-c-track-001 IMPORTANT 1
    (publishable-profile source-set completeness gate)."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.build_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_28_missing_test_thread_handoff_fails(self):
        entries = [e for e in full_freertos_set()
                   if not e["file"].endswith(
                       "test_thread_handoff.c")]
        write_cc(self.build_dir, entries)
        proc = run_audit(self.build_dir, "fair_perf",
                         rtos="freertos")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("missing source test_thread_handoff.c",
                      proc.stderr)

    def test_29_missing_bench_button_fails(self):
        entries = [e for e in full_freertos_set()
                   if not e["file"].endswith("bench_button.c")]
        write_cc(self.build_dir, entries)
        proc = run_audit(self.build_dir, "fair_perf",
                         rtos="freertos")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("missing source bench_button.c",
                      proc.stderr)

    def test_30_realistic_tickless_enforced(self):
        entries = [e for e in full_freertos_set()
                   if not e["file"].endswith("main.c")]
        write_cc(self.build_dir, entries)
        proc = run_audit(self.build_dir,
                         "realistic_tickless",
                         rtos="freertos")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("missing source main.c", proc.stderr)

    def test_31_debug_dev_skipped(self):
        # An incomplete set under debug_dev must still produce
        # the "audit skipped" output (no contract).
        write_cc(self.build_dir,
                 [freertos_app_entry("main.c")])
        proc = run_audit(self.build_dir, "debug_dev",
                         rtos="freertos")
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")
        self.assertIn("audit skipped", proc.stdout)

    def test_32_bare_O_fails(self):
        # Bare '-O' (no level digit) is valid GCC but NOT
        # equivalent to '-O2' (Codex MINOR 1).
        entries = full_freertos_set()
        entries[0]["command"] = entries[0]["command"].replace(
            " -O2 ", " -O ")
        write_cc(self.build_dir, entries)
        proc = run_audit(self.build_dir, "fair_perf",
                         rtos="freertos")
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("wrong effective optimization",
                      proc.stderr)
        self.assertIn("-O (expected -O2)", proc.stderr)


class CrossRtosSanityTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.build_dir = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_16_freertos_cmakelists_exports_compile_commands(
            self):
        # FreeRTOS CMakeLists.txt must explicitly enable
        # compile_commands.json export so the C3-step1 audit
        # has data to read.
        cml = (REPO_ROOT / "freertos" / "benchmark_freertos"
               / "CMakeLists.txt").read_text(encoding="utf-8")
        self.assertIn("CMAKE_EXPORT_COMPILE_COMMANDS ON", cml,
                      "FreeRTOS CMakeLists.txt must enable "
                      "compile_commands.json export")

    def test_17_zephyr_via_new_script_passes(self):
        # Generalised script via --rtos zephyr accepts Zephyr
        # paths (parity with the legacy wrapper).
        write_cc(self.build_dir, full_zephyr_set())
        proc = run_audit(self.build_dir, "fair_perf",
                         rtos="zephyr")
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")
        self.assertIn("8 Zephyr application object",
                      proc.stdout)

    def test_18_chibios_path_recognised(self):
        # The chibios regex set is wired. The full app set
        # under benchmark_chibios/ must be in scope; cfg/
        # must be out of scope (port glue).
        out_of_scope = {
            "directory": "/build",
            "command":   "arm-none-eabi-gcc -Os -flto -c c.c",
            "file":
                "/repo/chibios/benchmark_chibios/cfg/portab.c",
        }
        write_cc(self.build_dir,
                 full_chibios_set() + [out_of_scope])
        proc = run_audit(self.build_dir, "fair_perf",
                         rtos="chibios")
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")
        self.assertIn("8 ChibiOS application object",
                      proc.stdout)


CHIBIOS_SYNTH = REPO_ROOT / "scripts" / \
                "chibios_synth_compile_commands.py"


def _good_chibios_cc_line(source: str) -> str:
    """A representative `arm-none-eabi-gcc -c ...` line as
    ChibiOS rules.mk would print under `make -n`."""
    flags = " ".join(GOOD_FLAGS)
    return (f"arm-none-eabi-gcc {flags} "
            f"-DBENCH_RTOS_CHIBIOS -DSTM32H750xx "
            f"-I../../common -MD -MP -MF .dep/foo.d "
            f"-c -o build/fair_perf/obj/foo.o {source}")


def _run_synth(make_log: Path, build_dir: Path,
               workdir: Path
               ) -> subprocess.CompletedProcess:
    cmd = [sys.executable, str(CHIBIOS_SYNTH),
           "--make-log", str(make_log),
           "--build-dir", str(build_dir),
           "--workdir", str(workdir)]
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run(cmd, capture_output=True, text=True,
                          encoding="utf-8", env=env)


class ChibiosSynthCompileCommandsTest(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root      = Path(self._tmp.name)
        self.log_path  = self.root / "make-dry-run.log"
        self.build_dir = self.root / "build" / "fair_perf"
        self.workdir   = self.root / "src"
        self.workdir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        self._tmp.cleanup()

    def _write_log(self, *lines: str) -> None:
        self.log_path.write_text("\n".join(lines) + "\n",
                                 encoding="utf-8")

    def test_19_synth_basic(self):
        # Three application sources + one linker line that
        # must be ignored (no -c flag).
        self._write_log(
            "make[1]: Entering directory '/src'",
            _good_chibios_cc_line(
                "../../chibios/benchmark_chibios/main.c"),
            _good_chibios_cc_line(
                "../../chibios/benchmark_chibios/"
                "test_ctxsw_irq.c"),
            _good_chibios_cc_line(
                "../../common/dwt_cycle_counter.c"),
            ("arm-none-eabi-gcc -mcpu=cortex-m7 -mthumb "
             "-T link.ld -o build/foo.elf build/foo.o"),
            "make[1]: Leaving directory '/src'",
        )
        proc = _run_synth(self.log_path, self.build_dir,
                          self.workdir)
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")
        cc = json.loads(
            (self.build_dir / "compile_commands.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(len(cc), 3)
        files = sorted(Path(e["file"]).name for e in cc)
        self.assertEqual(files,
                         ["dwt_cycle_counter.c",
                          "main.c",
                          "test_ctxsw_irq.c"])
        # Each entry has a 'directory' field equal to the
        # resolved workdir.
        for e in cc:
            self.assertEqual(
                Path(e["directory"]).resolve(),
                self.workdir.resolve())

    def test_20_synth_strips_leading_at(self):
        # ChibiOS rules.mk prefixes recipes with `@` to silence
        # echo. `make -n` prints the line including the `@`.
        self._write_log(
            "@" + _good_chibios_cc_line(
                "../../chibios/benchmark_chibios/main.c"),
        )
        proc = _run_synth(self.log_path, self.build_dir,
                          self.workdir)
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")
        cc = json.loads(
            (self.build_dir / "compile_commands.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(len(cc), 1)
        # The leading `@` must be stripped from the stored
        # `command` field; otherwise shlex.split inside the
        # auditor would see "@arm-none-eabi-gcc" as the
        # compiler token and miss the GCC invocation.
        self.assertFalse(cc[0]["command"].startswith("@"))
        self.assertTrue(cc[0]["command"].startswith(
            "arm-none-eabi-gcc"))

    def test_21_synth_deduplicates(self):
        # If `make -B -n` somehow prints the same recipe line
        # twice (e.g. due to a phony intermediate target), keep
        # only the first occurrence so the audit object count
        # stays accurate.
        line = _good_chibios_cc_line(
            "../../chibios/benchmark_chibios/main.c")
        self._write_log(line, line, line)
        proc = _run_synth(self.log_path, self.build_dir,
                          self.workdir)
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")
        cc = json.loads(
            (self.build_dir / "compile_commands.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(len(cc), 1)

    def test_22_synth_ignores_link_lines(self):
        # The link step uses arm-none-eabi-gcc too, but without
        # -c. The synth must ignore such lines.
        self._write_log(
            ("arm-none-eabi-gcc -mcpu=cortex-m7 -mthumb "
             "-T link.ld -o build/foo.elf build/foo.o "
             "build/bar.o -lm"),
            ("arm-none-eabi-objcopy -Oihex build/foo.elf "
             "build/foo.hex"),
        )
        proc = _run_synth(self.log_path, self.build_dir,
                          self.workdir)
        # Empty result -> exit 2.
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no `arm-none-eabi-gcc -c", proc.stderr)

    def test_23_synth_handles_dependent_path_flags(self):
        # Flags that consume the next token as a path
        # (-o build/foo.o, -MF .dep/foo.d, -include foo.h)
        # MUST NOT be misidentified as the source file.
        self._write_log(
            ("arm-none-eabi-gcc -mcpu=cortex-m7 -O2 "
             "-I../../common -include preamble.h "
             "-MD -MP -MF build/fair_perf/.dep/foo.d "
             "-c -o build/fair_perf/obj/foo.o "
             "../../chibios/benchmark_chibios/foo.c"),
        )
        proc = _run_synth(self.log_path, self.build_dir,
                          self.workdir)
        self.assertEqual(proc.returncode, 0,
                         f"stderr:\n{proc.stderr}")
        cc = json.loads(
            (self.build_dir / "compile_commands.json")
            .read_text(encoding="utf-8"))
        self.assertEqual(len(cc), 1)
        self.assertEqual(Path(cc[0]["file"]).name, "foo.c")

    def test_24_synth_empty_log_fails(self):
        self._write_log("make[1]: Nothing to be done for 'all'.")
        proc = _run_synth(self.log_path, self.build_dir,
                          self.workdir)
        self.assertNotEqual(proc.returncode, 0)
        self.assertIn("no `arm-none-eabi-gcc -c", proc.stderr)

    def test_25_synth_feeds_audit_chibios(self):
        # End-to-end: synth produces compile_commands.json
        # for the full expected set, then
        # cflags_audit.py --rtos chibios reports PASS.
        app_lines = [_good_chibios_cc_line(
            f"../../chibios/benchmark_chibios/{n}")
            for n in APP_BASENAMES]
        common_lines = [_good_chibios_cc_line(
            f"../../common/{n}")
            for n in COMMON_BASENAMES]
        self._write_log(*(app_lines + common_lines))
        synth = _run_synth(self.log_path, self.build_dir,
                           self.workdir)
        self.assertEqual(synth.returncode, 0,
                         f"synth stderr:\n{synth.stderr}")
        audit = run_audit(self.build_dir, "fair_perf",
                          rtos="chibios")
        self.assertEqual(audit.returncode, 0,
                         f"audit stderr:\n{audit.stderr}")
        self.assertIn("8 ChibiOS application object",
                      audit.stdout)

    def test_26_synth_feeds_audit_chibios_bad_flag(self):
        # End-to-end with a missing required flag: cflags_audit
        # must fail.
        bad_flags = [f for f in GOOD_FLAGS
                     if f != "-fomit-frame-pointer"]
        bad_line = ("arm-none-eabi-gcc "
                    + " ".join(bad_flags) + " "
                    + "-c -o build/main.o "
                    + "../../chibios/benchmark_chibios/main.c")
        self._write_log(bad_line)
        synth = _run_synth(self.log_path, self.build_dir,
                           self.workdir)
        self.assertEqual(synth.returncode, 0,
                         f"synth stderr:\n{synth.stderr}")
        audit = run_audit(self.build_dir, "fair_perf",
                          rtos="chibios")
        self.assertNotEqual(audit.returncode, 0)
        self.assertIn("missing flag -fomit-frame-pointer",
                      audit.stderr)


class LabIntegrationTest(unittest.TestCase):
    """C3-step3: lab scripts integration sanity (static
    text checks against the PowerShell scripts and
    the lab pre-flight NO-GO list)."""

    def test_33_lab_runner_integrates_cflags_audit(self):
        runner = (REPO_ROOT / "scripts" / "lab_runner.py")
        self.assertTrue(runner.is_file(),
                        f"missing runner: {runner}")
        text = runner.read_text(encoding="utf-8")
        self.assertIn("def do_cflags_audit", text)
        self.assertIn("cflags_audit.py", text)
        self.assertIn("--rtos", text)
        # ChibiOS needs an explicit `make compile-commands` first.
        self.assertIn("compile-commands", text)

    def test_34_lab_smoke_dispatches_to_lab_runner(self):
        smoke = (REPO_ROOT / "scripts"
                 / "lab_smoke.ps1").read_text(
                     encoding="utf-8")
        # Codex 2026-05-20-commit-4-ps-thin-wrapper-001:
        # the smoke ps1 is now a thin wrapper around lab_runner.py.
        self.assertIn("lab_runner.py", smoke)
        self.assertIn("smoke", smoke)
        self.assertIn("build-only", smoke)
        self.assertIn("$OnlyBuild", smoke)
        # The audit is now in lab_runner.py; the wrapper must not
        # carry the old helper-call site any more.
        self.assertNotIn("Invoke-CflagsAuditForRtos", smoke)
        self.assertNotIn("run_cflags_audit.ps1", smoke)
        # Codex 2026-05-20-commit-4-applied-code-review-001
        # IMPORTANT 1: the -OnlyBuild branch must always include
        # --clean to preserve the pre-Commit-4 deterministic
        # build-once behaviour (regardless of whether the user
        # also passed -Clean).
        idx_if = smoke.find('if ($OnlyBuild)')
        self.assertGreater(idx_if, 0,
                           "missing $OnlyBuild branch in lab_smoke.ps1")
        idx_else = smoke.find('} else {', idx_if)
        self.assertGreater(idx_else, idx_if,
                           "missing else after $OnlyBuild branch")
        onlybuild_block = smoke[idx_if:idx_else]
        self.assertIn('"build-only"', onlybuild_block)
        self.assertIn('"--clean"', onlybuild_block)

    def test_34b_lab_campaign_dispatches_to_lab_runner(self):
        camp = (REPO_ROOT / "scripts"
                / "lab_campaign.ps1").read_text(
                    encoding="utf-8")
        # Codex 2026-05-20-commit-4-ps-thin-wrapper-001:
        # campaign ps1 is also a thin wrapper around lab_runner.py.
        self.assertIn("lab_runner.py", camp)
        self.assertIn("campaign", camp)
        # Switches propagated through the wrapper.
        self.assertIn("SkipWarmup", camp)
        self.assertIn("SkipReport", camp)
        self.assertIn("OnlyReport", camp)
        # Preserve ValidateSet on -Profile and -Rtoses (matches
        # test_38).
        self.assertIn(
            '[ValidateSet("fair_perf", "realistic_tickless", "debug_dev")]',
            camp)
        self.assertIn(
            '[ValidateSet("chibios", "freertos", "zephyr")]',
            camp)

    def test_38_lab_campaign_validates_profile_and_rtoses(
            self):
        # Codex round 2026-05-14-bucket-c4-...-001
        # IMPORTANT 2 - bind-time validation on
        # lab_campaign.ps1 -Profile and -Rtoses.
        camp = (REPO_ROOT / "scripts"
                / "lab_campaign.ps1").read_text(
                    encoding="utf-8")
        self.assertIn(
            'ValidateSet("fair_perf", "realistic_tickless",',
            camp,
            "lab_campaign.ps1 -Profile must declare a "
            "ValidateSet attribute matching ADR-011")
        self.assertIn(
            'ValidateSet("chibios", "freertos", "zephyr")',
            camp,
            "lab_campaign.ps1 -Rtoses must declare a "
            "ValidateSet attribute")

    def test_35_lab_checklist_no_go_mentions_audit(self):
        # The NO-GO list must reference the cross-RTOS
        # audit failure as an abort trigger.
        ck = (REPO_ROOT / "notes"
              / "lab_checklist.md").read_text(
                  encoding="utf-8")
        # Markdown wraps the script name in backticks; allow
        # either form.
        self.assertTrue(
            "cflags_audit.py` exits non-zero" in ck
            or "cflags_audit.py exits non-zero" in ck,
            "lab_checklist.md NO-GO list must mention "
            "cflags_audit.py audit failure")
        self.assertIn("any RTOS", ck)

    def test_36_lab_checklist_no_stale_zephyr_only_wording(
            self):
        # Codex round 2026-05-14-bucket-c3-step3-001
        # IMPORTANT 1: outside the NO-GO list the checklist
        # must describe the cross-RTOS audit, not a
        # Zephyr-only flow.
        ck = (REPO_ROOT / "notes"
              / "lab_checklist.md").read_text(
                  encoding="utf-8")
        self.assertNotIn(
            "run the Zephyr CFLAGS audit by hand", ck,
            "lab_checklist.md must describe the cross-RTOS "
            "audit, not a Zephyr-only manual step")
        self.assertNotIn(
            "Zephyr CFLAGS audit runs after each build", ck,
            "lab_checklist.md must describe the cross-RTOS "
            "audit, not just the Zephyr branch")
        # The cross-RTOS entry point + flag must be
        # mentioned in the body.
        self.assertIn("cflags_audit.py", ck)
        self.assertIn("--rtos", ck)

    def test_37_adr_009_describes_cross_rtos_audit(self):
        # Codex round 2026-05-14-bucket-c3-step3-001
        # IMPORTANT 2: ADR-009 must describe the cross-RTOS
        # gate, not the Zephyr-only legacy.
        adr = (REPO_ROOT / "notes"
               / "ADR-009-benchmark-config-baseline.md"
               ).read_text(encoding="utf-8")
        self.assertIn(
            "## Enforcement - `scripts/cflags_audit.py`",
            adr,
            "ADR-009 enforcement heading must point at the "
            "cross-RTOS audit script")
        # All three RTOSes must be mentioned in the
        # enforcement narrative.
        for rtos_name in ("ChibiOS", "FreeRTOS", "Zephyr"):
            self.assertIn(rtos_name, adr)
        # The completeness check must be documented.
        self.assertIn("completeness check", adr)


class ChibiosMakefileTargetTest(unittest.TestCase):

    def test_27_makefile_has_compile_commands_target(self):
        mk = (REPO_ROOT / "chibios" / "benchmark_chibios"
              / "Makefile").read_text(encoding="utf-8")
        self.assertIn(".PHONY: compile-commands", mk,
                      "ChibiOS Makefile must declare "
                      "`compile-commands` as a phony target")
        self.assertIn("chibios_synth_compile_commands.py", mk,
                      "ChibiOS Makefile must invoke the synth "
                      "script in the compile-commands recipe")


if __name__ == "__main__":
    unittest.main(verbosity=2)
