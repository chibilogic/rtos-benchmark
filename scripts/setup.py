#!/usr/bin/env python3
"""ADR-021 follow-up - one-command host setup orchestrator.

Single source of truth for the fresh-clone procedure. Wrappers
scripts/setup.sh and scripts/setup.ps1 are thin and delegate here.
stdlib only.

Plan (Codex 2026-05-21-setup-orchestrator-plan-review-001):
  0. preflight: git, python (>=3.10), make on PATH;
  1. git submodule update --init --recursive;
  2. select host Python:
       - already inside a venv -> use it;
       - --use-current-python -> use sys.executable;
       - otherwise -> create/reuse .venv-host at repo root;
  3. SSL trust: if SSL_CERT_FILE / SSL_CERT_DIR set, skip;
     elif truststore already importable in the selected Python, skip;
     else `<python> -m pip install truststore`;
  4. `<python> scripts/bootstrap_toolchain.py`;
  5. `<python> -m pip install -r requirements.txt`;
  6. `<python> -m unittest discover -s tests` (skippable via
     --skip-tests);
  7. (unless --skip-zephyr) create zephyr/.venv; pip install west;
     west init -l benchmark_zephyr; west update (idempotent after
     first run; downloads ~500 MB-1 GB the first time);
  8. banner: tell user to activate venv + env.bat/sh + first make
     for all 3 RTOS.

Design notes:
  - build_plan(args, python) returns a list of Step records;
    execute_plan runs them; print_plan is the --check-only output.
    This makes the orchestrator unit-testable without network/pip/
    git side-effects (Codex MD 2).
  - Repo root is resolved from __file__, not the cwd.
  - Fail-fast: a non-zero exit from any sub-step aborts with the
    same exit code.
  - No interactivity. No prompts. Suitable for CI later.
  - TLS policy unchanged: never disables verification; honors
    SSL_CERT_FILE / SSL_CERT_DIR on all OSes; truststore is the
    standard Windows path (per Codex 2026-05-21-adr021-patch-set-
    3b-ssl-plan-review-001).
  - Zephyr venv IS initialized by default (user-driven deviation
    from Codex MD 6 of 2026-05-21-setup-orchestrator-plan-review-
    001; documented in the next CODE_REVIEW handoff). Opt-out via
    --skip-zephyr for users who only want ChibiOS+FreeRTOS.
  - No HW steps: no OpenOCD flashing, no serial, no lab campaign.
  - No --force flag (Codex MD 3: undefined scope; can return later
    with a precise contract if needed).

Usage:
    python scripts/setup.py [--skip-tests] [--skip-zephyr]
        [--check-only] [--use-current-python]
Exit codes: 0 ok; 1 on any failure.
"""
from __future__ import annotations
import argparse
import os
import shutil
import subprocess
import sys
import venv
from dataclasses import dataclass
from pathlib import Path
from typing import NoReturn

REPO_ROOT = Path(__file__).resolve().parents[1]
HOST_VENV = REPO_ROOT / ".venv-host"
ZEPHYR_DIR = REPO_ROOT / "zephyr"
ZEPHYR_VENV = ZEPHYR_DIR / ".venv"
ZEPHYR_WEST_TOPDIR = ZEPHYR_DIR / ".west"
SUPPORTED_PYTHON_MIN = (3, 10)


def fail(msg: str) -> NoReturn:
    raise SystemExit(msg)


@dataclass
class Step:
    """One unit of work in the setup plan.

    cmd is the resolved subprocess argv to run (None for an
    informational/skip step or for a step handled inline in
    execute_plan, e.g. 'zephyr-venv' which calls
    ensure_zephyr_venv()). cwd is optional.
    """
    name: str
    description: str
    cmd: list[str] | None = None
    cwd: Path | None = None


# ---------------------------------------------------------------
# Preflight (Codex MD 5).
# ---------------------------------------------------------------

