"""Unit tests for scripts/verify_published_archive.py."""
import hashlib
import json
import sys
import tempfile
import textwrap
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import verify_published_archive as vpa  # noqa: E402

PROFILES = ("fair_perf", "realistic_tickless")
RTOSES = ("chibios", "freertos", "zephyr")
AGG = "rtos,test,median_cycles\nchibios,t1,100\nfreertos,t1,110\nzephyr,t1,120\n"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def build_archive_tree(root: Path) -> None:
    """Create a minimal but self-consistent extracted-archive layout."""
    raw = root / "results" / "raw"
    summ = root / "results" / "summary"
    mani_dir = root / "results" / "manifest"
    for d in (raw, summ, mani_dir):
        d.mkdir(parents=True, exist_ok=True)

    payload = {}  # relpath -> bytes
    for prof in PROFILES:
        rtos_block = {}
        for rtos in RTOSES:
            elf_bytes = f"ELF::{rtos}::{prof}".encode()
            payload[f"results/raw/{rtos}_{prof}_run01.elf"] = elf_bytes
            rtos_block[rtos] = {"elf_sha256": _sha(elf_bytes)}
            payload[f"results/raw/{rtos}_{prof}_run01.csv"] = b"iteration,cycles\n1,100\n"
        payload[f"results/manifest/{prof}_campaign.lock.json"] = json.dumps(
            {"profile": prof, "rtoses": rtos_block}, indent=1).encode()
        payload[f"results/summary/{prof}_aggregate.csv"] = AGG.encode()

    for rel, data in payload.items():
        f = root / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)

    lines = [f"{_sha(d)}  {rel}  {len(d)}" for rel, d in sorted(payload.items())]
    (root / "MANIFEST.sha256").write_text("\n".join(lines) + "\n",
                                          encoding="utf-8")


def write_stub_report(path: Path, *, faithful: bool) -> None:
    """A stand-in report_results.py. faithful: copies the shipped aggregate
    (medians reproduce); otherwise emits a different table."""
    if faithful:
        body = textwrap.dedent('''\
            import argparse, pathlib
            p = argparse.ArgumentParser()
            p.add_argument("--input-dir")
            p.add_argument("--output-dir")
            p.add_argument("--profile")
            a = p.parse_args()
            root = pathlib.Path(a.input_dir).parent.parent
            src = root / "results" / "summary" / (a.profile + "_aggregate.csv")
            out = pathlib.Path(a.output_dir)
            out.mkdir(parents=True, exist_ok=True)
            (out / (a.profile + "_aggregate.csv")).write_bytes(src.read_bytes())
        ''')
    else:
        body = textwrap.dedent('''\
            import argparse, pathlib
            p = argparse.ArgumentParser()
            p.add_argument("--input-dir")
            p.add_argument("--output-dir")
            p.add_argument("--profile")
            a = p.parse_args()
            out = pathlib.Path(a.output_dir)
            out.mkdir(parents=True, exist_ok=True)
            (out / (a.profile + "_aggregate.csv")).write_text("DIFFERENT\\n")
        ''')
    path.write_text(body, encoding="utf-8")


class VerifyArchiveTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        self.root = base / "phase1-raw-logs-deadbeef"
        self.root.mkdir(parents=True)
        build_archive_tree(self.root)
        self.stub_good = base / "stub_good.py"
        self.stub_bad = base / "stub_bad.py"
        write_stub_report(self.stub_good, faithful=True)
        write_stub_report(self.stub_bad, faithful=False)

    def tearDown(self):
        self._tmp.cleanup()

    def test_manifest_ok(self):
        self.assertTrue(vpa.check_manifest(self.root))

    def test_manifest_detects_tamper(self):
        f = self.root / "results" / "raw" / "chibios_fair_perf_run01.csv"
        f.write_bytes(f.read_bytes() + b"X")
        self.assertFalse(vpa.check_manifest(self.root))

    def test_firmware_ok(self):
        self.assertTrue(vpa.check_firmware(self.root))

    def test_firmware_detects_wrong_elf(self):
        f = self.root / "results" / "raw" / "zephyr_fair_perf_run01.elf"
        f.write_bytes(b"TAMPERED")
        self.assertFalse(vpa.check_firmware(self.root))

    def test_medians_ok(self):
        self.assertTrue(vpa.check_medians(self.root, self.stub_good, PROFILES))

    def test_medians_detects_divergence(self):
        self.assertFalse(vpa.check_medians(self.root, self.stub_bad, PROFILES))

    def test_archive_sha_match_and_mismatch(self):
        zpath = Path(self._tmp.name) / "a.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            for p in self.root.rglob("*"):
                if p.is_file():
                    zf.write(p, p.relative_to(self.root.parent).as_posix())
        side = Path(str(zpath) + ".sha256")
        side.write_text(vpa.sha256_file(zpath) + "  a.zip\n")
        self.assertTrue(vpa.check_archive(zpath, side))
        side.write_text("0" * 64 + "  a.zip\n")
        self.assertFalse(vpa.check_archive(zpath, side))

    def test_main_dir_pass(self):
        rc = vpa.main([str(self.root), "--report-script", str(self.stub_good)])
        self.assertEqual(rc, 0)

    def test_main_dir_fail_on_tamper(self):
        f = self.root / "results" / "raw" / "chibios_fair_perf_run01.csv"
        f.write_bytes(b"zzz")
        rc = vpa.main([str(self.root), "--report-script", str(self.stub_good)])
        self.assertEqual(rc, 1)

    def test_main_zip_pass(self):
        zpath = Path(self._tmp.name) / "phase1-raw-logs-deadbeef.zip"
        with zipfile.ZipFile(zpath, "w") as zf:
            for p in self.root.rglob("*"):
                if p.is_file():
                    arc = (Path(self.root.name) / p.relative_to(self.root)).as_posix()
                    zf.write(p, arc)
        Path(str(zpath) + ".sha256").write_text(
            vpa.sha256_file(zpath) + "  " + zpath.name + "\n")
        rc = vpa.main([str(zpath), "--report-script", str(self.stub_good)])
        self.assertEqual(rc, 0)


if __name__ == "__main__":
    unittest.main()
