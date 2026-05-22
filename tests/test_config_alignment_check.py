#!/usr/bin/env python3
"""Validation suite for scripts/config_alignment_check.py (ADR-022
gate scaffold).

Covers (Codex round 2 IMP-4):
  - _normalize_c_value across the variants the project actually
    uses: `TRUE`, `FALSE`, `( 1 )`, `( ( uint16_t ) 256 )`,
    integer-suffix `1U`, hex `0x1`, trailing inline comment,
    multi-paren nesting;
  - parse_c_defines (last-wins via re-#define);
  - parse_zephyr_conf with inline `#` comments + quoted strings;
  - _eq numeric comparison across bases;
  - Zephyr last-wins merge: profile conf overrides prj.conf;
  - end-to-end check_zephyr() catching a profile-override
    regression that the per-file parser would have missed;
  - FailureBag accumulation: every drift reported, not just the
    first.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

import config_alignment_check as cac  # noqa: E402


# ----------------------------------------------------------------------
# Value normalization
# ----------------------------------------------------------------------

class TestNormalizeCValue(unittest.TestCase):
    def test_bare_token(self):
        self.assertEqual(cac._normalize_c_value("TRUE"), "TRUE")
        self.assertEqual(cac._normalize_c_value("FALSE"), "FALSE")
        self.assertEqual(cac._normalize_c_value("1000"), "1000")

    def test_simple_parentheses(self):
        self.assertEqual(cac._normalize_c_value("( 1 )"), "1")
        self.assertEqual(cac._normalize_c_value("( 16 )"), "16")
        self.assertEqual(cac._normalize_c_value("(0)"), "0")

    def test_nested_parentheses(self):
        self.assertEqual(cac._normalize_c_value("(( 8 ))"), "8")

    def test_typecast(self):
        self.assertEqual(
            cac._normalize_c_value("( ( uint16_t ) 256 )"),
            "256",
        )
        self.assertEqual(
            cac._normalize_c_value("( ( TickType_t ) 1000 )"),
            "1000",
        )
        self.assertEqual(
            cac._normalize_c_value("( ( size_t ) ( 1 * 1024 ) )"),
            "1 * 1024",
        )

    def test_trailing_block_comment(self):
        self.assertEqual(
            cac._normalize_c_value("1   /* ADR-009 baseline */"),
            "1",
        )

    def test_trailing_line_comment(self):
        self.assertEqual(
            cac._normalize_c_value("FALSE  // dead code"),
            "FALSE",
        )

    def test_unbalanced_parens_left_alone(self):
        # Better to fail noisily downstream than to corrupt the
        # token silently.
        s = cac._normalize_c_value("( foo + bar")
        self.assertIn("foo", s)


class TestEqNumeric(unittest.TestCase):
    def test_string_equality(self):
        self.assertTrue(cac._eq("TRUE", "TRUE"))
        self.assertFalse(cac._eq("TRUE", "FALSE"))

    def test_integer_decimal_vs_string(self):
        self.assertTrue(cac._eq("1", "1"))
        self.assertTrue(cac._eq(" 1 ", " 1 "))

    def test_integer_hex_vs_decimal(self):
        self.assertTrue(cac._eq("0x10", "16"))
        self.assertTrue(cac._eq("0X1000", "4096"))

    def test_integer_zero_forms(self):
        self.assertTrue(cac._eq("0", "0x0"))
        self.assertTrue(cac._eq("0x0", "0"))


# ----------------------------------------------------------------------
# C define parser (last-wins)
# ----------------------------------------------------------------------

class TestParseCDefines(unittest.TestCase):
    def test_last_wins_redefinition(self):
        text = (
            "#define FOO 1\n"
            "#define BAR 2\n"
            "#define FOO 3\n"  # last wins
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".h", delete=False, encoding="utf-8",
        ) as f:
            f.write(text)
            p = Path(f.name)
        try:
            defs = cac.parse_c_defines(p)
            self.assertEqual(defs["FOO"], "3")
            self.assertEqual(defs["BAR"], "2")
        finally:
            p.unlink()

    def test_typical_chconf_layout(self):
        text = (
            "/**\n * Doxygen block.\n */\n"
            "#if !defined(CH_CFG_USE_MUTEXES)\n"
            "#define CH_CFG_USE_MUTEXES                  TRUE\n"
            "#endif\n"
            "\n"
            "#if !defined(CH_CFG_TIME_QUANTUM)\n"
            "#define CH_CFG_TIME_QUANTUM                 0\n"
            "#endif\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".h", delete=False, encoding="utf-8",
        ) as f:
            f.write(text)
            p = Path(f.name)
        try:
            defs = cac.parse_c_defines(p)
            self.assertEqual(defs["CH_CFG_USE_MUTEXES"], "TRUE")
            self.assertEqual(defs["CH_CFG_TIME_QUANTUM"], "0")
        finally:
            p.unlink()

    def test_typecast_normalized(self):
        text = (
            "#define configMINIMAL_STACK_SIZE   ( ( uint16_t ) 256 )\n"
            "#define configTICK_RATE_HZ         "
            "( ( TickType_t ) 1000 )\n"
        )
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".h", delete=False, encoding="utf-8",
        ) as f:
            f.write(text)
            p = Path(f.name)
        try:
            defs = cac.parse_c_defines(p)
            self.assertEqual(defs["configMINIMAL_STACK_SIZE"], "256")
            self.assertEqual(defs["configTICK_RATE_HZ"], "1000")
        finally:
            p.unlink()


# ----------------------------------------------------------------------
# Zephyr Kconfig parser
# ----------------------------------------------------------------------

class TestParseZephyrConf(unittest.TestCase):
    def _write(self, body: str) -> Path:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".conf", delete=False, encoding="utf-8",
        ) as f:
            f.write(body)
            return Path(f.name)

    def test_inline_comment_stripped(self):
        p = self._write(
            "CONFIG_LOG=n  # ADR-009 hard rule\n"
            "CONFIG_SYS_CLOCK_TICKS_PER_SEC=1000\n"
        )
        try:
            defs = cac.parse_zephyr_conf(p)
            self.assertEqual(defs["CONFIG_LOG"], "n")
            self.assertEqual(defs["CONFIG_SYS_CLOCK_TICKS_PER_SEC"],
                             "1000")
        finally:
            p.unlink()

    def test_quoted_string_stripped(self):
        p = self._write('CONFIG_BOARD="stm32h750b_dk"\n')
        try:
            defs = cac.parse_zephyr_conf(p)
            self.assertEqual(defs["CONFIG_BOARD"], "stm32h750b_dk")
        finally:
            p.unlink()

    def test_comment_lines_skipped(self):
        p = self._write(
            "# This is a comment line\n"
            "CONFIG_FOO=y\n"
            "\n"
        )
        try:
            defs = cac.parse_zephyr_conf(p)
            self.assertEqual(defs["CONFIG_FOO"], "y")
            self.assertNotIn("# This is a comment line", defs)
        finally:
            p.unlink()


# ----------------------------------------------------------------------
# Zephyr last-wins merge: the bug Codex round 2 IMP-2 surfaced
# ----------------------------------------------------------------------

class TestZephyrLastWinsMerge(unittest.TestCase):
    """Verify that a profile-conf override is caught even if
    prj.conf is contractually correct, and vice versa."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "zephyr" / "benchmark_zephyr" / "conf").mkdir(
            parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, rel: str, body: str) -> None:
        (self.root / rel).write_text(body, encoding="utf-8")

    def _all_contract_pass(self, profile: str) -> str:
        """Body for a prj.conf that satisfies every ZEPHYR_PRJ_CONTRACT
        entry (and writes the right profile-conf body too)."""
        prj_lines = [
            f"{name}={value}"
            for name, value in cac.ZEPHYR_PRJ_CONTRACT.items()
        ]
        return "\n".join(prj_lines) + "\n"

    def _all_profile_pass(self, profile: str) -> str:
        prof_lines = [
            f"{name}={value}"
            for name, value
            in cac.ZEPHYR_PROFILE_CONTRACT[profile].items()
        ]
        return "\n".join(prof_lines) + "\n"

    def test_profile_override_regresses_heap_pool(self):
        # prj.conf is correct; profile conf REGRESSES heap pool to 8192.
        self._write("zephyr/benchmark_zephyr/prj.conf",
                    self._all_contract_pass("fair_perf"))
        bad_profile = (self._all_profile_pass("fair_perf")
                       + "CONFIG_HEAP_MEM_POOL_SIZE=8192\n")
        self._write("zephyr/benchmark_zephyr/conf/fair_perf.conf",
                    bad_profile)
        bag = cac.FailureBag()
        cac.check_zephyr(self.root, "fair_perf", bag)
        # The override must be caught.
        heap_drift = [m for m in bag.failures
                      if "CONFIG_HEAP_MEM_POOL_SIZE" in m
                      and "8192" in m]
        self.assertTrue(
            heap_drift,
            f"expected HEAP_MEM_POOL_SIZE drift, got: {bag.failures}",
        )
        # And the diagnostic must point at the profile conf as the
        # last-wins source.
        self.assertTrue(any("fair_perf.conf" in m
                             for m in heap_drift),
                         f"failures: {heap_drift}")

    def test_clean_tree_passes(self):
        self._write("zephyr/benchmark_zephyr/prj.conf",
                    self._all_contract_pass("fair_perf"))
        self._write("zephyr/benchmark_zephyr/conf/fair_perf.conf",
                    self._all_profile_pass("fair_perf"))
        bag = cac.FailureBag()
        cac.check_zephyr(self.root, "fair_perf", bag)
        self.assertEqual(
            bag.failures, [],
            f"expected zero failures, got: {bag.failures}",
        )


