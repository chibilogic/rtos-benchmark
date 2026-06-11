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
        # build_notice() bundles the tracked root NOTICE.txt; the fake repo
        # root needs one.
        (self.root / "NOTICE.txt").write_text(
            "NOTICE (test)\n", encoding="utf-8")
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
                # .map is intentionally NOT published (ADR-025): its
                # map_sha256 stays in the campaign lock instead.
                self.assertNotIn(f"raw/{r}_{p}_run01.map", names)

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
    def _gen_digest(self) -> str:
        """Generate to dist (no publish) and return the asset filename, so a
        matching published README can be created for the deterministic
        digest before the publish step (which now requires the README)."""
        mra.main(["--out-dir", str(self.root / "dist")])
        return next((self.root / "dist").glob("phase1-raw-logs-*.zip")).name

    def test_publish_dir_copies_only_zip_and_sidecar(self):
        zname = self._gen_digest()
        pub = self.root / "published-logs" / "phase1"
        pub.mkdir(parents=True)
        (pub / "README.md").write_text(f"Asset: {zname}\n", encoding="utf-8")
        rc = mra.main(["--out-dir", str(self.root / "dist"),
                       "--publish-dir", str(pub)])
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
        zname = self._gen_digest()
        pub = self.root / "published-logs" / "phase1"
        pub.mkdir(parents=True)
        stale = pub / "phase1-raw-logs-deadbeef0000.zip"
        stale.write_bytes(b"stale")
        (pub / "phase1-raw-logs-deadbeef0000.zip.sha256").write_text(
            "x  phase1-raw-logs-deadbeef0000.zip\n", encoding="utf-8")
        (pub / "README.md").write_text(f"Asset: {zname}\n", encoding="utf-8")
        rc = mra.main(["--out-dir", str(self.root / "dist"),
                       "--publish-dir", str(pub)])
        self.assertEqual(rc, 0)
        self.assertFalse(stale.exists())
        zips = list(pub.glob("phase1-raw-logs-*.zip"))
        self.assertEqual(len(zips), 1)
        self.assertNotIn("deadbeef0000", zips[0].name)

    def test_publish_dir_missing_readme_fails_stop(self):
        # No README -> fail-stop BEFORE any mutation (review -022 transactional).
        pub = self.root / "published-logs" / "phase1"
        pub.mkdir(parents=True)
        stale = pub / "phase1-raw-logs-deadbeef0000.zip"
        stale.write_bytes(b"stale")
        with self.assertRaises(SystemExit):
            mra.main(["--out-dir", str(self.root / "dist"),
                      "--publish-dir", str(pub)])
        # transactional: the pre-existing asset is preserved, none added.
        self.assertTrue(stale.exists())
        self.assertEqual(
            sorted(p.name for p in pub.glob("phase1-raw-logs-*.zip")),
            ["phase1-raw-logs-deadbeef0000.zip"])

    def test_publish_dir_copy_failure_preserves_prior(self):
        # Injected copy failure must NOT destroy the prior published pair
        # (review -023: transactional install -- prepare/verify before prune).
        from unittest import mock
        zname = self._gen_digest()
        pub = self.root / "published-logs" / "phase1"
        pub.mkdir(parents=True)
        prior = pub / "phase1-raw-logs-deadbeef0000.zip"
        prior.write_bytes(b"prior-valid")
        prior_side = pub / "phase1-raw-logs-deadbeef0000.zip.sha256"
        prior_side.write_text(
            "x  phase1-raw-logs-deadbeef0000.zip\n", encoding="utf-8")
        (pub / "README.md").write_text(f"Asset: {zname}\n", encoding="utf-8")
        with mock.patch("make_raw_logs_archive.shutil.copyfile",
                        side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                mra.main(["--out-dir", str(self.root / "dist"),
                          "--publish-dir", str(pub)])
        # the prior published pair survives; no partial/new/tmp asset remains
        self.assertTrue(prior.exists())
        self.assertTrue(prior_side.exists())
        self.assertFalse((pub / zname).exists())
        self.assertEqual(list(pub.glob(".*.tmp")), [])

    def test_publish_dir_verify_failure_preserves_prior(self):
        # Injected post-copy SHA mismatch must preserve the prior pair and
        # install no new/partial/temp asset (review -024 regression guard).
        from unittest import mock
        zname = self._gen_digest()
        pub = self.root / "published-logs" / "phase1"
        pub.mkdir(parents=True)
        prior = pub / "phase1-raw-logs-deadbeef0000.zip"
        prior.write_bytes(b"prior-valid")
        prior_side = pub / "phase1-raw-logs-deadbeef0000.zip.sha256"
        prior_side.write_text(
            "x  phase1-raw-logs-deadbeef0000.zip\n", encoding="utf-8")
        (pub / "README.md").write_text(f"Asset: {zname}\n", encoding="utf-8")
        real_sha = mra.sha256_file

        def fake_sha(p):
            if str(p).endswith(".tmp"):
                return "0" * 64
            return real_sha(p)
        with mock.patch("make_raw_logs_archive.sha256_file",
                        side_effect=fake_sha):
            with self.assertRaises(SystemExit):
                mra.main(["--out-dir", str(self.root / "dist"),
                          "--publish-dir", str(pub)])
        self.assertTrue(prior.exists())
        self.assertTrue(prior_side.exists())
        self.assertFalse((pub / zname).exists())
        self.assertFalse((pub / f"{zname}.sha256").exists())
        self.assertEqual(list(pub.glob(".*.tmp")), [])

    def test_publish_dir_sidecar_install_failure_rolls_back(self):
        # Injected sidecar-install failure (after the ZIP install) must roll
        # back the new ZIP, leave no new sidecar or temp file, and keep the
        # prior published pair intact (review -024).
        from unittest import mock
        zname = self._gen_digest()
        pub = self.root / "published-logs" / "phase1"
        pub.mkdir(parents=True)
        prior = pub / "phase1-raw-logs-deadbeef0000.zip"
        prior.write_bytes(b"prior-valid")
        prior_side = pub / "phase1-raw-logs-deadbeef0000.zip.sha256"
        prior_side.write_text(
            "x  phase1-raw-logs-deadbeef0000.zip\n", encoding="utf-8")
        (pub / "README.md").write_text(f"Asset: {zname}\n", encoding="utf-8")
        real_replace = mra.Path.replace

        def fake_replace(self, target):
            if str(target).endswith(".sha256"):
                raise OSError("disk full")
            return real_replace(self, target)
        with mock.patch("make_raw_logs_archive.Path.replace", new=fake_replace):
            with self.assertRaises(OSError):
                mra.main(["--out-dir", str(self.root / "dist"),
                          "--publish-dir", str(pub)])
        self.assertTrue(prior.exists())
        self.assertTrue(prior_side.exists())
        self.assertFalse((pub / zname).exists())
        self.assertFalse((pub / f"{zname}.sha256").exists())
        self.assertEqual(list(pub.glob(".*.tmp")), [])

    def test_publish_dir_idempotent_same_digest_noop(self):
        # Republishing the identical digest is a no-op: the already valid pair
        # is preserved and NO final replace of dst/side is attempted (-025).
        from unittest import mock
        zname = self._gen_digest()
        pub = self.root / "published-logs" / "phase1"
        pub.mkdir(parents=True)
        (pub / "README.md").write_text(f"Asset: {zname}\n", encoding="utf-8")
        self.assertEqual(mra.main(["--out-dir", str(self.root / "dist"),
                                   "--publish-dir", str(pub)]), 0)
        zip_before = (pub / zname).read_bytes()
        side_before = (pub / f"{zname}.sha256").read_bytes()
        real_replace = mra.Path.replace
        seen = []

        def spy_replace(self, target):
            seen.append(str(target))
            return real_replace(self, target)
        with mock.patch("make_raw_logs_archive.Path.replace", new=spy_replace):
            self.assertEqual(mra.main(["--out-dir", str(self.root / "dist"),
                                       "--publish-dir", str(pub)]), 0)
        self.assertFalse(any(s.endswith(zname) for s in seen))
        self.assertFalse(any(s.endswith(f"{zname}.sha256") for s in seen))
        self.assertEqual((pub / zname).read_bytes(), zip_before)
        self.assertEqual((pub / f"{zname}.sha256").read_bytes(), side_before)
        self.assertEqual(list(pub.glob(".*.tmp")), [])

    def test_publish_dir_same_name_mismatch_refused(self):
        # A same-name target whose bytes do not match the staged digest is
        # evidence of corruption/collision: refuse, leaving it untouched (-025).
        zname = self._gen_digest()
        pub = self.root / "published-logs" / "phase1"
        pub.mkdir(parents=True)
        (pub / "README.md").write_text(f"Asset: {zname}\n", encoding="utf-8")
        bad_zip = b"corrupt-not-the-real-archive"
        (pub / zname).write_bytes(bad_zip)
        bad_side = "deadbeef  " + zname + "\n"
        (pub / f"{zname}.sha256").write_text(bad_side, encoding="utf-8")
        with self.assertRaises(SystemExit):
            mra.main(["--out-dir", str(self.root / "dist"),
                      "--publish-dir", str(pub)])
        self.assertEqual((pub / zname).read_bytes(), bad_zip)
        self.assertEqual(
            (pub / f"{zname}.sha256").read_text(encoding="utf-8"), bad_side)
        self.assertEqual(list(pub.glob(".*.tmp")), [])

    def test_publish_dir_same_name_half_present_refused(self):
        # Only the ZIP present (sidecar missing) for the target digest is a
        # partial prior publish: refuse without replacing/deleting it (-025).
        zname = self._gen_digest()
        pub = self.root / "published-logs" / "phase1"
        pub.mkdir(parents=True)
        (pub / "README.md").write_text(f"Asset: {zname}\n", encoding="utf-8")
        half = b"half-present-zip"
        (pub / zname).write_bytes(half)
        with self.assertRaises(SystemExit):
            mra.main(["--out-dir", str(self.root / "dist"),
                      "--publish-dir", str(pub)])
        self.assertEqual((pub / zname).read_bytes(), half)
        self.assertFalse((pub / f"{zname}.sha256").exists())
        self.assertEqual(list(pub.glob(".*.tmp")), [])

    def test_publish_dir_readme_mismatch_fails_stop(self):
        # A README naming a different asset -> fail-stop BEFORE any mutation
        # (review -020/-022): no prune/copy, the publish dir is unchanged.
        pub = self.root / "published-logs" / "phase1"
        pub.mkdir(parents=True)
        stale = pub / "phase1-raw-logs-deadbeef0000.zip"
        stale.write_bytes(b"stale")
        (pub / "README.md").write_text(
            "Asset: phase1-raw-logs-deadbeef0000.zip\n", encoding="utf-8")
        with self.assertRaises(SystemExit):
            mra.main(["--out-dir", str(self.root / "dist"),
                      "--publish-dir", str(pub)])
        self.assertTrue(stale.exists())
        self.assertEqual(
            sorted(p.name for p in pub.glob("phase1-raw-logs-*.zip")),
            ["phase1-raw-logs-deadbeef0000.zip"])


if __name__ == "__main__":
    unittest.main()
