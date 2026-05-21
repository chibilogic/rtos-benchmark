#!/usr/bin/env python3
"""Validation suite for scripts/bootstrap_toolchain.py (ADR-021,
hardened per Codex 2026-05-18-bootstrap-toolchain-codereview-001).

Fully offline: fixtures built in a temp dir, served via file://
with --allow-file-url; destinations are repo-relative under a
temporary --repo-root. No real toolchain download. Stdlib only.

Run: python -m unittest tests.test_bootstrap_toolchain -v
"""
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = REPO_ROOT / "scripts" / "bootstrap_toolchain.py"
PLAT = "linux-x86_64"
DEST = f"tools/{PLAT}/arm-gnu-toolchain"
STRIP = "tc-1.0"


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def make_zip(p: Path, kind: str = "good") -> None:
    with zipfile.ZipFile(p, "w") as zf:
        if kind == "good":
            zf.writestr(f"{STRIP}/bin/arm-none-eabi-gcc", b"#!fake\n")
        elif kind == "traversal":
            zf.writestr("../evil.txt", b"x")
        elif kind == "backslash":
            zf.writestr("a\\..\\..\\evil.txt", b"x")
        elif kind == "symlink":
            zi = zipfile.ZipInfo("link")
            zi.external_attr = (0o120777 << 16)
            zf.writestr(zi, "/etc/passwd")
        elif kind == "extra-top":
            zf.writestr(f"{STRIP}/bin/arm-none-eabi-gcc", b"x")
            zf.writestr("stray/foo", b"x")