# ----------------------------------------------------------------------
# Codex round 4 BLOCKER: source-only must NOT inspect generated .config
# (chicken-and-egg with a stale .config blocking the corrective rebuild)
# ----------------------------------------------------------------------

class TestZephyrDotConfigPhase(unittest.TestCase):
    """Verify the two-phase gate semantics on the Zephyr .config
    branch added in round 3 IMP-1. The BLOCKER scenario:
    source fragments are correct but the generated .config is
    stale (e.g. missing CONFIG_PM=y for realistic_tickless because
    a previous build used different Kconfig defaults). The
    source-only phase MUST ignore .config; the full phase MUST
    catch the drift; the --rtos freertos / chibios paths in full
    mode MUST skip the Zephyr .config scan entirely."""

    PROFILE = "realistic_tickless"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        # Source fragments: all correct.
        (self.root / "zephyr" / "benchmark_zephyr" / "conf").mkdir(
            parents=True)
        prj_body = "\n".join(
            f"{k}={v}" for k, v in cac.ZEPHYR_PRJ_CONTRACT.items()
        ) + "\n"
        prof_body = "\n".join(
            f"{k}={v}" for k, v
            in cac.ZEPHYR_PROFILE_CONTRACT[self.PROFILE].items()
        ) + "\n"
        (self.root / "zephyr" / "benchmark_zephyr" / "prj.conf"
         ).write_text(prj_body, encoding="utf-8")
        (self.root / "zephyr" / "benchmark_zephyr" / "conf"
         / f"{self.PROFILE}.conf"
         ).write_text(prof_body, encoding="utf-8")
        # Generated .config: STALE. The source declares
        # CONFIG_TICKLESS_KERNEL=y for realistic_tickless but the
        # .config omits it (simulating a Kconfig default that did
        # not propagate from prj.conf, analogous to the original
        # round-4 CONFIG_PM scenario after ADR-024 removed PM from
        # the contract).
        dot_config_dir = (self.root / "zephyr" / "build"
                          / self.PROFILE / "zephyr")
        dot_config_dir.mkdir(parents=True)
        stale_body = "\n".join(
            f"{k}={v}"
            for k, v in cac.ZEPHYR_PRJ_CONTRACT.items()
        ) + "\n"
        # Include profile contract values EXCEPT
        # CONFIG_TICKLESS_KERNEL (drift indicator).
        for k, v in cac.ZEPHYR_PROFILE_CONTRACT[self.PROFILE].items():
            if k != "CONFIG_TICKLESS_KERNEL":
                stale_body += f"{k}={v}\n"
        (dot_config_dir / ".config").write_text(stale_body,
                                                encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_source_only_ignores_stale_dot_config(self):
        """The BLOCKER from Codex round 4: source-only mode MUST
        NOT read the generated .config so a stale build cannot
        block the rebuild that would refresh it."""
        bag = cac.FailureBag()
        cac.check_zephyr(self.root, self.PROFILE, bag,
                         source_only=True)
        self.assertEqual(
            bag.failures, [],
            f"source-only must ignore .config; got: {bag.failures}",
        )

    def test_full_mode_catches_dot_config_drift(self):
        """Full mode MUST catch the missing CONFIG_TICKLESS_KERNEL=y
        entry in the stale .config. This is the legitimate build-
        layer failure that source-only had to mask."""
        bag = cac.FailureBag()
        cac.check_zephyr(self.root, self.PROFILE, bag,
                         source_only=False,
                         build_layer_rtos="all")
        drift_failures = [m for m in bag.failures
                          if "CONFIG_TICKLESS_KERNEL" in m
                          and ".config" in m]
        self.assertTrue(
            drift_failures,
            f"full mode must catch CONFIG_TICKLESS_KERNEL drift; "
            f"got: {bag.failures}",
        )

    def test_full_mode_rtos_freertos_skips_zephyr_dot_config(self):
        """When the operator runs `--rtos freertos` (e.g. via
        `lab_runner.py build-only --rtos freertos`), the post-
        build full check must NOT inspect the Zephyr .config: a
        stale Zephyr build artefact must not fail a single-RTOS
        FreeRTOS flow."""
        bag = cac.FailureBag()
        cac.check_zephyr(self.root, self.PROFILE, bag,
                         source_only=False,
                         build_layer_rtos="freertos")
        zephyr_dot_config_failures = [m for m in bag.failures
                                       if ".config" in m]
        self.assertEqual(
            zephyr_dot_config_failures, [],
            f"--rtos freertos must skip Zephyr .config; "
            f"got: {bag.failures}",
        )

    def test_full_mode_rtos_zephyr_does_check_dot_config(self):
        """`--rtos zephyr` full mode is the explicit Zephyr-only
        check; it MUST inspect the generated .config and catch
        the drift."""
        bag = cac.FailureBag()
        cac.check_zephyr(self.root, self.PROFILE, bag,
                         source_only=False,
                         build_layer_rtos="zephyr")
        drift_failures = [m for m in bag.failures
                          if "CONFIG_TICKLESS_KERNEL" in m
                          and ".config" in m]
        self.assertTrue(
            drift_failures,
            f"--rtos zephyr must catch CONFIG_TICKLESS_KERNEL drift; "
            f"got: {bag.failures}",
        )


# ----------------------------------------------------------------------
# Codex round 4 MIN-2: synthetic .config fixture with the full
# correct profile contract -- positive case to complement the
# BLOCKER's negative cases above.
# ----------------------------------------------------------------------

class TestZephyrDotConfigCorrect(unittest.TestCase):
    """When the generated .config matches every contracted symbol
    (both the base PRJ_CONTRACT and the per-profile
    PROFILE_CONTRACT), full mode must pass."""

    PROFILE = "realistic_tickless"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "zephyr" / "benchmark_zephyr" / "conf").mkdir(
            parents=True)
        prj_body = "\n".join(
            f"{k}={v}" for k, v in cac.ZEPHYR_PRJ_CONTRACT.items()
        ) + "\n"
        prof_body = "\n".join(
            f"{k}={v}" for k, v
            in cac.ZEPHYR_PROFILE_CONTRACT[self.PROFILE].items()
        ) + "\n"
        (self.root / "zephyr" / "benchmark_zephyr" / "prj.conf"
         ).write_text(prj_body, encoding="utf-8")
        (self.root / "zephyr" / "benchmark_zephyr" / "conf"
         / f"{self.PROFILE}.conf"
         ).write_text(prof_body, encoding="utf-8")
        # Generated .config: every contract symbol present with the
        # contracted value. This is what a fresh, in-sync Zephyr
        # build produces.
        dot_config_dir = (self.root / "zephyr" / "build"
                          / self.PROFILE / "zephyr")
        dot_config_dir.mkdir(parents=True)
        clean_body = prj_body + prof_body
        (dot_config_dir / ".config").write_text(clean_body,
                                                encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_full_mode_clean_dot_config_passes(self):
        bag = cac.FailureBag()
        cac.check_zephyr(self.root, self.PROFILE, bag,
                         source_only=False,
                         build_layer_rtos="all")
        self.assertEqual(
            bag.failures, [],
            f"clean .config must pass full mode; got: {bag.failures}",
        )


# ----------------------------------------------------------------------
# Codex round 7 IMP-1: negative contract for realistic_tickless
# ARM_ON_ENTER_CPU_IDLE_HOOK. A future Kconfig regression that selects
# the hook for realistic_tickless would suppress WFI and violate
# ADR-024. The build-layer scan MUST catch that drift.
# ----------------------------------------------------------------------

class TestZephyrRealisticTicklessNegativeHookContract(unittest.TestCase):
    PROFILE = "realistic_tickless"

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "zephyr" / "benchmark_zephyr" / "conf").mkdir(
            parents=True)
        prj_body = "\n".join(
            f"{k}={v}" for k, v in cac.ZEPHYR_PRJ_CONTRACT.items()
        ) + "\n"
        prof_body = "\n".join(
            f"{k}={v}" for k, v
            in cac.ZEPHYR_PROFILE_CONTRACT[self.PROFILE].items()
        ) + "\n"
        (self.root / "zephyr" / "benchmark_zephyr" / "prj.conf"
         ).write_text(prj_body, encoding="utf-8")
        (self.root / "zephyr" / "benchmark_zephyr" / "conf"
         / f"{self.PROFILE}.conf"
         ).write_text(prof_body, encoding="utf-8")
        self.dot_config_dir = (self.root / "zephyr" / "build"
                                / self.PROFILE / "zephyr")
        self.dot_config_dir.mkdir(parents=True)

    def tearDown(self):
        self.tmp.cleanup()

    def _write_config(self, extra_lines: list[str]) -> None:
        body = "\n".join(
            f"{k}={v}" for k, v in cac.ZEPHYR_PRJ_CONTRACT.items()
        ) + "\n"
        body += "\n".join(
            f"{k}={v}" for k, v
            in cac.ZEPHYR_PROFILE_CONTRACT[self.PROFILE].items()
        ) + "\n"
        body += "\n".join(extra_lines) + "\n"
        (self.dot_config_dir / ".config").write_text(body,
                                                     encoding="utf-8")

    def test_hook_y_in_realistic_tickless_dot_config_fails(self):
        """A regressed .config that selects the hook for
        realistic_tickless MUST be flagged: it would suppress
        WFI in the profile that requires WFI per ADR-024."""
        self._write_config([
            "CONFIG_ARM_ON_ENTER_CPU_IDLE_HOOK=y",
        ])
        bag = cac.FailureBag()
        cac.check_zephyr(self.root, self.PROFILE, bag,
                         source_only=False,
                         build_layer_rtos="all")
        hook_failures = [m for m in bag.failures
                         if "CONFIG_ARM_ON_ENTER_CPU_IDLE_HOOK" in m
                         and "expected 'n'" in m]
        self.assertTrue(
            hook_failures,
            f"realistic_tickless .config with hook=y must fail; "
            f"got: {bag.failures}",
        )

    def test_hook_absent_in_realistic_tickless_dot_config_passes(self):
        """The legitimate case: the hook symbol is absent from
        .config because the project Kconfig did NOT select it for
        realistic_tickless. Tolerated by the `n`-default logic."""
        self._write_config([])  # no hook entry at all
        bag = cac.FailureBag()
        cac.check_zephyr(self.root, self.PROFILE, bag,
                         source_only=False,
                         build_layer_rtos="all")
        hook_failures = [m for m in bag.failures
                         if "CONFIG_ARM_ON_ENTER_CPU_IDLE_HOOK" in m]
        self.assertEqual(
            hook_failures, [],
            f"absent hook entry must pass `n` tolerance; "
            f"got: {bag.failures}",
        )