def preflight() -> None:
    """Hard blockers: python (>=3.10), git, make. Make has an
    educational message because it is intentionally unmanaged by
    tools/TOOLCHAIN.lock (ADR-021 patch set 3b).
    """
    if sys.version_info < SUPPORTED_PYTHON_MIN:
        fail(
            f"[setup] Python {SUPPORTED_PYTHON_MIN[0]}."
            f"{SUPPORTED_PYTHON_MIN[1]}+ required (found "
            f"{sys.version_info.major}.{sys.version_info.minor})."
        )
    if shutil.which("git") is None:
        fail("[setup] 'git' is not on PATH. Install git and re-run.")
    if shutil.which("make") is None:
        fail(
            "[setup] 'make' is not on PATH. GNU Make is intentionally"
            " NOT managed by tools/TOOLCHAIN.lock (no canonical "
            "upstream binary archive). Install it manually:\n"
            "  Linux:   sudo apt install make  (or distro equivalent)"
            "\n"
            "  Windows: install MSYS2 (https://www.msys2.org/) and\n"
            "           `pacman -S mingw-w64-x86_64-make`, or use\n"
            "           the ChibiStudio bundle.\n"
            "See docs/SETUP.md section 2."
        )


# ---------------------------------------------------------------
# Host Python venv resolution (Codex MD 1).
# ---------------------------------------------------------------

def _in_venv() -> bool:
    """True if the current interpreter is already inside a venv
    (PEP 405) or VIRTUAL_ENV is set in the environment."""
    return sys.prefix != sys.base_prefix or "VIRTUAL_ENV" in os.environ


def _venv_python(venv_dir: Path) -> Path:
    if os.name == "nt":
        return venv_dir / "Scripts" / "python.exe"
    return venv_dir / "bin" / "python"


def resolve_host_python(use_current: bool) -> Path:
    """Return the Python executable to use for all subsequent steps.

    Codex MD 1 precedence:
      - --use-current-python: sys.executable (no venv created);
      - already inside a venv: sys.executable;
      - otherwise: ensure .venv-host exists and return its python.
    """
    if use_current or _in_venv():
        return Path(sys.executable).resolve()
    if not HOST_VENV.exists():
        print(f"[setup] creating host venv at {HOST_VENV}")
        venv.EnvBuilder(with_pip=True, clear=False,
                        upgrade_deps=False).create(str(HOST_VENV))
    py = _venv_python(HOST_VENV)
    if not py.is_file():
        fail(f"[setup] failed to materialise host venv python "
             f"at {py}")
    return py.resolve()


# ---------------------------------------------------------------
# SSL adapter step (Codex MD 1 + prior TLS plan-review).
# ---------------------------------------------------------------

def _truststore_importable(python: Path) -> bool:
    try:
        r = subprocess.run(
            [str(python), "-c", "import truststore"],
            capture_output=True, text=True)
        return r.returncode == 0
    except Exception:
        return False


def needs_truststore_install(python: Path) -> bool:
    if (os.environ.get("SSL_CERT_FILE")
            or os.environ.get("SSL_CERT_DIR")):
        return False
    return not _truststore_importable(python)


# ---------------------------------------------------------------
# Zephyr venv (user-driven deviation from Codex MD 6: ON by
# default; opt-out via --skip-zephyr). Kept SEPARATE from
# .venv-host by project design (docs/SETUP.md sec. 8 'host-vs-
# Zephyr-venv discipline').
# ---------------------------------------------------------------

def _zephyr_venv_python() -> Path:
    if os.name == "nt":
        return ZEPHYR_VENV / "Scripts" / "python.exe"
    return ZEPHYR_VENV / "bin" / "python"


def _zephyr_west_exe() -> Path:
    if os.name == "nt":
        return ZEPHYR_VENV / "Scripts" / "west.exe"
    return ZEPHYR_VENV / "bin" / "west"


def needs_zephyr_venv() -> bool:
    return not _zephyr_venv_python().is_file()


def needs_west_install() -> bool:
    return not _zephyr_west_exe().is_file()


def needs_west_init() -> bool:
    return not ZEPHYR_WEST_TOPDIR.is_dir()


def ensure_zephyr_venv() -> None:
    """Idempotent: create zephyr/.venv if missing."""
    if _zephyr_venv_python().is_file():
        return
    print(f"[setup] creating Zephyr venv at {ZEPHYR_VENV}")
    venv.EnvBuilder(with_pip=True, clear=False,
                    upgrade_deps=False).create(str(ZEPHYR_VENV))