def make_tar(p: Path, kind: str) -> None:
    with tarfile.open(p, "w:gz") as tf:
        if kind in ("good-exec", "good-noexec"):
            data = b"#!fake\n"
            ti = tarfile.TarInfo(f"{STRIP}/bin/arm-none-eabi-gcc")
            ti.size = len(data)
            ti.mode = 0o755 if kind == "good-exec" else 0o644
            tf.addfile(ti, io.BytesIO(data))
        elif kind == "traversal":
            ti = tarfile.TarInfo("../evil")
            ti.size = 1
            tf.addfile(ti, io.BytesIO(b"x"))
        elif kind == "symlink":
            ti = tarfile.TarInfo("ln")
            ti.type = tarfile.SYMTYPE
            ti.linkname = "/etc/passwd"
            tf.addfile(ti)
        elif kind == "fifo":
            ti = tarfile.TarInfo("fifo")
            ti.type = tarfile.FIFOTYPE
            tf.addfile(ti)
        # ADR-021 patch set 3a-extractor fixtures
        elif kind == "safe-symlink":
            data = b"#!real\n"
            ti = tarfile.TarInfo(f"{STRIP}/bin/arm-none-eabi-gcc")
            ti.size = len(data); ti.mode = 0o755
            tf.addfile(ti, io.BytesIO(data))
            ln = tarfile.TarInfo(f"{STRIP}/bin/arm-none-eabi-cc")
            ln.type = tarfile.SYMTYPE
            ln.linkname = "arm-none-eabi-gcc"
            tf.addfile(ln)
        elif kind == "escape-symlink":
            ln = tarfile.TarInfo(f"{STRIP}/bin/escape")
            ln.type = tarfile.SYMTYPE
            ln.linkname = "../../../etc/passwd"
            tf.addfile(ln)
        elif kind == "backslash-symlink":
            ln = tarfile.TarInfo(f"{STRIP}/bin/back")
            ln.type = tarfile.SYMTYPE
            ln.linkname = "subdir\\file"
            tf.addfile(ln)
        elif kind == "drive-symlink":
            ln = tarfile.TarInfo(f"{STRIP}/bin/drv")
            ln.type = tarfile.SYMTYPE
            ln.linkname = "C:/Windows"
            tf.addfile(ln)
        elif kind == "safe-hardlink":
            data = b"#!real\n"
            ti = tarfile.TarInfo(f"{STRIP}/bin/arm-none-eabi-gcc")
            ti.size = len(data); ti.mode = 0o755
            tf.addfile(ti, io.BytesIO(data))
            hl = tarfile.TarInfo(f"{STRIP}/bin/arm-none-eabi-cc")
            hl.type = tarfile.LNKTYPE
            hl.linkname = f"{STRIP}/bin/arm-none-eabi-gcc"
            tf.addfile(hl)
        elif kind == "escape-hardlink":
            hl = tarfile.TarInfo(f"{STRIP}/bin/escape")
            hl.type = tarfile.LNKTYPE
            hl.linkname = "../../etc/passwd"
            tf.addfile(hl)
        # ADR-021 patch set 3a-extractor Codex CODE_REVIEW
        # 2026-05-20-adr021-patch-set-3a-extractor-applied-code-
        # review-001 BLOCKER 1+2 regression fixtures.
        elif kind == "dup-norm-regular":
            for variant in (f"{STRIP}/bin/x", f"{STRIP}/./bin/x"):
                data = variant.encode()
                ti = tarfile.TarInfo(variant)
                ti.size = len(data); ti.mode = 0o644
                tf.addfile(ti, io.BytesIO(data))
        elif kind == "dup-norm-reg-sym":
            data = b"x"
            ti = tarfile.TarInfo(f"{STRIP}/bin/x")
            ti.size = len(data); ti.mode = 0o644
            tf.addfile(ti, io.BytesIO(data))
            ln = tarfile.TarInfo(f"{STRIP}/./bin/x")
            ln.type = tarfile.SYMTYPE; ln.linkname = "y"
            tf.addfile(ln)
        elif kind == "hardlink-to-symlink":
            sl = tarfile.TarInfo(f"{STRIP}/bin/sym")
            sl.type = tarfile.SYMTYPE; sl.linkname = "real"
            tf.addfile(sl)
            hl = tarfile.TarInfo(f"{STRIP}/bin/hl")
            hl.type = tarfile.LNKTYPE
            hl.linkname = f"{STRIP}/bin/sym"
            tf.addfile(hl)
        elif kind == "hardlink-to-dir":
            di = tarfile.TarInfo(f"{STRIP}/bin")
            di.type = tarfile.DIRTYPE; di.mode = 0o755
            tf.addfile(di)
            hl = tarfile.TarInfo(f"{STRIP}/binhardlink")
            hl.type = tarfile.LNKTYPE; hl.linkname = f"{STRIP}/bin"
            tf.addfile(hl)
        elif kind == "hardlink-to-missing":
            hl = tarfile.TarInfo(f"{STRIP}/bin/hl")
            hl.type = tarfile.LNKTYPE
            hl.linkname = f"{STRIP}/bin/nonexistent"
            tf.addfile(hl)
        elif kind == "empty-symlink":
            ln = tarfile.TarInfo(f"{STRIP}/bin/empty")
            ln.type = tarfile.SYMTYPE; ln.linkname = ""
            tf.addfile(ln)
        elif kind == "empty-hardlink":
            hl = tarfile.TarInfo(f"{STRIP}/bin/empty")
            hl.type = tarfile.LNKTYPE; hl.linkname = ""
            tf.addfile(hl)


