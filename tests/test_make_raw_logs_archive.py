"""Unit tests for scripts/make_raw_logs_archive.py (selection / fail-stop)."""
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import make_raw_logs_archive as mra  # noqa: E402

RTOSES = ("chibios", "freertos", "zephyr")
PROFILES = ("fair_perf", "realistic_tickless")
RUNS = ("01", "02", "03", "04", "05")
SUFFIXES = (".csv", ".t4_pi.csv", ".banner.txt", ".validated.json")


def build_full_tree(root: Path, *, noise: bool = True) -> Path:
    results = root / "results"
    raw = results / "raw"
    raw.mkdir(parents=True)
    (results / "manifest").mkdir()
    (results / "summary" / "footprint").mkdir(parents=True)
    (results / "summary" / "zephyr_config").mkdir(parents=True)
    (results / "README.md").write_text("format", encoding="utf-8")
    for r in RTOSES:
        for p in PROFILES:
            for run in RUNS:
                for suf in SUFFIXES:
                    (raw / f"{r}_{p}_run{run}{suf}").write_text(
                        "x", encoding="utf-8")
            # ELF/MAP exist for every run (campaign artifacts); only run01
            # is published.
            for run in ("00",) + RUNS:
                (raw / f"{r}_{p}_run{run}.elf").write_bytes(b"elf")
                (raw / f"{r}_{p}_run{run}.map").write_text(
                    "map", encoding="utf-8")
    for p in PROFILES:
        (results / "manifest" / f"{p}_campaign.lock.json").write_text(
            "{}", encoding="utf-8")
        (results / "summary" / "footprint"
         / f"{p}_footprint.json").write_text("{}", encoding="utf-8")
        (results / "summary" / "footprint"
         / f"{p}_footprint.md").write_text("#", encoding="utf-8")
        (results / "summary" / "zephyr_config"
         / f"{p}.json").write_text("{}", encoding="utf-8")
        (results / "summary" / f"{p}_aggregate.csv").write_text(
            "a", encoding="utf-8")
    if noise:
        for r in RTOSES:
            for p in PROFILES:
                for suf in SUFFIXES:
                    (raw / f"{r}_{p}_run00{suf}").write_text(
                        "warm", encoding="utf-8")
                (raw / f"{r}_{p}_run01.stdout.txt").write_text(
                    "n", encoding="utf-8")
                (raw / f"{r}_{p}_run01.collector.out.txt").write_text(
                    "n", encoding="utf-8")
        (results / "plots").mkdir()
        (results / "plots" / "x.png").write_bytes(b"png")
        arch = raw / "_archived_pre_adr024"
        arch.mkdir()
        (arch / "chibios_fair_perf_run01.csv").write_text(
            "stale", encoding="utf-8")
        (results / "_campaign_logs").mkdir()
        (results / "_campaign_logs" / "log.txt").write_text(
            "l", encoding="utf-8")
    return results