# ---------------------------------------------------------------
# Plan construction (no side effects beyond venv creation already
# performed by resolve_host_python; testable in isolation).
# ---------------------------------------------------------------

def build_plan(args, python: Path) -> list[Step]:
    """Construct the ordered list of steps. Pure function of
    (args, python, env, filesystem probes)."""
    steps: list[Step] = []
    steps.append(Step(
        name="submodules",
        description="git submodule update --init --recursive",
        cmd=["git", "submodule", "update", "--init", "--recursive"],
        cwd=REPO_ROOT,
    ))
    if needs_truststore_install(python):
        steps.append(Step(
            name="ssl-truststore",
            description=("pip install truststore (Schannel CA on "
                         "Windows; harmless elsewhere)"),
            cmd=[str(python), "-m", "pip", "install", "truststore"],
        ))
    else:
        why = ("SSL_CERT_FILE/SSL_CERT_DIR provided by environment"
               if (os.environ.get("SSL_CERT_FILE")
                   or os.environ.get("SSL_CERT_DIR"))
               else "truststore already importable")
        steps.append(Step(
            name="ssl-truststore-skip",
            description=f"SSL trust adapter: skip ({why})",
        ))
    steps.append(Step(
        name="bootstrap-toolchain",
        description=("scripts/bootstrap_toolchain.py "
                     "(download + SHA-256 + extract toolchain)"),
        cmd=[str(python), str(REPO_ROOT / "scripts"
                              / "bootstrap_toolchain.py")],
        cwd=REPO_ROOT,
    ))
    steps.append(Step(
        name="host-deps",
        description="pip install -r requirements.txt",
        cmd=[str(python), "-m", "pip", "install", "-r",
             str(REPO_ROOT / "requirements.txt")],
    ))
    if not args.skip_tests:
        steps.append(Step(
            name="tests",
            description=("python -m unittest discover -s tests "
                         "(~2 min)"),
            cmd=[str(python), "-m", "unittest", "discover",
                 "-s", "tests"],
            cwd=REPO_ROOT,
        ))
    else:
        steps.append(Step(
            name="tests-skip",
            description="host test suite: skip (--skip-tests)",
        ))
    # Zephyr (user-driven deviation from Codex MD 6: ON by default).
    if args.skip_zephyr:
        steps.append(Step(
            name="zephyr-skip",
            description=("Zephyr venv/west init/update: skip "
                         "(--skip-zephyr); ChibiOS+FreeRTOS still "
                         "build fully"),
        ))
        return steps
    zpy = _zephyr_venv_python()
    if needs_zephyr_venv():
        steps.append(Step(
            name="zephyr-venv",
            description=("create zephyr/.venv (separate from "
                         ".venv-host by design, docs/SETUP.md "
                         "sec. 8)"),
        ))
    else:
        steps.append(Step(
            name="zephyr-venv-skip",
            description="zephyr/.venv already exists, reuse",
        ))
    if needs_west_install():
        steps.append(Step(
            name="zephyr-west-install",
            description="pip install west into zephyr/.venv",
            cmd=[str(zpy), "-m", "pip", "install", "west"],
        ))
    else:
        steps.append(Step(
            name="zephyr-west-skip",
            description="west already installed in zephyr/.venv",
        ))
    if needs_west_init():
        steps.append(Step(
            name="zephyr-west-init",
            description="west init -l benchmark_zephyr",
            cmd=[str(zpy), "-m", "west", "init", "-l",
                 "benchmark_zephyr"],
            cwd=ZEPHYR_DIR,
        ))
    else:
        steps.append(Step(
            name="zephyr-west-init-skip",
            description="zephyr/.west already exists, reuse",
        ))
    steps.append(Step(
        name="zephyr-west-update",
        description=("west update (downloads/updates Zephyr modules "
                     "~500 MB-1 GB first time; idempotent after)"),
        cmd=[str(zpy), "-m", "west", "update"],
        cwd=ZEPHYR_DIR,
    ))
    return steps