class BootstrapHardeningTest(unittest.TestCase):

    def setUp(self):
        self._t = tempfile.TemporaryDirectory()
        self.tmp = Path(self._t.name)
        self.repo = self.tmp / "repo"
        (self.repo / "tools").mkdir(parents=True)

    def tearDown(self):
        self._t.cleanup()

    def _lock(self, **over) -> Path:
        comp = {"version": "1.0", "url": "", "sha256": "",
                "archive": "zip", "strip_prefix": STRIP,
                "destination": DEST,
                "expect": ["bin/arm-none-eabi-gcc"]}
        comp.update(over)
        d = {"platforms": {PLAT: {"arm_gnu_toolchain": comp}}}
        p = self.tmp / "TOOLCHAIN.lock"
        p.write_text(json.dumps(d), encoding="utf-8")
        return p

    def _run(self, lock: Path, platform=PLAT, allow_file=True):
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        cmd = [sys.executable, str(SCRIPT), "--platform", platform,
               "--lock", str(lock), "--repo-root", str(self.repo)]
        if allow_file:
            cmd.append("--allow-file-url")
        return subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", env=env)

    def _arc(self, name: str, kind: str = "good",
             tar: bool = False) -> Path:
        a = self.tmp / name
        (make_tar if tar else make_zip)(a, kind)
        return a

    # --- happy path -------------------------------------------------
    def test_01_not_pinned(self):
        r = self._run(self._lock())
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not pinned", r.stdout + r.stderr)

    def test_02_valid_extract(self):
        a = self._arc("g.zip")
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a)))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((self.repo / DEST / "bin"
                         / "arm-none-eabi-gcc").is_file())
        self.assertTrue((self.repo / DEST / ".bootstrap_ok")
                        .is_file())

    def test_03_idempotent_skip(self):
        a = self._arc("g.zip")
        lk = self._lock(url=a.as_uri(), sha256=_sha(a))
        self._run(lk)
        r = self._run(lk)
        self.assertEqual(r.returncode, 0)
        self.assertIn("skip", r.stdout)

    def test_04_skip_only_if_layout_present(self):
        a = self._arc("g.zip")
        lk = self._lock(url=a.as_uri(), sha256=_sha(a))
        self._run(lk)
        (self.repo / DEST / "bin" / "arm-none-eabi-gcc").unlink()
        r = self._run(lk)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("skip", r.stdout)
        self.assertTrue((self.repo / DEST / "bin"
                         / "arm-none-eabi-gcc").is_file())

    def test_05_sha_mismatch(self):
        a = self._arc("g.zip")
        r = self._run(self._lock(url=a.as_uri(), sha256="0" * 64))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("SHA-256 mismatch", r.stdout + r.stderr)

    # --- platform / destination -------------------------------------
    def test_06_unsupported_platform(self):
        a = self._arc("g.zip")
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a)),
                      platform="macos-arm64")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not supported", r.stdout + r.stderr)

    def test_07_absolute_destination_rejected(self):
        a = self._arc("g.zip")
        absdest = str((self.tmp / "x").resolve())
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a),
                                 destination=absdest))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("repo-relative", r.stdout + r.stderr)

    def test_08_destination_escape_rejected(self):
        a = self._arc("g.zip")
        r = self._run(self._lock(
            url=a.as_uri(), sha256=_sha(a),
            destination=f"tools/{PLAT}/../../evil"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("escapes", r.stdout + r.stderr)

    # --- url scheme -------------------------------------------------
    def test_09_ftp_scheme_rejected(self):
        r = self._run(self._lock(url="ftp://h/x.zip",
                                 sha256="0" * 64))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("refused URL scheme", r.stdout + r.stderr)

    def test_10_file_url_needs_optin(self):
        a = self._arc("g.zip")
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a)),
                      allow_file=False)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("allow-file-url", r.stdout + r.stderr)

    # --- archive hardening ------------------------------------------
    def test_11_zip_traversal(self):
        a = self._arc("e.zip", "traversal")
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a),
                                 strip_prefix=""))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unsafe zip member", r.stdout + r.stderr)

    def test_12_zip_backslash(self):
        a = self._arc("b.zip", "backslash")
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a),
                                 strip_prefix=""))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unsafe zip member", r.stdout + r.stderr)

    def test_13_zip_symlink_rejected(self):
        a = self._arc("s.zip", "symlink")
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a),
                                 strip_prefix=""))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("zip symlink member rejected",
                      r.stdout + r.stderr)

    def test_14_strip_prefix_extra_top_rejected(self):
        a = self._arc("x.zip", "extra-top")
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a)))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not entirely under it", r.stdout + r.stderr)
        self.assertFalse((self.repo / DEST).exists())

    def test_15_tar_traversal(self):
        a = self._arc("t.tar.gz", "traversal", tar=True)
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a),
                                 archive="tar.gz", strip_prefix=""))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("unsafe tar member", r.stdout + r.stderr)

    def test_16_tar_external_symlink_rejected(self):
        # Codex 2026-05-20-adr021-patch-set-3a-symlink-discovery-001:
        # absolute /etc/passwd symlink stays rejected by the safe-
        # link policy (was the only symlink case rejected by the
        # original reject-all-non-regular policy; now caught by the
        # explicit absolute-symlink validation in _extract_tar).
        a = self._arc("ts.tar.gz", "symlink", tar=True)
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a),
                                 archive="tar.gz", strip_prefix=""))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("absolute symlink rejected", r.stdout + r.stderr)

    def test_17_tar_fifo_rejected(self):
        # FIFO / device / socket members stay rejected under the new
        # two-pass extractor: special-file rejection is non-negotiable.
        a = self._arc("tf.tar.gz", "fifo", tar=True)
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a),
                                 archive="tar.gz", strip_prefix=""))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("special", r.stdout + r.stderr)

    def test_18_no_partial_destination_on_failure(self):
        a = self._arc("g.zip")
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a),
                                 strip_prefix="wrong-prefix"))
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.repo / DEST).exists())

    # --- executable permission preservation (POSIX) -----------------
    @unittest.skipIf(os.name == "nt", "exec bits are POSIX-only")
    def test_19_tar_exec_bit_preserved(self):
        a = self._arc("ge.tar.gz", "good-exec", tar=True)
        lk = self._lock(
            url=a.as_uri(), sha256=_sha(a), archive="tar.gz",
            expect=[{"path": "bin/arm-none-eabi-gcc",
                     "executable": True}])
        r = self._run(lk)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        gcc = self.repo / DEST / "bin" / "arm-none-eabi-gcc"
        self.assertTrue(os.access(gcc, os.X_OK))

    @unittest.skipIf(os.name == "nt", "exec bits are POSIX-only")
    def test_20_non_exec_binary_rejected(self):
        a = self._arc("gn.tar.gz", "good-noexec", tar=True)
        lk = self._lock(
            url=a.as_uri(), sha256=_sha(a), archive="tar.gz",
            expect=[{"path": "bin/arm-none-eabi-gcc",
                     "executable": True}])
        r = self._run(lk)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("expected layout invalid", r.stdout + r.stderr)
        self.assertFalse((self.repo / DEST).exists())

    # --- ADR-021 patch set 3a-extractor (safe tar links) ---------

    @unittest.skipIf(os.name == "nt",
                     "POSIX symlink creation only")
    def test_21_tar_safe_internal_symlink_allowed(self):
        # Codex 2026-05-20-adr021-patch-set-3a-symlink-discovery-001:
        # safe internal symlink (relative, contained) must be
        # recreated as a real symlink under the extracted tree.
        a = self._arc("ssl.tar.gz", "safe-symlink", tar=True)
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a),
                                 archive="tar.gz"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        link = self.repo / DEST / "bin" / "arm-none-eabi-cc"
        self.assertTrue(link.is_symlink(),
                        f"{link} should be a symlink")
        self.assertEqual(os.readlink(link), "arm-none-eabi-gcc")

    def test_22_tar_symlink_escape_rejected(self):
        a = self._arc("esl.tar.gz", "escape-symlink", tar=True)
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a),
                                 archive="tar.gz"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("symlink escapes destination",
                      r.stdout + r.stderr)

    def test_23_tar_safe_hardlink_accepted(self):
        # Hardlinks are materialised as content copies (portable).
        a = self._arc("shl.tar.gz", "safe-hardlink", tar=True)
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a),
                                 archive="tar.gz"))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        real = self.repo / DEST / "bin" / "arm-none-eabi-gcc"
        copy = self.repo / DEST / "bin" / "arm-none-eabi-cc"
        self.assertTrue(real.is_file() and copy.is_file())
        # both files have identical content (the materialised copy)
        self.assertEqual(real.read_bytes(), copy.read_bytes())
        # neither is a symlink (hardlinks become content copies)
        self.assertFalse(copy.is_symlink())

    def test_24_tar_hardlink_escape_rejected(self):
        a = self._arc("ehl.tar.gz", "escape-hardlink", tar=True)
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a),
                                 archive="tar.gz"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("hardlink target", r.stdout + r.stderr)

    def test_25_tar_symlink_backslash_rejected(self):
        a = self._arc("bsl.tar.gz", "backslash-symlink", tar=True)
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a),
                                 archive="tar.gz"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("backslash-containing symlink",
                      r.stdout + r.stderr)

    def test_26_tar_symlink_drive_letter_rejected(self):
        a = self._arc("dsl.tar.gz", "drive-symlink", tar=True)
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a),
                                 archive="tar.gz"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("drive-letter symlink",
                      r.stdout + r.stderr)

    # --- Codex CODE_REVIEW 3a-extractor-applied (post-fix) ---

    def test_27_tar_duplicate_normalized_paths_rejected(self):
        a = self._arc("dnr.tar.gz", "dup-norm-regular", tar=True)
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a),
                                 archive="tar.gz"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("duplicate normalized tar member",
                      r.stdout + r.stderr)

    def test_28_tar_dup_norm_reg_sym_rejected(self):
        a = self._arc("drs.tar.gz", "dup-norm-reg-sym", tar=True)
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a),
                                 archive="tar.gz"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("duplicate normalized tar member",
                      r.stdout + r.stderr)

    def test_29_tar_hardlink_to_symlink_rejected(self):
        a = self._arc("hsl.tar.gz", "hardlink-to-symlink", tar=True)
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a),
                                 archive="tar.gz"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not a validated regular file",
                      r.stdout + r.stderr)

    def test_30_tar_hardlink_to_directory_rejected(self):
        a = self._arc("hdr.tar.gz", "hardlink-to-dir", tar=True)
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a),
                                 archive="tar.gz"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not a validated regular file",
                      r.stdout + r.stderr)

    def test_31_tar_hardlink_to_missing_rejected(self):
        a = self._arc("hmi.tar.gz", "hardlink-to-missing", tar=True)
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a),
                                 archive="tar.gz"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("not a validated regular file",
                      r.stdout + r.stderr)

    def test_32_tar_empty_symlink_rejected(self):
        a = self._arc("esl0.tar.gz", "empty-symlink", tar=True)
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a),
                                 archive="tar.gz"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("empty symlink target", r.stdout + r.stderr)

    def test_33_tar_empty_hardlink_rejected(self):
        a = self._arc("ehl0.tar.gz", "empty-hardlink", tar=True)
        r = self._run(self._lock(url=a.as_uri(), sha256=_sha(a),
                                 archive="tar.gz"))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("empty hardlink target", r.stdout + r.stderr)

    # --- ADR-021 patch set 3b: managed:false (host prerequisite) ---

    def test_34_unmanaged_entry_informatively_skipped(self):
        # managed=false + skip_reason makes the bootstrap print an
        # informative skip msg and return without trying to download.
        comp = {"managed": False,
                "skip_reason": "host prerequisite for testing",
                "expect_on_path": "make"}
        d = {"platforms": {PLAT: {"arm_gnu_toolchain": comp}}}
        p = self.tmp / "TOOLCHAIN.lock"
        p.write_text(json.dumps(d), encoding="utf-8")
        r = self._run(p)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("unmanaged: host prerequisite",
                      r.stdout + r.stderr)

    def test_35_managed_false_missing_skip_reason_fails(self):
        comp = {"managed": False}
        d = {"platforms": {PLAT: {"arm_gnu_toolchain": comp}}}
        p = self.tmp / "TOOLCHAIN.lock"
        p.write_text(json.dumps(d), encoding="utf-8")
        r = self._run(p)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("managed=false requires a non-empty",
                      r.stdout + r.stderr)

    # --- ADR-021 patch set 3b SSL (Codex 2026-05-21) ---

    def test_36_ssl_cert_file_env_respected(self):
        # If SSL_CERT_FILE is in env, script honors it (no override).
        a = self._arc("g.zip")
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["SSL_CERT_FILE"] = str(self.tmp / "fake-bundle.pem")
        cmd = [sys.executable, str(SCRIPT), "--platform", PLAT,
               "--lock", str(self._lock(url=a.as_uri(),
                                        sha256=_sha(a))),
               "--repo-root", str(self.repo), "--allow-file-url"]
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", env=env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("SSL_CERT_FILE/SSL_CERT_DIR provided by "
                      "environment", r.stdout)

    def test_37_non_tls_error_has_no_truststore_guidance(self):
        # Non-TLS download failure must NOT emit truststore guidance.
        bogus = (self.tmp / "does_not_exist.zip").as_uri()
        r = self._run(self._lock(url=bogus, sha256="0" * 64))
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("download failed", r.stdout + r.stderr)
        self.assertNotIn("pip install truststore",
                         r.stdout + r.stderr)