# ----------------------------------------------------------------------
# ADR-024: ChibiOS CORTEX_ENABLE_WFI_IDLE profile-conditional check
# ----------------------------------------------------------------------

class TestChibiosWfiProfileConditional(unittest.TestCase):
    """Verify _extract_chibios_profile_conditional() parses the
    canonical ADR-024 pattern correctly and that check_chibios
    applies the profile contract per-profile."""

    CANONICAL_BLOCK = (
        "#if !defined(CORTEX_ENABLE_WFI_IDLE)\n"
        "#if defined(BENCH_PROFILE_REALISTIC_TICKLESS)\n"
        "#define CORTEX_ENABLE_WFI_IDLE              TRUE\n"
        "#else\n"
        "#define CORTEX_ENABLE_WFI_IDLE              FALSE\n"
        "#endif\n"
        "#endif\n"
    )

    def test_extract_returns_true_for_realistic_tickless(self):
        v = cac._extract_chibios_profile_conditional(
            self.CANONICAL_BLOCK, "CORTEX_ENABLE_WFI_IDLE",
            "realistic_tickless",
        )
        self.assertEqual(v, "TRUE")

    def test_extract_returns_false_for_fair_perf(self):
        v = cac._extract_chibios_profile_conditional(
            self.CANONICAL_BLOCK, "CORTEX_ENABLE_WFI_IDLE",
            "fair_perf",
        )
        self.assertEqual(v, "FALSE")

    def test_extract_returns_false_for_debug_dev(self):
        v = cac._extract_chibios_profile_conditional(
            self.CANONICAL_BLOCK, "CORTEX_ENABLE_WFI_IDLE",
            "debug_dev",
        )
        self.assertEqual(v, "FALSE")

    def test_extract_returns_none_when_pattern_absent(self):
        text = "#define CORTEX_ENABLE_WFI_IDLE TRUE\n"  # unconditional
        v = cac._extract_chibios_profile_conditional(
            text, "CORTEX_ENABLE_WFI_IDLE", "realistic_tickless",
        )
        self.assertIsNone(v)


