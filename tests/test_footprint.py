#!/usr/bin/env python3
"""Validation suite for scripts/footprint.py (ADR-023 scaffold).

Covers (Codex round 2 IMP-3):
  - readelf section header regex on synthetic two- and three-digit
    section indices, empty names, mixed flag strings;
  - Section dataclass property classification (alloc / write / exec
    / in_flash);
  - _is_code_or_rodata / _is_ram_data / _is_ram_bss for the boundary
    cases that drive the metric;
  - end-to-end analyze_elf with subprocess.run mocked, validating
    the .heap exclusion, the per-RTOS extra-stacks add (ChibiOS +
    FreeRTOS), the FreeRTOS tail adjustment, and the missing-tail
    warning path.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import footprint  # noqa: E402


# ----------------------------------------------------------------------
# Regex + dataclass primitives
# ----------------------------------------------------------------------

class TestReadelfRegex(unittest.TestCase):
    """The readelf -S -W output format is the boundary between
    binutils and our metric pipeline. Any change there breaks
    everything downstream silently, hence the tight coverage."""

    def test_typical_progbits_row(self):
        line = ("  [ 1] .text             PROGBITS        "
                "08000300 001300 005294 00  AX  0   0 64")
        m = footprint._READELF_SECTION_RE.match(line)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group("idx")), 1)
        self.assertEqual(m.group("name"), ".text")
        self.assertEqual(m.group("type"), "PROGBITS")
        self.assertEqual(m.group("addr"), "08000300")
        self.assertEqual(m.group("size"), "005294")
        self.assertEqual(m.group("flags"), "AX")

    def test_three_digit_index(self):
        line = ("  [101] noinit            NOBITS          "
                "24035580 00b380 004580 00  WA  0   0 128")
        m = footprint._READELF_SECTION_RE.match(line)
        self.assertIsNotNone(m)
        self.assertEqual(int(m.group("idx")), 101)
        self.assertEqual(m.group("name"), "noinit")

    def test_empty_flags(self):
        # Debug sections often have no flags column populated.
        line = ("  [12] .debug_info       PROGBITS        "
                "00000000 00c5b8 048f1f 00      0   0  1")
        m = footprint._READELF_SECTION_RE.match(line)
        self.assertIsNotNone(m)
        self.assertEqual(m.group("flags"), "")

    def test_section_with_dot_name(self):
        # Zephyr emits ".ARM.exidx" with a dot prefix.
        line = ("  [ 2] .ARM.exidx        PROGBITS        "
                "08009530 009630 000008 00   A  0   0  4")
        m = footprint._READELF_SECTION_RE.match(line)
        self.assertIsNotNone(m)
        self.assertEqual(m.group("name"), ".ARM.exidx")


class TestSectionProperties(unittest.TestCase):
    def test_alloc_write_exec_flags(self):
        s = footprint.Section(1, ".text", "PROGBITS",
                              0x08000300, 0x1000, "AX")
        self.assertTrue(s.is_alloc)
        self.assertFalse(s.is_write)
        self.assertTrue(s.is_exec)

        s2 = footprint.Section(2, ".bss", "NOBITS",
                               0x24000000, 0x1000, "WA")
        self.assertTrue(s2.is_alloc)
        self.assertTrue(s2.is_write)
        self.assertFalse(s2.is_exec)

    def test_in_flash_classification(self):
        # 0x08000000..0x08020000 is the STM32H750 main flash bank.
        s_flash = footprint.Section(1, ".text", "PROGBITS",
                                    0x08000300, 0x1000, "AX")
        s_ram = footprint.Section(2, ".bss", "NOBITS",
                                  0x24000000, 0x1000, "WA")
        s_dtcm = footprint.Section(3, ".dtcm", "NOBITS",
                                   0x20000000, 0x800, "WA")
        s_qspi = footprint.Section(4, ".ext_flash", "PROGBITS",
                                   0x90000000, 0x1000, "A")
        self.assertTrue(s_flash.in_flash)
        self.assertFalse(s_ram.in_flash)
        self.assertFalse(s_dtcm.in_flash)
        self.assertTrue(s_qspi.in_flash)


# ----------------------------------------------------------------------
# Classification helpers
# ----------------------------------------------------------------------

class TestClassification(unittest.TestCase):
    def test_code_or_rodata_requires_progbits_alloc_noW_inflash(self):
        text = footprint.Section(1, ".text", "PROGBITS",
                                 0x08000000, 0x1000, "AX")
        rodata = footprint.Section(2, ".rodata", "PROGBITS",
                                   0x08005000, 0x800, "A")
        data = footprint.Section(3, ".data", "PROGBITS",
                                 0x24000000, 0x100, "WA")
        bss = footprint.Section(4, ".bss", "NOBITS",
                                0x24000100, 0x1000, "WA")
        self.assertTrue(footprint._is_code_or_rodata(text))
        self.assertTrue(footprint._is_code_or_rodata(rodata))
        # .data is writable -> NOT code; it's "ram data".
        self.assertFalse(footprint._is_code_or_rodata(data))
        # .bss is NOBITS -> NOT code.
        self.assertFalse(footprint._is_code_or_rodata(bss))

    def test_ram_data_progbits_aw(self):
        data = footprint.Section(1, ".data", "PROGBITS",
                                 0x24000000, 0x100, "WA")
        text = footprint.Section(2, ".text", "PROGBITS",
                                 0x08000000, 0x1000, "AX")
        self.assertTrue(footprint._is_ram_data(data))
        self.assertFalse(footprint._is_ram_data(text))

    def test_ram_bss_nobits_aw(self):
        bss = footprint.Section(1, ".bss", "NOBITS",
                                0x24000000, 0x1000, "WA")
        heap = footprint.Section(2, ".heap", "NOBITS",
                                 0x24010000, 0x40000, "WA")
        noinit = footprint.Section(3, "noinit", "NOBITS",
                                   0x24050000, 0x4580, "WA")
        text = footprint.Section(4, ".text", "PROGBITS",
                                 0x08000000, 0x1000, "AX")
        self.assertTrue(footprint._is_ram_bss(bss))
        self.assertTrue(footprint._is_ram_bss(heap))
        self.assertTrue(footprint._is_ram_bss(noinit))
        self.assertFalse(footprint._is_ram_bss(text))


# ----------------------------------------------------------------------
# End-to-end analyze_elf with mocked subprocess
# ----------------------------------------------------------------------

class TestAnalyzeElfChibios(unittest.TestCase):
    """Mocks readelf + nm output to verify ChibiOS-specific behaviour:
    .heap exclusion + DTCM stacks added back."""

    READELF_OUT = (
        "Section Headers:\n"
        "  [Nr] Name              Type            Addr     Off    "
        "Size   ES Flg Lk Inf Al\n"
        "  [ 0]                   NULL            00000000 000000 "
        "000000 00      0   0  0\n"
        "  [ 5] .text             PROGBITS        "
        "08000300 001300 005294 00  AX  0   0 64\n"
        "  [ 6] .rodata           PROGBITS        "
        "08005594 006594 000aec 00   A  0   0  4\n"
        "  [ 8] .data             PROGBITS        "
        "24000000 008000 000150 00  WA  0   0  8\n"
        "  [ 9] .bss              NOBITS          "
        "24000150 008150 037110 00  WA  0   0  8\n"
        "  [26] .heap             NOBITS          "
        "24037260 008260 048da0 00  WA  0   0  1\n"
    )

    NM_OUT = (
        "24037260 B __heap_base__\n"
        "24080000 B __heap_end__\n"
        "00000400 A __main_stack_size__\n"
        "00000400 A __process_stack_size__\n"
        "08000000 T Reset_Handler\n"
    )

    def setUp(self):
        # Use a real temp ELF file (analyze_elf checks .exists()).
        self.tmpdir = tempfile.TemporaryDirectory()
        self.elf = Path(self.tmpdir.name) / "benchmark_chibios.elf"
        self.elf.write_bytes(b"\x7fELF")

    def tearDown(self):
        self.tmpdir.cleanup()

    def _mock_subprocess(self, cmd, **kw):
        prog = cmd[0]
        if "readelf" in prog:
            return subprocess.CompletedProcess(
                cmd, 0, stdout=self.READELF_OUT, stderr="")
        if "nm" in prog:
            return subprocess.CompletedProcess(
                cmd, 0, stdout=self.NM_OUT, stderr="")
        raise AssertionError(f"unexpected subprocess: {cmd!r}")

    def test_chibios_heap_excluded_and_dtcm_stacks_added(self):
        with mock.patch("footprint.shutil.which",
                        side_effect=lambda t: f"/usr/bin/{t}"), \
             mock.patch("footprint.subprocess.run",
                        side_effect=self._mock_subprocess):
            rec = footprint.analyze_elf("chibios", "fair_perf", self.elf)
        # Code size: .text (0x5294=21140) + .rodata (0xaec=2796) =
        # 23936. No .vectors in this fixture, by design.
        self.assertEqual(rec.code_size_total, 21140 + 2796)
        # RAM data = .data only.
        self.assertEqual(rec.ram_data, 0x150)
        # RAM bss raw = .bss + .heap.
        self.assertEqual(rec.ram_bss_raw, 0x37110 + 0x48da0)
        # Excluded = .heap.
        self.assertEqual(rec.ram_bss_excluded, 0x48da0)
        self.assertEqual(rec.ram_bss_excluded_section, ".heap")
        # Extra stacks = 1024 + 1024 (DTCM main + process).
        self.assertEqual(rec.ram_extra_stacks, 0x800)
        self.assertEqual(len(rec.ram_extra_stacks_breakdown), 2)
        # Static RAM used = data + bss - heap + extra.
        expected = 0x150 + (0x37110 + 0x48da0) - 0x48da0 + 0x800
        self.assertEqual(rec.ram_static_used, expected)
        # Tail = __heap_end__ - __heap_base__ = 0x48da0.
        self.assertEqual(rec.tail_reservation_size, 0x48da0)
        self.assertEqual(rec.tail_reservation_basis,
                         "__heap_end__ - __heap_base__")


class TestAnalyzeElfFreertosTailAdjustment(unittest.TestCase):
    READELF_OUT = (
        "Section Headers:\n"
        "  [Nr] Name              Type            Addr     Off    "
        "Size   ES Flg Lk Inf Al\n"
        "  [ 0]                   NULL            00000000 000000 "
        "000000 00      0   0  0\n"
        "  [ 1] .text             PROGBITS        "
        "080002a0 0012a0 006ee8 00  AX  0   0  4\n"
        "  [ 8] .data             PROGBITS        "
        "24000000 009000 000018 00  WA  0   0  4\n"
        "  [ 9] .bss              NOBITS          "
        "24000018 009018 03b750 00  WA  0   0  8\n"
    )

    NM_OUT = (
        "24080000 R _estack\n"
        "2403b768 B __bss_end__\n"
        "00001000 A _Min_Stack_Size\n"
    )

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.elf = Path(self.tmpdir.name) / "benchmark_freertos.elf"
        self.elf.write_bytes(b"\x7fELF")

    def tearDown(self):
        self.tmpdir.cleanup()

    def _mock(self, cmd, **kw):
        if "readelf" in cmd[0]:
            return subprocess.CompletedProcess(
                cmd, 0, stdout=self.READELF_OUT, stderr="")
        return subprocess.CompletedProcess(
            cmd, 0, stdout=self.NM_OUT, stderr="")

    def test_freertos_extra_stack_added_tail_subtracted(self):
        with mock.patch("footprint.shutil.which",
                        side_effect=lambda t: f"/usr/bin/{t}"), \
             mock.patch("footprint.subprocess.run",
                        side_effect=self._mock):
            rec = footprint.analyze_elf("freertos", "fair_perf", self.elf)
        # No .heap excluded.
        self.assertEqual(rec.ram_bss_excluded, 0)
        # Extra stacks = 4096.
        self.assertEqual(rec.ram_extra_stacks, 0x1000)
        # Tail = _estack - __bss_end__ - _Min_Stack_Size
        #      = 0x24080000 - 0x2403b768 - 0x1000.
        raw_tail = 0x24080000 - 0x2403b768
        self.assertEqual(rec.tail_reservation_size, raw_tail - 0x1000)
        self.assertIn("_Min_Stack_Size",
                      rec.tail_reservation_basis or "")


class TestAnalyzeElfZephyrNoExtraStacks(unittest.TestCase):
    READELF_OUT = (
        "Section Headers:\n"
        "  [Nr] Name              Type            Addr     Off    "
        "Size   ES Flg Lk Inf Al\n"
        "  [ 0]                   NULL            00000000 000000 "
        "000000 00      0   0  0\n"
        "  [ 1] text              PROGBITS        "
        "08000240 000340 0092f0 00  AX  0   0 64\n"
        "  [26] bss               NOBITS          "
        "24000080 00b380 035499 00  WA  0   0  8\n"
        "  [27] noinit            NOBITS          "
        "24035580 00b380 004580 00  WA  0   0 128\n"
    )

    NM_OUT = (
        "24039b00 B _end\n"
        "24080000 A __kernel_ram_end\n"
    )

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.elf = Path(self.tmpdir.name) / "zephyr.elf"
        self.elf.write_bytes(b"\x7fELF")

    def tearDown(self):
        self.tmpdir.cleanup()

    def _mock(self, cmd, **kw):
        if "readelf" in cmd[0]:
            return subprocess.CompletedProcess(
                cmd, 0, stdout=self.READELF_OUT, stderr="")
        return subprocess.CompletedProcess(
            cmd, 0, stdout=self.NM_OUT, stderr="")

    def test_zephyr_noinit_counted_no_extra_stacks(self):
        with mock.patch("footprint.shutil.which",
                        side_effect=lambda t: f"/usr/bin/{t}"), \
             mock.patch("footprint.subprocess.run",
                        side_effect=self._mock):
            rec = footprint.analyze_elf("zephyr", "fair_perf", self.elf)
        # No extra stacks.
        self.assertEqual(rec.ram_extra_stacks, 0)
        self.assertEqual(rec.ram_extra_stacks_breakdown, [])
        # bss + noinit = 0x35499 + 0x4580.
        self.assertEqual(rec.ram_bss_raw, 0x35499 + 0x4580)
        # Tail = __kernel_ram_end - _end.
        self.assertEqual(rec.tail_reservation_size,
                         0x24080000 - 0x24039b00)


class TestAnalyzeElfMissingTailSymbol(unittest.TestCase):
    """If the configured tail symbols are absent, tail must be
    None (not crash; not silently invent a value)."""

    READELF_OUT = (
        "Section Headers:\n"
        "  [Nr] Name              Type            Addr     Off    "
        "Size   ES Flg Lk Inf Al\n"
        "  [ 0]                   NULL            00000000 000000 "
        "000000 00      0   0  0\n"
        "  [ 1] .text             PROGBITS        "
        "08000000 000300 001000 00  AX  0   0  4\n"
    )
    NM_OUT = "08000000 T Reset_Handler\n"  # no heap symbols!

    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.elf = Path(self.tmpdir.name) / "stub.elf"
        self.elf.write_bytes(b"\x7fELF")

    def tearDown(self):
        self.tmpdir.cleanup()

    def _mock(self, cmd, **kw):
        if "readelf" in cmd[0]:
            return subprocess.CompletedProcess(
                cmd, 0, stdout=self.READELF_OUT, stderr="")
        return subprocess.CompletedProcess(
            cmd, 0, stdout=self.NM_OUT, stderr="")

    def test_missing_tail_symbols_returns_none(self):
        with mock.patch("footprint.shutil.which",
                        side_effect=lambda t: f"/usr/bin/{t}"), \
             mock.patch("footprint.subprocess.run",
                        side_effect=self._mock):
            rec = footprint.analyze_elf("chibios", "fair_perf", self.elf)
        self.assertIsNone(rec.tail_reservation_size)


if __name__ == "__main__":
    unittest.main()