class TLSDiagnosticsTest(unittest.TestCase):
    """In-process tests for the TLS helpers (Codex
    2026-05-21-adr021-patch-set-3b-ssl-plan-review-001)."""

    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(SCRIPT.parent))
        import importlib
        cls.bt = importlib.import_module("bootstrap_toolchain")

    def setUp(self):
        self._env_keys = ("SSL_CERT_FILE", "SSL_CERT_DIR")
        self._saved = {k: os.environ.get(k) for k in self._env_keys}
        for k in self._env_keys:
            os.environ.pop(k, None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_38_is_cert_verify_error_variants(self):
        import ssl as _ssl
        import urllib.error
        direct = _ssl.SSLCertVerificationError(
            "CERTIFICATE_VERIFY_FAILED")
        wrapped = urllib.error.URLError(direct)
        other = urllib.error.URLError("not found")
        self.assertTrue(self.bt._is_cert_verify_error(direct))
        self.assertTrue(self.bt._is_cert_verify_error(wrapped))
        self.assertFalse(self.bt._is_cert_verify_error(other))

    def test_39_emit_cert_error_guidance_message(self):
        import ssl as _ssl
        e = _ssl.SSLCertVerificationError("CERTIFICATE_VERIFY_FAILED")
        with self.assertRaises(SystemExit) as cm:
            self.bt._emit_cert_error_guidance("foo", e)
        msg = str(cm.exception)
        self.assertIn("pip install truststore", msg)
        self.assertIn("SSL_CERT_FILE", msg)

    def test_40_configure_tls_trust_store_honors_env(self):
        os.environ["SSL_CERT_FILE"] = "/tmp/fake.pem"
        s = self.bt.configure_tls_trust_store()
        self.assertIn("SSL_CERT_FILE", s)
        self.assertIn("environment", s)

    def test_41_ssl_cert_dir_env_honored(self):
        os.environ["SSL_CERT_DIR"] = "/tmp/fake-dir"
        s = self.bt.configure_tls_trust_store()
        self.assertIn("SSL_CERT_DIR", s)
        self.assertIn("environment", s)

    def test_42_truststore_inject_called_when_available(self):
        # Mock a fake truststore module to prove inject_into_ssl()
        # is invoked when no SSL_CERT_* env var is set (Codex
        # CODE_REVIEW IMPORTANT 2).
        import sys as _sys
        import types
        called = {"hit": False}
        fake = types.ModuleType("truststore")

        def _fake_inject():
            called["hit"] = True
        fake.inject_into_ssl = _fake_inject
        saved = _sys.modules.get("truststore")
        _sys.modules["truststore"] = fake
        try:
            s = self.bt.configure_tls_trust_store()
        finally:
            if saved is None:
                _sys.modules.pop("truststore", None)
            else:
                _sys.modules["truststore"] = saved
        self.assertTrue(called["hit"],
                        f"inject_into_ssl not called; status={s!r}")
        self.assertIn("truststore", s)

    def test_43_truststore_inject_failure_fails_with_guidance(self):
        # Broken/incompatible truststore that raises on inject must
        # produce a SystemExit with actionable guidance, NOT a silent
        # fallback (Codex CODE_REVIEW IMPORTANT 3).
        import sys as _sys
        import types
        fake = types.ModuleType("truststore")

        def _broken_inject():
            raise RuntimeError("simulated incompatible truststore")
        fake.inject_into_ssl = _broken_inject
        saved = _sys.modules.get("truststore")
        _sys.modules["truststore"] = fake
        try:
            with self.assertRaises(SystemExit) as cm:
                self.bt.configure_tls_trust_store()
        finally:
            if saved is None:
                _sys.modules.pop("truststore", None)
            else:
                _sys.modules["truststore"] = saved
        msg = str(cm.exception)
        self.assertIn("truststore", msg)
        self.assertIn("SSL_CERT_FILE", msg)
        self.assertIn("simulated incompatible truststore", msg)


if __name__ == "__main__":
    unittest.main(verbosity=2)