class BaseTmp(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.root = Path(self._td.name)
        build_full_tree(self.root)
        self._orig = (mra.REPO_ROOT, mra.RESULTS)
        mra.REPO_ROOT = self.root
        mra.RESULTS = self.root / "results"

    def tearDown(self):
        mra.REPO_ROOT, mra.RESULTS = self._orig
        self._td.cleanup()

    def names(self, files):
        base = self.root / "results"
        return {p.relative_to(base).as_posix() for p in files}


class TestSelection(BaseTmp):
    def test_selects_full_expected_matrix(self):
        names = self.names(mra.collect_files())
        for r in RTOSES:
            for p in PROFILES:
                for run in RUNS:
                    for suf in SUFFIXES:
                        self.assertIn(f"raw/{r}_{p}_run{run}{suf}", names)
                self.assertIn(f"raw/{r}_{p}_run01.elf", names)
                self.assertIn(f"raw/{r}_{p}_run01.map", names)

    def test_excludes_noise(self):
        names = self.names(mra.collect_files())
        self.assertNotIn("raw/chibios_fair_perf_run00.csv", names)
        self.assertNotIn("raw/chibios_fair_perf_run02.elf", names)
        self.assertNotIn("raw/chibios_fair_perf_run05.map", names)
        self.assertFalse(any(".stdout." in n for n in names))
        self.assertFalse(any(".collector." in n for n in names))
        self.assertFalse(any(n.startswith("plots/") for n in names))
        self.assertFalse(any("_archived" in n for n in names))
        self.assertFalse(any("_campaign_logs" in n for n in names))

    def test_includes_locks_summary_readme(self):
        names = self.names(mra.collect_files())
        self.assertIn("manifest/fair_perf_campaign.lock.json", names)
        self.assertIn("manifest/realistic_tickless_campaign.lock.json", names)
        self.assertIn("summary/footprint/fair_perf_footprint.json", names)
        self.assertIn("summary/zephyr_config/realistic_tickless.json", names)
        self.assertIn("README.md", names)

    def test_result_is_sorted(self):
        files = mra.collect_files()
        keyed = sorted(
            files, key=lambda p: p.relative_to(mra.REPO_ROOT).as_posix())
        self.assertEqual(files, keyed)

    def test_manifest_ordering_stable(self):
        man = mra.build_manifest(mra.collect_files())
        paths = [ln.split("  ")[1] for ln in man.strip().splitlines()]
        self.assertEqual(paths, sorted(paths))


class TestFailStop(BaseTmp):
    def test_missing_required_raw_fails(self):
        (self.root / "results" / "raw"
         / "chibios_fair_perf_run03.csv").unlink()
        with self.assertRaises(SystemExit):
            mra.collect_files()

    def test_unexpected_debug_dev_fails(self):
        (self.root / "results" / "raw"
         / "chibios_debug_dev_run01.csv").write_text("x", encoding="utf-8")
        with self.assertRaises(SystemExit):
            mra.collect_files()

    def test_unexpected_run_id_fails(self):
        (self.root / "results" / "raw"
         / "chibios_fair_perf_run06.csv").write_text("x", encoding="utf-8")
        with self.assertRaises(SystemExit):
            mra.collect_files()

    def test_unexpected_lock_fails(self):
        (self.root / "results" / "manifest"
         / "debug_dev_campaign.lock.json").write_text("{}", encoding="utf-8")
        with self.assertRaises(SystemExit):
            mra.collect_files()

    def test_missing_summary_required_fails(self):
        (self.root / "results" / "summary" / "footprint"
         / "fair_perf_footprint.json").unlink()
        with self.assertRaises(SystemExit):
            mra.collect_files()


class TestPublishDir(BaseTmp):
    def test_publish_dir_copies_only_zip_and_sidecar(self):
        dist = self.root / "dist"
        pub = self.root / "published-logs" / "phase1"
        rc = mra.main(["--out-dir", str(dist), "--publish-dir", str(pub)])
        self.assertEqual(rc, 0)
        zips = list(pub.glob("phase1-raw-logs-*.zip"))
        self.assertEqual(len(zips), 1)
        # no tar.gz / SHA256SUMS copied into the tracked publish dir
        self.assertEqual(list(pub.glob("*.tar.gz")), [])
        self.assertEqual(list(pub.glob("*.SHA256SUMS")), [])
        sidecar = pub / (zips[0].name + ".sha256")
        self.assertTrue(sidecar.is_file())
        line = sidecar.read_text(encoding="utf-8").strip()
        self.assertTrue(line.endswith(zips[0].name))
        self.assertNotIn(".tar.gz", line)

    def test_publish_dir_prunes_stale_archives(self):
        pub = self.root / "published-logs" / "phase1"
        pub.mkdir(parents=True)
        stale = pub / "phase1-raw-logs-deadbeef0000.zip"
        stale.write_bytes(b"stale")
        (pub / "phase1-raw-logs-deadbeef0000.zip.sha256").write_text(
            "x  phase1-raw-logs-deadbeef0000.zip\n", encoding="utf-8")
        rc = mra.main(["--out-dir", str(self.root / "dist"),
                       "--publish-dir", str(pub)])
        self.assertEqual(rc, 0)
        self.assertFalse(stale.exists())
        zips = list(pub.glob("phase1-raw-logs-*.zip"))
        self.assertEqual(len(zips), 1)
        self.assertNotIn("deadbeef0000", zips[0].name)


if __name__ == "__main__":
    unittest.main()
