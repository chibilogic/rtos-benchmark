"""Unit tests for scripts/zephyr_config_snapshot.py (synthetic .config)."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import zephyr_config_snapshot as zcs  # noqa: E402

SAMPLE = """
# Auto-generated Zephyr configuration
CONFIG_MULTITHREADING=y
CONFIG_SCHED_SIMPLE=y
# CONFIG_SCHED_SCALABLE is not set
CONFIG_PREEMPT_ENABLED=y
CONFIG_NUM_PREEMPT_PRIORITIES=8
CONFIG_SYS_CLOCK_TICKS_PER_SEC=1000
# CONFIG_TICKLESS_KERNEL is not set
CONFIG_ARM_ON_ENTER_CPU_IDLE_HOOK=y
CONFIG_HEAP_MEM_POOL_SIZE=0
CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE=512
CONFIG_NOT_IN_LIST=y
"""


class TestParseDotconfig(unittest.TestCase):
    def setUp(self):
        self.v = zcs.parse_dotconfig(SAMPLE)

    def test_set_bool(self):
        self.assertEqual(self.v["CONFIG_MULTITHREADING"], "y")
        self.assertEqual(self.v["CONFIG_SCHED_SIMPLE"], "y")
        self.assertEqual(self.v["CONFIG_ARM_ON_ENTER_CPU_IDLE_HOOK"], "y")

    def test_commented_and_absent_are_not_set(self):
        self.assertEqual(self.v["CONFIG_SCHED_SCALABLE"], zcs.NOT_SET)
        self.assertEqual(self.v["CONFIG_TICKLESS_KERNEL"], zcs.NOT_SET)
        self.assertEqual(self.v["CONFIG_PM"], zcs.NOT_SET)
        self.assertEqual(self.v["CONFIG_ASSERT"], zcs.NOT_SET)
        self.assertEqual(self.v["CONFIG_USERSPACE"], zcs.NOT_SET)

    def test_int_values(self):
        self.assertEqual(self.v["CONFIG_NUM_PREEMPT_PRIORITIES"], "8")
        self.assertEqual(self.v["CONFIG_SYS_CLOCK_TICKS_PER_SEC"], "1000")
        self.assertEqual(self.v["CONFIG_HEAP_MEM_POOL_SIZE"], "0")
        self.assertEqual(
            self.v["CONFIG_SYSTEM_WORKQUEUE_STACK_SIZE"], "512")

    def test_keys_are_exactly_symbols_in_order(self):
        self.assertEqual(list(self.v.keys()), zcs.SYMBOLS)

    def test_unrelated_symbol_ignored(self):
        self.assertNotIn("CONFIG_NOT_IN_LIST", self.v)

    def test_quoted_string_stripped(self):
        v = zcs.parse_dotconfig('CONFIG_MULTITHREADING="abc"')
        self.assertEqual(v["CONFIG_MULTITHREADING"], "abc")


class TestSnapshotIO(unittest.TestCase):
    def test_write_snapshot(self):
        with tempfile.TemporaryDirectory() as td:
            tdp = Path(td)
            cfg = tdp / ".config"
            cfg.write_text(SAMPLE, encoding="utf-8")
            orig = zcs.dotconfig_path
            zcs.dotconfig_path = lambda profile: cfg
            try:
                out = zcs.write_snapshot("fair_perf", tdp / "out")
            finally:
                zcs.dotconfig_path = orig
            data = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(data["profile"], "fair_perf")
        self.assertEqual(data["schema"], "rtos-benchmark/zephyr-config/v1")
        self.assertEqual(data["symbols"]["CONFIG_MULTITHREADING"], "y")
        self.assertEqual(data["symbols"]["CONFIG_PM"], zcs.NOT_SET)

    def test_missing_config_raises(self):
        orig = zcs.dotconfig_path
        zcs.dotconfig_path = lambda profile: Path("nonexistent_dir/.config")
        try:
            with self.assertRaises(FileNotFoundError):
                zcs.snapshot("fair_perf")
        finally:
            zcs.dotconfig_path = orig


if __name__ == "__main__":
    unittest.main()