class TestCheckChibiosWfiContractEnforced(unittest.TestCase):
    """End-to-end: synthesise a minimal chconf.h, drive
    check_chibios with each profile, assert the WFI contract is
    enforced."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        cfg = (self.root / "chibios" / "benchmark_chibios" / "cfg")
        cfg.mkdir(parents=True)
        self.chconf = cfg / "chconf.h"

    def tearDown(self):
        self.tmp.cleanup()

    def _write(self, profile_conditional_value_pair):
        """Write a minimal chconf.h with the ADR-022 + ADR-024
        contract. `profile_conditional_value_pair` is
        (value_for_realistic_tickless, value_for_default)."""
        v_tickless, v_default = profile_conditional_value_pair
        body = "".join(
            f"#define {k} {v}\n"
            for k, v in cac.CHIBIOS_CHCONF_CONTRACT.items()
        )
        body += (
            "#if !defined(CORTEX_ENABLE_WFI_IDLE)\n"
            "#if defined(BENCH_PROFILE_REALISTIC_TICKLESS)\n"
            f"#define CORTEX_ENABLE_WFI_IDLE              {v_tickless}\n"
            "#else\n"
            f"#define CORTEX_ENABLE_WFI_IDLE              {v_default}\n"
            "#endif\n"
            "#endif\n"
        )
        self.chconf.write_text(body, encoding="utf-8")

    def test_canonical_realistic_tickless_passes(self):
        self._write(("TRUE", "FALSE"))
        bag = cac.FailureBag()
        cac.check_chibios(self.root, bag, profile="realistic_tickless")
        self.assertEqual(
            bag.failures, [],
            f"expected zero failures, got: {bag.failures}",
        )

    def test_canonical_fair_perf_passes(self):
        self._write(("TRUE", "FALSE"))
        bag = cac.FailureBag()
        cac.check_chibios(self.root, bag, profile="fair_perf")
        self.assertEqual(
            bag.failures, [],
            f"expected zero failures, got: {bag.failures}",
        )

    def test_swapped_polarity_fails_for_realistic_tickless(self):
        # Wrong polarity: realistic_tickless branch says FALSE.
        self._write(("FALSE", "TRUE"))
        bag = cac.FailureBag()
        cac.check_chibios(self.root, bag, profile="realistic_tickless")
        wfi_failures = [m for m in bag.failures
                        if "CORTEX_ENABLE_WFI_IDLE" in m
                        and "expected 'TRUE'" in m]
        self.assertTrue(
            wfi_failures,
            f"swapped polarity must fail realistic_tickless; "
            f"got: {bag.failures}",
        )

    def test_swapped_polarity_fails_for_fair_perf(self):
        self._write(("FALSE", "TRUE"))
        bag = cac.FailureBag()
        cac.check_chibios(self.root, bag, profile="fair_perf")
        wfi_failures = [m for m in bag.failures
                        if "CORTEX_ENABLE_WFI_IDLE" in m
                        and "expected 'FALSE'" in m]
        self.assertTrue(
            wfi_failures,
            f"swapped polarity must fail fair_perf; "
            f"got: {bag.failures}",
        )


# ----------------------------------------------------------------------
# FailureBag accumulation
# ----------------------------------------------------------------------

class TestFailureBag(unittest.TestCase):
    def test_collects_every_failure(self):
        bag = cac.FailureBag()
        bag.add("first")
        bag.add("second")
        bag.add("third")
        self.assertEqual(bag.failures, ["first", "second", "third"])
        self.assertFalse(bag.ok())

    def test_ok_on_empty(self):
        bag = cac.FailureBag()
        self.assertTrue(bag.ok())


# ----------------------------------------------------------------------
# Build-layer ChibiOS ELF symbol check (Codex round 3 IMP-3)
# ----------------------------------------------------------------------

class TestCheckChibiosElfSymbols(unittest.TestCase):
    """Covers the ADR-022 build-layer scan. The ChibiOS ELF is the
    only artefact with a forbidden/required symbol contract; this
    suite mocks `_elf_symbols` to drive the four boundary cases."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        bd = (self.root / "chibios" / "benchmark_chibios"
              / "build" / "fair_perf")
        bd.mkdir(parents=True)
        # Build-layer only runs if the ELF file exists on disk.
        self.elf = bd / "benchmark_chibios.elf"
        self.elf.write_bytes(b"\x7fELF")

    def tearDown(self):
        self.tmp.cleanup()

    def _all_clean_syms(self):
        """Required-only symbol set; nothing forbidden."""
        return list(cac.CHIBIOS_ELF_REQUIRED_SYMBOLS) + [
            "Reset_Handler", "main", "SystemInit",
        ]

    def test_clean_elf_no_failures(self):
        from unittest import mock
        with mock.patch(
            "config_alignment_check._elf_symbols",
            return_value=self._all_clean_syms(),
        ):
            bag = cac.FailureBag()
            cac.check_chibios_elf_symbols(self.root, "fair_perf", bag)
        self.assertEqual(
            bag.failures, [],
            f"expected zero failures, got: {bag.failures}",
        )

    def test_missing_required_symbol_fails(self):
        from unittest import mock
        # Drop chMtxLock specifically.
        syms = [s for s in self._all_clean_syms() if s != "chMtxLock"]
        with mock.patch(
            "config_alignment_check._elf_symbols", return_value=syms,
        ):
            bag = cac.FailureBag()
            cac.check_chibios_elf_symbols(self.root, "fair_perf", bag)
        self.assertTrue(any("chMtxLock" in m and "NOT present" in m
                            for m in bag.failures),
                        f"failures: {bag.failures}")

    def test_forbidden_symbol_present_fails(self):
        from unittest import mock
        syms = self._all_clean_syms() + ["chFactoryInit",
                                          "chFactoryCreateBuffer"]
        with mock.patch(
            "config_alignment_check._elf_symbols", return_value=syms,
        ):
            bag = cac.FailureBag()
            cac.check_chibios_elf_symbols(self.root, "fair_perf", bag)
        self.assertTrue(
            any("forbidden ELF symbol" in m and "chFactory" in m
                for m in bag.failures),
            f"failures: {bag.failures}",
        )

    def test_nm_missing_warns_no_failure(self):
        """When nm is not on PATH, the check downgrades to a printed
        warning (does NOT add a FailureBag entry). This keeps source-
        only audits usable in CI before the toolchain bootstrap."""
        from unittest import mock
        with mock.patch(
            "config_alignment_check._elf_symbols", return_value=None,
        ):
            bag = cac.FailureBag()
            cac.check_chibios_elf_symbols(self.root, "fair_perf", bag)
        self.assertEqual(
            bag.failures, [],
            f"nm-missing should warn, not fail; got: {bag.failures}",
        )