# ---------------------------------------------------------------
# Plan execution + dry-run printing.
# ---------------------------------------------------------------

def print_plan(python: Path, steps: list[Step]) -> None:
    print(f"[setup] host python: {python}")
    print(f"[setup] repo root:   {REPO_ROOT}")
    print(f"[setup] dry-run (--check-only). Planned steps:")
    for i, s in enumerate(steps, 1):
        print(f"  {i}. {s.name:24s} {s.description}")
        if s.cmd is not None:
            print(f"     $ {' '.join(s.cmd)}")
            if s.cwd is not None:
                print(f"       (cwd: {s.cwd})")
    print("[setup] dry-run complete; no side-effects performed.")


def execute_plan(python: Path, steps: list[Step]) -> int:
    print(f"[setup] host python: {python}")
    print(f"[setup] repo root:   {REPO_ROOT}")
    for i, s in enumerate(steps, 1):
        print(f"\n[setup] step {i}/{len(steps)}: {s.name} - "
              f"{s.description}")
        if s.name == "zephyr-venv":
            ensure_zephyr_venv()
            continue
        if s.cmd is None:
            continue
        r = subprocess.run(s.cmd,
                           cwd=str(s.cwd) if s.cwd else None)
        if r.returncode != 0:
            print(f"[setup] step '{s.name}' failed (exit "
                  f"{r.returncode}); aborting.",
                  file=sys.stderr)
            return r.returncode
    return 0


def print_banner(python: Path, skip_zephyr: bool) -> None:
    is_win = os.name == "nt"
    using_repo_venv = False
    try:
        using_repo_venv = python.is_relative_to(HOST_VENV)
    except (ValueError, AttributeError):
        using_repo_venv = False
    print("\n" + "=" * 60)
    print("Setup complete. Next:")
    step_num = 1
    if using_repo_venv:
        if is_win:
            print(f"  {step_num}. Activate host venv: "
                  f".venv-host\\Scripts\\activate.bat")
        else:
            print(f"  {step_num}. Activate host venv: "
                  f". .venv-host/bin/activate")
        step_num += 1
    if is_win:
        print(f"  {step_num}. Activate toolchain env: env.bat")
    else:
        print(f"  {step_num}. Activate toolchain env: . ./env.sh")
    step_num += 1
    print(f"  {step_num}. Build firmware (pick any/all):")
    print(f"     make -C chibios/benchmark_chibios")
    print(f"     make -C freertos/benchmark_freertos "
          f"PROFILE=fair_perf")
    if not skip_zephyr:
        print(f"     make -C zephyr/benchmark_zephyr  "
              f"PROFILE=fair_perf")
    else:
        print(f"     # Zephyr: re-run setup without --skip-zephyr "
              f"first")
    print("=" * 60)


# ---------------------------------------------------------------
# CLI.
# ---------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description=("One-command host setup for the rtos-benchmark"
                     " fresh clone (Codex 2026-05-21-setup-"
                     "orchestrator-plan-review-001)."))
    ap.add_argument("--skip-tests", action="store_true",
                    help="skip the host test suite (~2 min)")
    ap.add_argument("--skip-zephyr", action="store_true",
                    help="skip Zephyr venv + west init/update "
                         "(saves ~500 MB-1 GB download); ChibiOS "
                         "and FreeRTOS still build fully")
    ap.add_argument("--check-only", action="store_true",
                    help="dry-run: print planned steps without "
                         "running any side-effect command")
    ap.add_argument("--use-current-python", action="store_true",
                    help="use sys.executable instead of "
                         "creating/using .venv-host")
    a = ap.parse_args()
    preflight()
    if a.check_only:
        if a.use_current_python or _in_venv():
            python = Path(sys.executable).resolve()
        else:
            python = _venv_python(HOST_VENV)  # may not yet exist
        steps = build_plan(a, python)
        print_plan(python, steps)
        return 0
    python = resolve_host_python(a.use_current_python)
    steps = build_plan(a, python)
    rc = execute_plan(python, steps)
    if rc == 0:
        print_banner(python, a.skip_zephyr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