# ----------------------------------------------------------------------
# Codex round 3 IMP-4: integer suffix support in _normalize_c_value
# ----------------------------------------------------------------------

class TestNormalizeIntegerSuffix(unittest.TestCase):
    def test_u_suffix_stripped(self):
        self.assertEqual(cac._normalize_c_value("1U"), "1")
        self.assertEqual(cac._normalize_c_value("16u"), "16")

    def test_ul_ull_l_ll_stripped(self):
        self.assertEqual(cac._normalize_c_value("1UL"), "1")
        self.assertEqual(cac._normalize_c_value("1ULL"), "1")
        self.assertEqual(cac._normalize_c_value("1L"), "1")
        self.assertEqual(cac._normalize_c_value("1LL"), "1")
        self.assertEqual(cac._normalize_c_value("1ul"), "1")
        self.assertEqual(cac._normalize_c_value("1uLl"), "1")

    def test_hex_with_suffix(self):
        self.assertEqual(cac._normalize_c_value("0x10U"), "0x10")
        self.assertEqual(cac._normalize_c_value("0xFFUL"), "0xFF")

    def test_suffix_inside_typecast_paren(self):
        # `( ( uint32_t ) 0x1000U )` -> `0x1000`.
        self.assertEqual(
            cac._normalize_c_value("( ( uint32_t ) 0x1000U )"),
            "0x1000",
        )

    def test_non_numeric_word_not_eaten(self):
        # `TRUE` ends in `E` (letter) but is NOT a number with
        # suffix. Must survive intact.
        self.assertEqual(cac._normalize_c_value("TRUE"), "TRUE")
        self.assertEqual(cac._normalize_c_value("FALSE"), "FALSE")
        # `chThdU` would be even worse; not a real token but the
        # safety guard must reject it as suffix-strippable.
        self.assertEqual(cac._normalize_c_value("chThdU"), "chThdU")

    def test_eq_treats_suffixed_as_equal(self):
        # _eq is what the contract comparison ultimately uses, so
        # the user-visible behaviour is: a header literal `1U`
        # equates to a contract literal `1`.
        self.assertTrue(cac._eq(
            cac._normalize_c_value("1U"), "1",
        ))
        self.assertTrue(cac._eq(
            cac._normalize_c_value("0x10UL"), "16",
        ))


if __name__ == "__main__":
    unittest.main()
