# SPDX-License-Identifier: GPL-3.0-or-later
#
# Phase 1 publishable report builder.
#
# Reads aggregated benchmark data, per-run validated manifests, banner
# files and pre-rendered plots from results/ and produces a single
# self-contained PDF under docs/Phase1_Benchmark_Report.pdf.
#
# The script is dependency-light: ReportLab + the Python standard
# library. It is fully re-runnable; the output PDF is
# overwritten every time.
#
# Usage:
#   python scripts/build_report.py
#
# Author: Edoardo Lombardi - Chibilogic s.r.l.

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_JUSTIFY, TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm, mm
from reportlab.platypus import (
    BaseDocTemplate, Frame, Image, KeepTogether, NextPageTemplate,
    PageBreak, PageTemplate, Paragraph, Spacer, Table, TableStyle,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RESULTS = REPO_ROOT / "results"
SUMMARY = RESULTS / "summary"
RAW = RESULTS / "raw"
PLOTS = RESULTS / "plots"
MANIFEST = RESULTS / "manifest"
DOCS = REPO_ROOT / "docs"
OUTPUT_PDF = DOCS / "Phase1_Benchmark_Report.pdf"

REPORT_TITLE = "RTOS Benchmark on STM32H750B-DK"
REPORT_SUBTITLE = "Phase 1 - DWT-only Publishable Campaign"
AUTHOR = "Edoardo Lombardi"
COMPANY = "Chibilogic s.r.l."
REPORT_DATE = dt.date.today().isoformat()

# Publication metadata (Codex 2026-05-18-report-legal-compliance-001).
# Empty URLs + "draft" status make the report render truthful
# "pending public release/archive" wording plus a legal-review
# warning. Fill the URLs and set PUBLICATION_STATUS = "published"
# ONLY when a public repository and a downloadable raw-log archive
# actually exist; never hardcode placeholder URLs.
# Empty in development/draft: a broken hardcoded phase1-v1.0 URL is worse
# than no URL. The publication commit (Gate D) fills these with the real
# immutable tag/release URLs and flips PUBLICATION_STATUS to "published".
PUBLIC_REPOSITORY_URL = ""
PUBLIC_RAW_LOGS_URL = ""
PUBLICATION_STATUS = "draft"

RTOSES = ["chibios", "freertos", "zephyr"]
RTOS_LABELS = {"chibios": "ChibiOS", "freertos": "FreeRTOS", "zephyr": "Zephyr"}
PROFILES = ["fair_perf", "realistic_tickless"]
PROFILE_LABELS = {
    "fair_perf": "fair_perf  (tickless OFF, WFI OFF)",
    "realistic_tickless": "realistic_tickless  (tickless ON, WFI ON)",
}
PROFILE_ROLE = {
    "realistic_tickless": "the headline representative profile (low-power, "
                          "shipping-like: tickless idle + WFI enabled)",
    "fair_perf": "the controlled-isolation baseline (periodic tick, no WFI) "
                 "that exposes scheduler / primitive cost without idle "
                 "re-arm effects",
}
TESTS = ["t1_irq", "t2_handoff", "t3_mtx_uncont", "t4_mtx_pi"]
TEST_LABELS = {
    "t1_irq": "T1 - IRQ -> thread latency",
    "t2_handoff": "T2 - Thread handoff",
    "t3_mtx_uncont": "T3 - Mutex uncontended",
    "t4_mtx_pi": "T4 - Mutex contended + priority inheritance",
}

CPU_HZ = 480_000_000

# Palette for tables (clean, neutral).
HDR_BG = colors.HexColor("#1f2a44")
HDR_FG = colors.whitesmoke
ROW_ALT = colors.HexColor("#f3f5f9")
GRID = colors.HexColor("#cdd3dd")
ACCENT = colors.HexColor("#2b5797")
GOOD = colors.HexColor("#107c10")
BAD = colors.HexColor("#a4262c")


# ---------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------

@dataclass(frozen=True)
class AggRow:
    rtos: str
    rtos_version: str
    profile: str
    test: str
    source: str
    n_runs: int
    n: int
    median: int
    p95: int
    p99: int
    max: int
    jitter: int
    stddev: int
    run_spread: int
    median_us: float
    p99_us: float
    pi_passed_total: int | None
    pi_total_total: int | None


def _parse_int(v: str) -> int | None:
    if v == "" or v is None:
        return None
    return int(v)


def load_aggregate(profile: str) -> list[AggRow]:
    path = SUMMARY / f"{profile}_aggregate.csv"
    out: list[AggRow] = []
    with path.open("r", newline="", encoding="utf-8") as fp:
        reader = csv.DictReader(fp)
        for r in reader:
            out.append(AggRow(
                rtos=r["rtos"],
                rtos_version=r["rtos_version"],
                profile=r["profile"],
                test=r["test"],
                source=r["source"],
                n_runs=int(r["n_runs"]),
                n=int(r["n"]),
                median=int(r["median"]),
                p95=int(r["p95"]),
                p99=int(r["p99"]),
                max=int(r["max"]),
                jitter=int(r["jitter"]),
                stddev=int(r["stddev"]),
                run_spread=int(r["run_spread"]),
                median_us=float(r["median_us"]),
                p99_us=float(r["p99_us"]),
                pi_passed_total=_parse_int(r["pi_passed_total"]),
                pi_total_total=_parse_int(r["pi_total_total"]),
            ))
    return out


@dataclass(frozen=True)
class FootprintRow:
    rtos: str
    code_size: int
    ram_static_used: int
    ram_bss_excluded: int
    ram_extra_stacks: int
    tail_reservation: int | None
    elf_source: str
    lock_sha256_match: bool | None


def load_footprint(profile: str) -> list[FootprintRow]:
    """Load the ADR-023 footprint JSON for one profile.

    Produced by report_results.py --footprint (which drives
    footprint.py --from-raw --verify-lock). Missing file is a
    publication-gate failure surfaced by validate_publication_metadata.
    """
    path = SUMMARY / "footprint" / f"{profile}_footprint.json"
    with path.open("r", encoding="utf-8-sig") as fp:
        data = json.load(fp)
    out: list[FootprintRow] = []
    for e in data.get("elfs", []):
        tail = e.get("tail_reservation_size")
        out.append(FootprintRow(
            rtos=e["rtos"],
            code_size=int(e["code_size_total"]),
            ram_static_used=int(e["ram_static_used"]),
            ram_bss_excluded=int(e.get("ram_bss_excluded", 0)),
            ram_extra_stacks=int(e.get("ram_extra_stacks", 0)),
            tail_reservation=int(tail) if tail is not None else None,
            elf_source=e.get("elf_source", "build"),
            lock_sha256_match=e.get("lock_sha256_match"),
        ))
    return out


def load_validated(rtos: str, profile: str, run: str) -> dict:
    path = RAW / f"{rtos}_{profile}_run{run}.validated.json"
    with path.open("r", encoding="utf-8-sig") as fp:
        return json.load(fp)


def load_lock(profile: str) -> dict:
    path = MANIFEST / f"{profile}_campaign.lock.json"
    with path.open("r", encoding="utf-8-sig") as fp:
        return json.load(fp)


def lookup_row(rows: list[AggRow], rtos: str, test: str) -> AggRow:
    for r in rows:
        if r.rtos == rtos and r.test == test:
            return r
    raise KeyError(f"({rtos}, {test}) not in aggregate")


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fp:
        for chunk in iter(lambda: fp.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---------------------------------------------------------------------
# ReportLab styling
# ---------------------------------------------------------------------

def make_styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    styles: dict[str, ParagraphStyle] = {}
    styles["body"] = ParagraphStyle(
        "body", parent=base["BodyText"], fontName="Helvetica",
        fontSize=9.5, leading=13, alignment=TA_JUSTIFY,
        spaceAfter=4,
    )
    styles["body_left"] = ParagraphStyle(
        "body_left", parent=styles["body"], alignment=TA_LEFT,
    )
    styles["small"] = ParagraphStyle(
        "small", parent=styles["body"], fontSize=8.0, leading=11,
    )
    styles["mono"] = ParagraphStyle(
        "mono", parent=styles["body"], fontName="Courier",
        fontSize=8.0, leading=10, alignment=TA_LEFT,
    )
    styles["h1"] = ParagraphStyle(
        "h1", parent=base["Heading1"], fontName="Helvetica-Bold",
        fontSize=16, leading=20, textColor=HDR_BG,
        spaceBefore=4, spaceAfter=8,
    )
    styles["h2"] = ParagraphStyle(
        "h2", parent=base["Heading2"], fontName="Helvetica-Bold",
        fontSize=12.5, leading=16, textColor=ACCENT,
        spaceBefore=8, spaceAfter=4,
    )
    styles["h3"] = ParagraphStyle(
        "h3", parent=base["Heading3"], fontName="Helvetica-Bold",
        fontSize=10.5, leading=13, textColor=HDR_BG,
        spaceBefore=6, spaceAfter=2,
    )
    styles["caption"] = ParagraphStyle(
        "caption", parent=styles["small"], alignment=TA_CENTER,
        textColor=colors.grey, spaceBefore=2, spaceAfter=10,
    )
    styles["cover_title"] = ParagraphStyle(
        "cover_title", parent=base["Title"], fontName="Helvetica-Bold",
        fontSize=26, leading=32, alignment=TA_CENTER, textColor=HDR_BG,
        spaceAfter=4,
    )
    styles["cover_sub"] = ParagraphStyle(
        "cover_sub", parent=base["Title"], fontName="Helvetica",
        fontSize=15, leading=20, alignment=TA_CENTER, textColor=ACCENT,
        spaceAfter=18,
    )
    styles["cover_meta"] = ParagraphStyle(
        "cover_meta", parent=base["BodyText"], fontName="Helvetica",
        fontSize=12, leading=18, alignment=TA_CENTER,
    )
    styles["th"] = ParagraphStyle(
        "th", parent=base["BodyText"], fontName="Helvetica-Bold",
        fontSize=7.5, leading=9, alignment=TA_CENTER,
        textColor=HDR_FG, spaceBefore=0, spaceAfter=0,
    )
    styles["tcell"] = ParagraphStyle(
        "tcell", parent=base["BodyText"], fontName="Helvetica",
        fontSize=8.5, leading=10.5, alignment=TA_LEFT,
        textColor=colors.black, spaceBefore=0, spaceAfter=0,
    )
    return styles


def std_table_style(header_rows: int = 1) -> TableStyle:
    return TableStyle([
        ("BACKGROUND", (0, 0), (-1, header_rows - 1), HDR_BG),
        ("TEXTCOLOR", (0, 0), (-1, header_rows - 1), HDR_FG),
        ("FONTNAME", (0, 0), (-1, header_rows - 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("LEADING", (0, 0), (-1, -1), 10.5),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ROWBACKGROUNDS", (0, header_rows), (-1, -1),
            [colors.white, ROW_ALT]),
        ("GRID", (0, 0), (-1, -1), 0.25, GRID),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ])


def _hrow(labels: Iterable[str],
          styles: dict[str, ParagraphStyle]) -> list:
    """Header row with wrapping Paragraph cells.

    ReportLab does not word-wrap raw strings inside a Table; only
    Paragraph flowables wrap to the column width. The TableStyle
    keeps the header background but cannot recolour Paragraph text,
    so styles["th"] carries the white bold appearance itself.
    """
    return [Paragraph(x, styles["th"]) for x in labels]


# ---------------------------------------------------------------------
# Page templates
# ---------------------------------------------------------------------

PAGE_W, PAGE_H = A4
MARGIN_L = 2.0 * cm
MARGIN_R = 2.0 * cm
MARGIN_T = 2.2 * cm
MARGIN_B = 2.0 * cm
CONTENT_W = PAGE_W - MARGIN_L - MARGIN_R


def _draw_cover_decor(canvas, _doc):
    canvas.saveState()
    canvas.setFillColor(HDR_BG)
    canvas.rect(0, PAGE_H - 1.4 * cm, PAGE_W, 1.4 * cm,
                stroke=0, fill=1)
    canvas.setFillColor(ACCENT)
    canvas.rect(0, 0, PAGE_W, 0.6 * cm, stroke=0, fill=1)
    canvas.restoreState()


def _draw_body_decor(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(HDR_BG)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(MARGIN_L, PAGE_H - 1.3 * cm, COMPANY)
    canvas.setFillColor(colors.grey)
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(PAGE_W - MARGIN_R, PAGE_H - 1.3 * cm,
                            f"{REPORT_TITLE}  -  Phase 1  -  {REPORT_DATE}")
    canvas.setStrokeColor(GRID)
    canvas.setLineWidth(0.4)
    canvas.line(MARGIN_L, PAGE_H - 1.45 * cm,
                PAGE_W - MARGIN_R, PAGE_H - 1.45 * cm)
    canvas.line(MARGIN_L, MARGIN_B - 0.4 * cm,
                PAGE_W - MARGIN_R, MARGIN_B - 0.4 * cm)
    canvas.setFillColor(colors.grey)
    canvas.setFont("Helvetica", 8)
    canvas.drawString(MARGIN_L, MARGIN_B - 0.85 * cm,
                       f"{AUTHOR}  /  {COMPANY}")
    canvas.drawRightString(PAGE_W - MARGIN_R, MARGIN_B - 0.85 * cm,
                            f"Page {doc.page}")
    canvas.restoreState()


def make_doc(path: Path) -> BaseDocTemplate:
    doc = BaseDocTemplate(
        str(path), pagesize=A4,
        leftMargin=MARGIN_L, rightMargin=MARGIN_R,
        topMargin=MARGIN_T, bottomMargin=MARGIN_B,
        title=REPORT_TITLE, author=AUTHOR,
    )
    cover_frame = Frame(MARGIN_L, MARGIN_B, CONTENT_W,
                        PAGE_H - MARGIN_T - MARGIN_B, id="cover")
    body_frame = Frame(MARGIN_L, MARGIN_B, CONTENT_W,
                       PAGE_H - MARGIN_T - MARGIN_B, id="body")
    doc.addPageTemplates([
        PageTemplate(id="cover", frames=[cover_frame],
                     onPage=_draw_cover_decor),
        PageTemplate(id="body", frames=[body_frame],
                     onPage=_draw_body_decor),
    ])
    return doc


# ---------------------------------------------------------------------
# Section builders
# ---------------------------------------------------------------------

def section_cover(styles: dict[str, ParagraphStyle]) -> list:
    flow: list = []
    flow.append(Spacer(1, 5.0 * cm))
    flow.append(Paragraph(REPORT_TITLE, styles["cover_title"]))
    flow.append(Paragraph(REPORT_SUBTITLE, styles["cover_sub"]))
    flow.append(Spacer(1, 1.0 * cm))
    flow.append(Paragraph(
        "Four-test latency comparison of ChibiOS RT 7.0.6, "
        "FreeRTOS V11.3.0 and Zephyr 4.4.0 running at 480 MHz "
        "(VOS0, FLASH WS=4, I-Cache + D-Cache enabled) on the "
        "STM32H750B-DK Discovery Kit.", styles["cover_meta"]))
    flow.append(Spacer(1, 3.0 * cm))
    meta = (
        f"<b>Author:</b> {AUTHOR}<br/>"
        f"<b>Company:</b> {COMPANY}<br/>"
        f"<b>Date:</b> {REPORT_DATE}<br/>"
        f"<b>Document:</b> Phase 1 publishable benchmark report"
    )
    flow.append(Paragraph(meta, styles["cover_meta"]))
    return flow


def section_abstract(styles: dict[str, ParagraphStyle],
                     fair: list[AggRow],
                     tickless: list[AggRow]) -> list:
    flow: list = [Paragraph("Abstract", styles["h1"])]
    c1 = lookup_row(tickless, "chibios", "t1_irq").median
    f1 = lookup_row(tickless, "freertos", "t1_irq").median
    z1 = lookup_row(tickless, "zephyr", "t1_irq").median
    c1_fp = lookup_row(fair, "chibios", "t1_irq").median
    f1_fp = lookup_row(fair, "freertos", "t1_irq").median
    z1_fp = lookup_row(fair, "zephyr", "t1_irq").median
    d_fr = f1 - f1_fp
    d_ch = c1 - c1_fp
    d_ze = z1 - z1_fp
    text = (
        "This report documents the Phase 1 DWT-only publishable "
        "benchmark campaign of three open-source real-time operating "
        "systems on a single, controlled and shared STM32H750B-DK target "
        "(the controlled setup minimizes known non-RTOS differences; results "
        "remain specific to the ports, configuration and scenarios reported here). "
        "The "
        "three kernels are compared under identical hardware "
        "conditions: CPU clock 480 MHz, voltage scaling VOS0, "
        "FLASH_ACR = 0x34, I-Cache + D-Cache enabled, identical GCC "
        "14.2 toolchain and -O2 -fomit-frame-pointer "
        "-falign-functions=16 effective flags. Two publishable "
        "profiles are reported. The headline profile is "
        "<b>realistic_tickless</b> (tickless idle ON, WFI ON), a "
        "representative low-power, shipping-like configuration; "
        "<b>fair_perf</b> (periodic tick, no WFI) is reported as a "
        "controlled-isolation baseline that exposes scheduler and "
        "primitive cost without idle re-arm effects. Latencies for the "
        "four tests T1-T4 are measured inside the firmware via the "
        "Cortex-M7 DWT cycle counter. Each (RTOS, profile) combination "
        "has been validated against five independent firmware loads, "
        "with publication-gate verification of clock, cache, flash, "
        "memory placement and priority-inheritance correctness; the "
        "run_spread metric is zero cycles on every (RTOS, test) cell, "
        "demonstrating fully reproducible results across reloads. Under "
        "realistic_tickless, ChibiOS showed the lowest median latency "
        f"in all four tests (T1 median {c1} cycles vs FreeRTOS {f1} and "
        f"Zephyr {z1}); the fair_perf baseline preserves the same "
        "ranking. Between the two profiles the FreeRTOS T1 median rises "
        f"from {f1_fp} to {f1} cycles ({d_fr:+d}) under this benchmark "
        f"configuration, a larger profile-to-profile change than ChibiOS "
        f"({d_ch:+d}) and Zephyr ({d_ze:+d}), which move much less; the "
        "delta is reported as measured, without attributing it to a single "
        "internal cause. Mutex priority-inheritance is correct in all "
        "three kernels with 500/500 events verified per RTOS per "
        "profile. FreeRTOS and Zephyr are excellent RTOS projects with "
        "different design goals; this comparison focuses only on "
        "real-time latency under the tested conditions."
    )
    flow.append(Paragraph(text, styles["body"]))
    return flow


def section_environment(styles: dict[str, ParagraphStyle],
                        sample_banner: dict[str, str]) -> list:
    flow: list = [Paragraph("Test environment", styles["h1"])]

    flow.append(Paragraph("Hardware", styles["h2"]))
    hw_rows = [
        ["Property", "Value"],
        ["Board", "STM32H750B-DK Discovery Kit"],
        ["MCU", "STM32H750XBH6, silicon revision V"],
        ["Core", "Cortex-M7 with double-precision FPU"],
        ["External oscillator (HSE)", "25 MHz crystal"],
        ["CPU clock", "480 MHz (PLL1 from HSE)"],
        ["Voltage scaling", "VOS0 (required for 480 MHz)"],
        ["FLASH_ACR", "0x00000034 (LATENCY = 4 WS, programming "
                       "delay 2)"],
        ["I-Cache / D-Cache", "ON (production-realistic)"],
        ["Internal Flash", "128 KB (no bootloader, application fits)"],
        ["RAM", "1 MB (64K ITCM + 128K DTCM + 864K AXI/AHB SRAM)"],
        ["Debug / VCP", "ST-LINK V3E onboard, USART3 PB10/PB11, "
                        "115200 8N1"],
    ]
    t = Table(hw_rows, colWidths=[5.0 * cm, 11.0 * cm])
    t.setStyle(std_table_style())
    t.setStyle(TableStyle([("ALIGN", (0, 1), (0, -1), "LEFT"),
                            ("ALIGN", (1, 1), (1, -1), "LEFT")]))
    flow.append(t)
    flow.append(Spacer(1, 4 * mm))

    flow.append(Paragraph("Toolchain and compile flags", styles["h2"]))
    tc_rows = [
        ["Tool", "Version / Setting"],
        ["GCC", "arm-none-eabi-gcc 14.2.Rel1 (Arm GNU Toolchain)"],
        ["Make", "GNU Make 4.3 (MSYS2)"],
        ["OpenOCD", "0.12.0+dev (xPack)"],
        ["Optimization", "-O2  (no -Os, no -O3, no LTO)"],
        ["ADR-009 effective flags",
            "-fomit-frame-pointer -falign-functions=16"],
        ["C standard",
            "C11 application code, C99 portable modules"],
        ["Cross-RTOS verification",
            "compile_commands.json read-back audit (per port)"],
    ]
    t = Table(tc_rows, colWidths=[5.0 * cm, 11.0 * cm])
    t.setStyle(std_table_style())
    t.setStyle(TableStyle([("ALIGN", (0, 1), (0, -1), "LEFT"),
                            ("ALIGN", (1, 1), (1, -1), "LEFT")]))
    flow.append(t)
    flow.append(Spacer(1, 4 * mm))

    flow.append(Paragraph("RTOS versions", styles["h2"]))
    rt_rows = [
        ["RTOS", "Version", "Source"],
        ["ChibiOS RT", "7.0.6", "ChibiOS 21.11.5, git tag ver21.11.5 "
                                 "(upstream, no fork)"],
        ["FreeRTOS Kernel", "V11.3.0",
            "tag V11.3.0 (release tested here)"],
        ["Zephyr", "4.4.0", "tag v4.4.0 (release tested here)"],
        ["STM32CubeH7 HAL", "v1.12.1",
            "for FreeRTOS variant only"],
    ]
    t = Table(rt_rows, colWidths=[4.0 * cm, 2.5 * cm, 9.5 * cm])
    t.setStyle(std_table_style())
    t.setStyle(TableStyle([("ALIGN", (0, 1), (-1, -1), "LEFT")]))
    flow.append(t)
    flow.append(Spacer(1, 4 * mm))

    flow.append(Paragraph(
        "All three kernels are pinned to specific tested release tags: "
        "ChibiOS 21.11.5 (RT 7.0.6, git tag ver21.11.5), FreeRTOS V11.3.0 "
        "and Zephyr 4.4.0. ChibiOS 21.11.x is the maintained stable line "
        "and 21.11.5 is the point release tested here, so the comparison "
        "uses these specific tagged releases of each kernel rather than a "
        "frozen older tag. The benchmarked firmware was captured at submodule "
        "commit 78a2ddd2, which is ver21.11.5 plus the removal of one "
        "non-compiled SBOM file; the source pin was subsequently aligned "
        "to the named tag ver21.11.5, and a clean rebuild from the pinned "
        "tree reproduces every benchmarked loadable firmware image "
        "byte-for-byte (loadable_image_sha256; the full ELF/MAP SHA-256 may "
        "differ only in DWARF/debug metadata after source comment edits).",
        styles["body"]))
    flow.append(Spacer(1, 4 * mm))

    flow.append(Paragraph(
        "Clock-tree witness (banner of run 01)", styles["h2"]))
    flow.append(Paragraph(
        "The firmware banner of every run prints back the values of "
        "RCC, PWR and FLASH registers immediately after boot, so "
        "that the publishable claims of 480 MHz / VOS0 / WS=4 are "
        "anchored to actually measured silicon state, not just "
        "configuration sources. The excerpt below is taken from "
        "<i>chibios_fair_perf_run01.banner.txt</i> and is "
        "representative.",
        styles["body"]))
    banner_pairs = [
        ("SystemClock", sample_banner.get("SystemClock", "")),
        ("VOS level", sample_banner.get("VOS level", "")),
        ("VOSRDY", sample_banner.get("VOSRDY", "")),
        ("FLASH_ACR", sample_banner.get("FLASH_ACR", "")),
        ("RCC_PLLCKSELR", sample_banner.get("RCC_PLLCKSELR", "")),
        ("RCC_PLLCFGR", sample_banner.get("RCC_PLLCFGR", "")),
        ("RCC_PLL1DIVR", sample_banner.get("RCC_PLL1DIVR", "")),
        ("RCC_D1CFGR", sample_banner.get("RCC_D1CFGR", "")),
        ("PWR_D3CR", sample_banner.get("PWR_D3CR", "")),
        ("SCB->CCR", sample_banner.get("SCB->CCR", "")),
        ("ICache", sample_banner.get("ICache", "")),
        ("DCache", sample_banner.get("DCache", "")),
        ("Tick rate", sample_banner.get("Tick rate", "")),
        ("Optimization", sample_banner.get("Optimization", "")),
    ]
    bn_rows = [["Register / field", "Value"]]
    for k, v in banner_pairs:
        bn_rows.append([k, v])
    t = Table(bn_rows, colWidths=[5.0 * cm, 11.0 * cm])
    t.setStyle(std_table_style())
    t.setStyle(TableStyle([
        ("ALIGN", (0, 1), (0, -1), "LEFT"),
        ("ALIGN", (1, 1), (1, -1), "LEFT"),
        ("FONTNAME", (1, 1), (1, -1), "Courier"),
        ("FONTSIZE", (1, 1), (1, -1), 8.5),
    ]))
    flow.append(t)
    return flow


def section_methodology(styles: dict[str, ParagraphStyle]) -> list:
    flow: list = [Paragraph("Methodology", styles["h1"])]

    flow.append(Paragraph("The four tests", styles["h2"]))
    tests_raw = [
        ("T1", "IRQ -> thread latency",
            "TIM2 compare match triggers a hardware-routed IRQ; a "
            "high-priority worker thread is unblocked. DWT counter "
            "is sampled at ISR entry (A1) and again as soon as the "
            "worker thread resumes execution (A4). The reported "
            "metric is the cycle delta A4 - A1, i.e. the path "
            "ISR_ENTRY -> THREAD_RUNNING."),
        ("T2", "Thread handoff",
            "A tester thread suspends/resumes a higher-priority target "
            "via the native suspend/resume primitive (the target blocks, "
            "the tester wakes it). Pure thread-to-thread context-switch "
            "cost, with the scheduler hot in cache."),
        ("T3", "Mutex lock / unlock, uncontended",
            "A single thread locks and immediately unlocks a mutex "
            "in a tight loop. No contention. Measures the cost of "
            "the fast path through the mutex primitive."),
        ("T4", "Mutex contended + priority inheritance",
            "Three threads (LOW, MEDIUM, HIGH). LOW owns the mutex, "
            "HIGH waits on it, MEDIUM tries to disturb. The "
            "scheduler must boost LOW to HIGH's priority and keep "
            "MEDIUM excluded for the duration of the critical "
            "section. The protocol verifies the PI invariant with "
            "100 one-shot scenarios per run."),
    ]
    tests_rows: list = [_hrow(["ID", "Name", "What is measured"],
                              styles)]
    for tid, name, desc in tests_raw:
        tests_rows.append([
            tid,
            Paragraph(name, styles["tcell"]),
            Paragraph(desc, styles["tcell"]),
        ])
    t = Table(tests_rows, colWidths=[1.2 * cm, 3.6 * cm, 11.2 * cm])
    t.setStyle(std_table_style())
    t.setStyle(TableStyle([
        ("ALIGN", (1, 1), (-1, -1), "LEFT"),
        ("VALIGN", (0, 1), (-1, -1), "TOP"),
    ]))
    flow.append(t)
    flow.append(Spacer(1, 4 * mm))

    flow.append(Paragraph(
        "<b>Cross-RTOS equivalence.</b> The benchmark defines the "
        "same external scenario for all three kernels and "
        "implements it with each RTOS's most direct native "
        "primitive. The source code is therefore not identical "
        "across ChibiOS, FreeRTOS and Zephyr; the comparison is "
        "scenario-equivalent under identical hardware, clock, "
        "compiler and measurement conditions.", styles["body"]))
    flow.append(Spacer(1, 4 * mm))

    flow.append(Paragraph("Primitive used per test", styles["h2"]))
    flow.append(Paragraph(
        "The exact native call exercised inside the measured DWT window "
        "for each (test, RTOS). For T1 and T2 these are the wake / "
        "handoff primitives themselves; the readiness handshakes used "
        "only to start each test are excluded.", styles["body"]))
    prim_rows = [
        _hrow(["Test", "ChibiOS", "FreeRTOS", "Zephyr"], styles),
        ["T1",
         Paragraph("chThdSuspendS / chThdResumeI", styles["tcell"]),
         Paragraph("ulTaskNotifyTake / vTaskNotifyGiveFromISR<br/>"
                   "+ portYIELD_FROM_ISR", styles["tcell"]),
         Paragraph("k_sem_take / k_sem_give", styles["tcell"])],
        ["T2",
         Paragraph("chSchGoSleepS / chSchWakeupS", styles["tcell"]),
         Paragraph("vTaskSuspend / vTaskResume", styles["tcell"]),
         Paragraph("k_thread_suspend /<br/>k_thread_resume",
                   styles["tcell"])],
        ["T3",
         Paragraph("chMtxLock / chMtxUnlock", styles["tcell"]),
         Paragraph("xSemaphoreCreateMutexStatic;<br/>"
                   "xSemaphoreTake / Give", styles["tcell"]),
         Paragraph("k_mutex_lock / k_mutex_unlock", styles["tcell"])],
        ["T4",
         Paragraph("chMtxLock / chMtxUnlock (PI)", styles["tcell"]),
         Paragraph("xSemaphoreCreateMutexStatic (PI);<br/>"
                   "xSemaphoreTake / Give", styles["tcell"]),
         Paragraph("k_mutex_lock / k_mutex_unlock (PI)", styles["tcell"])],
    ]
    t = Table(prim_rows, colWidths=[1.2 * cm, 4.9 * cm, 5.5 * cm, 4.4 * cm])
    t.setStyle(std_table_style())
    t.setStyle(TableStyle([
        ("ALIGN", (1, 1), (-1, -1), "LEFT"),
        ("VALIGN", (0, 1), (-1, -1), "TOP"),
        ("FONTNAME", (1, 1), (-1, -1), "Courier"),
        ("FONTSIZE", (1, 1), (-1, -1), 7.5),
    ]))
    flow.append(t)
    flow.append(Spacer(1, 4 * mm))

    flow.append(Paragraph("Measurement protocol", styles["h2"]))
    body = (
        "All latencies are measured using the Cortex-M7 DWT cycle "
        "counter (32-bit free-running, no external timing). DWT "
        "overhead is 4 cycles per pair of samples (0.008 us at "
        "480 MHz) and is documented in the firmware banner. T1, T2 "
        "and T3 run for 1000 warmup iterations (discarded) followed "
        "by 10 000 measured iterations. T4 runs 100 one-shot PI "
        "scenarios without warmup (ADR-013 explicit exception, "
        "because PI must be observed on the very first event of a "
        "fresh kernel state, not after a steady-state warmup). "
        "Samples are stored in pre-allocated static arrays placed "
        "in AXI-SRAM (memory placement verified per run via the "
        "<i>bench_addr</i> banner table). No dynamic allocation is "
        "used by the benchmark code in any RTOS."
    )
    flow.append(Paragraph(body, styles["body"]))

    flow.append(Paragraph("Campaign protocol (ADR-013)", styles["h2"]))
    body = (
        "For every (RTOS, profile) combination the firmware is "
        "fully rebuilt, flashed and run five independent times "
        "(run01 through run05). The hash of the ELF and MAP "
        "produced by each rebuild is recorded and verified to be "
        "identical across runs of the same target (homogeneity "
        "check). The serial collector discards any stale bytes "
        "from the ST-Link VCP receive buffer before listening, so "
        "that no row from a previous firmware can leak into the "
        "current capture. The publication gate rejects a run unless "
        "ALL of the following hold: TIM2 setup readback matches the "
        "expected state; memory placement banner confirms every "
        "benchmark object lives in AXI-SRAM; iteration sequences "
        "are dense and ordered; T1/T2/T3 produce exactly 10 000 "
        "valid rows; T4 produces exactly 100 PI scenarios with "
        "100/100 passes; ELF and MAP SHA-256 match the campaign "
        "lock. The reported median per (RTOS, test) is the "
        "median-of-medians across the five runs; jitter is "
        "max - min in cycles; run_spread is the cycle span of the "
        "per-run medians (a strictly internal stability metric)."
    )
    flow.append(Paragraph(body, styles["body"]))

    flow.append(Paragraph(
        "On the interpretation of the <i>max (cyc)</i> column in "
        "the fair_perf profile: a fair_perf run does not suppress "
        "asynchronous interrupts (notably the 1 kHz SysTick at "
        "480 MHz), so a single iteration's measured cycle window "
        "can capture both the native operation and any asynchronous "
        "ISR that happens to land inside the same DWT sample. The "
        "primary cross-RTOS hot-path comparison is therefore based "
        "on <b>median, p95 and p99</b>, while <i>max</i> is reported "
        "for transparency rather than presented as the pure native "
        "operation cost. realistic_tickless suppresses the periodic "
        "tick when the system is idle but a CPU-bound loop in any "
        "RTOS can still be interrupted by other asynchronous events.",
        styles["body"]))

    flow.append(Paragraph(
        "Scope and non-claims (Phase 1)", styles["h2"]))
    body = (
        "Phase 1 publishes the DWT cycle-delta A4 - A1 as the "
        "headline figure for T1. This metric covers the path from "
        "ISR entry to the worker thread regaining execution, "
        "<b>excluding</b> the silicon hardware-event-to-ISR-entry "
        "portion (timer compare match, NVIC arbitration, exception "
        "stacking, vector fetch and ISR prologue). The figures in "
        "this report must not be quoted as the absolute external "
        "IRQ-to-thread latency that an external logic analyzer "
        "would observe at GPIO pins; see ADR-015 for the Phase 2 "
        "dual-source plan where the analyzer-based metric is "
        "introduced alongside the DWT one."
    )
    flow.append(Paragraph(body, styles["body"]))
    return flow


def headline_table(rows: list[AggRow],
                   styles: dict[str, ParagraphStyle]) -> Table:
    hdr = ["RTOS", "Test",
           "median (cyc)", "median (us)",
           "p95 (cyc)", "p99 (cyc)", "p99 (us)",
           "max (cyc)", "jitter", "run_spread"]
    body: list = [_hrow(hdr, styles)]
    for rtos in RTOSES:
        for test in TESTS:
            r = lookup_row(rows, rtos, test)
            body.append([
                RTOS_LABELS[rtos], test,
                f"{r.median}", f"{r.median_us:.3f}",
                f"{r.p95}", f"{r.p99}", f"{r.p99_us:.3f}",
                f"{r.max}", f"{r.jitter}", f"{r.run_spread}",
            ])
    t = Table(body, colWidths=[
        1.7 * cm, 2.4 * cm,
        1.55 * cm, 1.5 * cm,
        1.35 * cm, 1.35 * cm, 1.5 * cm,
        1.35 * cm, 1.15 * cm, 1.95 * cm,
    ])
    t.setStyle(std_table_style())
    t.setStyle(TableStyle([
        ("ALIGN", (0, 1), (1, -1), "LEFT"),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
    ]))
    return t


def compare_median_table(rows: list[AggRow],
                          styles: dict[str, ParagraphStyle]) -> Table:
    hdr = ["Test",
           "ChibiOS (cyc)", "FreeRTOS (cyc)", "Zephyr (cyc)",
           "ChibiOS (us)", "FreeRTOS (us)", "Zephyr (us)",
           "Lowest median (this test)"]
    body: list = [_hrow(hdr, styles)]
    style_extras: list[tuple] = []
    for ridx, test in enumerate(TESTS, start=1):
        c = lookup_row(rows, "chibios", test)
        f = lookup_row(rows, "freertos", test)
        z = lookup_row(rows, "zephyr", test)
        wins = {"ChibiOS": c.median, "FreeRTOS": f.median,
                 "Zephyr": z.median}
        lowest = min(wins, key=wins.get)
        body.append([
            test,
            f"{c.median}", f"{f.median}", f"{z.median}",
            f"{c.median_us:.3f}", f"{f.median_us:.3f}",
            f"{z.median_us:.3f}",
            lowest,
        ])
        col = {"ChibiOS": 1, "FreeRTOS": 2, "Zephyr": 3}[lowest]
        style_extras.append(
            ("TEXTCOLOR", (col, ridx), (col, ridx), GOOD))
        style_extras.append(
            ("FONTNAME", (col, ridx), (col, ridx), "Helvetica-Bold"))
        style_extras.append(
            ("TEXTCOLOR", (-1, ridx), (-1, ridx), GOOD))
        style_extras.append(
            ("FONTNAME", (-1, ridx), (-1, ridx), "Helvetica-Bold"))
    t = Table(body, colWidths=[
        2.6 * cm,
        1.6 * cm, 1.6 * cm, 1.6 * cm,
        1.6 * cm, 1.6 * cm, 1.6 * cm,
        2.0 * cm,
    ])
    t.setStyle(std_table_style())
    t.setStyle(TableStyle([
        ("ALIGN", (0, 1), (0, -1), "LEFT"),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
        ("ALIGN", (-1, 1), (-1, -1), "CENTER"),
    ] + style_extras))
    return t


def pi_table(rows: list[AggRow],
             styles: dict[str, ParagraphStyle]) -> Table:
    hdr = ["RTOS", "PI scenarios", "PI passed", "Result"]
    body: list[list[str]] = [hdr]
    style_extras: list[tuple] = []
    for ridx, rtos in enumerate(RTOSES, start=1):
        r = lookup_row(rows, rtos, "t4_mtx_pi")
        total = r.pi_total_total or 0
        passed = r.pi_passed_total or 0
        ok = passed == total and total > 0
        body.append([
            RTOS_LABELS[rtos], f"{total}", f"{passed}",
            "PASS" if ok else "FAIL",
        ])
        style_extras.append(
            ("TEXTCOLOR", (-1, ridx), (-1, ridx),
             GOOD if ok else BAD))
        style_extras.append(
            ("FONTNAME", (-1, ridx), (-1, ridx), "Helvetica-Bold"))
    t = Table(body, colWidths=[3.0 * cm, 3.5 * cm, 3.5 * cm,
                                 3.0 * cm])
    t.setStyle(std_table_style())
    t.setStyle(TableStyle([
        ("ALIGN", (0, 1), (0, -1), "LEFT"),
        ("ALIGN", (1, 1), (-2, -1), "RIGHT"),
        ("ALIGN", (-1, 1), (-1, -1), "CENTER"),
    ] + style_extras))
    return t


def fit_image(path: Path, max_w_cm: float,
              max_h_cm: float = 9.0) -> Image:
    img = Image(str(path))
    iw, ih = img.imageWidth, img.imageHeight
    max_w = max_w_cm * cm
    max_h = max_h_cm * cm
    s = min(max_w / iw, max_h / ih)
    img.drawWidth = iw * s
    img.drawHeight = ih * s
    return img


def section_profile(profile: str,
                     rows: list[AggRow],
                     styles: dict[str, ParagraphStyle]) -> list:
    flow: list = []
    flow.append(Paragraph(
        f"Results - profile {profile}", styles["h1"]))
    flow.append(Paragraph(
        f"<b>Profile semantics:</b> {PROFILE_LABELS[profile]} — "
        f"{PROFILE_ROLE[profile]}. All other publication invariants "
        "(480 MHz, VOS0, FLASH_ACR=0x34, I-Cache + D-Cache ON, -O2 "
        "effective flags, DWT measurement) are unchanged.",
        styles["body"]))

    flow.append(Paragraph("Aggregate results", styles["h2"]))
    flow.append(Paragraph(
        "Median, percentile, jitter and run_spread for each "
        "(RTOS, test) cell, computed across 10 000 iterations per "
        "run x 5 runs (T1/T2/T3) or 100 scenarios per run x 5 runs "
        "(T4). run_spread = 0 cycles on every cell means the median of "
        "each individual run was bit-identical to the median of every "
        "other run for that (RTOS, test) -- a per-run stability metric, "
        "NOT an absence of variance: the p95 / p99 / max columns below "
        "capture the real distribution (e.g. an asynchronous SysTick "
        "tick landing in-sample appears as a max well above the median), "
        "so the flat run_spread reflects reproducible medians, not "
        "over-clean data.",
        styles["small"]))
    flow.append(headline_table(rows, styles))
    flow.append(Spacer(1, 4 * mm))

    flow.append(Paragraph("Cross-RTOS comparison", styles["h2"]))
    flow.append(compare_median_table(rows, styles))
    flow.append(Paragraph(
        "Method: median-of-medians over five validated firmware "
        "loads; DWT CYCCNT cycle deltas; lower is better for these "
        "latency tests. Results apply only to the benchmark "
        "configuration stated in this report.", styles["caption"]))
    flow.append(Spacer(1, 4 * mm))

    flow.append(Paragraph("Priority-inheritance proof (T4)",
                            styles["h2"]))
    flow.append(pi_table(rows, styles))
    flow.append(PageBreak())

    flow.append(Paragraph("Per-test plots", styles["h2"]))
    for test in TESTS:
        flow.append(Paragraph(TEST_LABELS[test], styles["h3"]))
        agg = PLOTS / f"{profile}_{test}_aggregate.png"
        per = PLOTS / f"{profile}_{test}_per_run.png"
        block: list = []
        if agg.exists():
            block.append(fit_image(agg, 15.5, 8.0))
            block.append(Paragraph(
                f"Aggregate distribution - {profile} / {test}",
                styles["caption"]))
        if per.exists():
            block.append(fit_image(per, 15.5, 8.0))
            block.append(Paragraph(
                f"Per-run medians - {profile} / {test}",
                styles["caption"]))
        flow.append(KeepTogether(block))

    # T4 PI plot, only if present.
    pi_plot = PLOTS / f"{profile}_t4_pi.png"
    if pi_plot.exists():
        flow.append(Paragraph(
            "Priority-inheritance event distribution",
            styles["h3"]))
        flow.append(fit_image(pi_plot, 15.5, 8.0))
        flow.append(Paragraph(
            f"T4 priority-inheritance scenarios - {profile}",
            styles["caption"]))
    return flow


def section_cross_profile(styles: dict[str, ParagraphStyle],
                            fair: list[AggRow],
                            tickless: list[AggRow]) -> list:
    flow: list = [Paragraph(
        "Cross-profile delta (baseline fair_perf -> headline "
        "realistic_tickless)", styles["h1"])]
    flow.append(Paragraph(
        "Per-cell difference of the median latency from the "
        "controlled-isolation baseline (fair_perf) to the headline "
        "profile (realistic_tickless). The arithmetic direction is "
        "baseline-to-headline, so a positive number means the headline "
        "profile is slower. The notable swing is T1 for FreeRTOS, where "
        "the median increases most from the baseline to the headline "
        "profile under this benchmark configuration; the delta is reported "
        "as measured, without internal root-cause attribution.",
        styles["body"]))

    hdr = ["RTOS", "Test",
           "fair_perf median (cyc)",
           "realistic_tickless median (cyc)",
           "delta (cyc)", "delta (us)"]
    body: list = [_hrow(hdr, styles)]
    style_extras: list[tuple] = []
    ridx = 0
    for rtos in RTOSES:
        for test in TESTS:
            ridx += 1
            a = lookup_row(fair, rtos, test).median
            b = lookup_row(tickless, rtos, test).median
            d = b - a
            d_us = d / CPU_HZ * 1e6
            body.append([
                RTOS_LABELS[rtos], test, f"{a}", f"{b}",
                f"{d:+d}", f"{d_us:+.3f}",
            ])
            if d > 50:
                style_extras.append(
                    ("TEXTCOLOR", (-2, ridx), (-1, ridx), BAD))
                style_extras.append(
                    ("FONTNAME", (-2, ridx), (-1, ridx),
                     "Helvetica-Bold"))
            elif d < -10:
                style_extras.append(
                    ("TEXTCOLOR", (-2, ridx), (-1, ridx), GOOD))
    t = Table(body, colWidths=[
        2.0 * cm, 2.8 * cm,
        3.3 * cm, 3.7 * cm,
        2.0 * cm, 2.0 * cm,
    ])
    t.setStyle(std_table_style())
    t.setStyle(TableStyle([
        ("ALIGN", (0, 1), (1, -1), "LEFT"),
        ("ALIGN", (2, 1), (-1, -1), "RIGHT"),
    ] + style_extras))
    flow.append(t)
    return flow


def footprint_table(rows: list[FootprintRow],
                    styles: dict[str, ParagraphStyle]) -> Table:
    hdr = ["RTOS", "code size (B)", "static RAM used (B)",
           "tail reservation (B, info)"]
    body: list = [_hrow(hdr, styles)]
    by_rtos = {r.rtos: r for r in rows}
    present = [by_rtos[x] for x in RTOSES if x in by_rtos]
    min_code = min((r.code_size for r in present), default=None)
    min_ram = min((r.ram_static_used for r in present), default=None)
    style_extras: list[tuple] = []
    for ridx, rtos in enumerate(RTOSES, start=1):
        r = by_rtos.get(rtos)
        if r is None:
            body.append([RTOS_LABELS[rtos], "n/a", "n/a", "n/a"])
            continue
        tail = (f"{r.tail_reservation}"
                if r.tail_reservation is not None else "n/a")
        body.append([RTOS_LABELS[rtos], f"{r.code_size}",
                     f"{r.ram_static_used}", tail])
        if r.code_size == min_code:
            style_extras += [
                ("TEXTCOLOR", (1, ridx), (1, ridx), GOOD),
                ("FONTNAME", (1, ridx), (1, ridx), "Helvetica-Bold")]
        if r.ram_static_used == min_ram:
            style_extras += [
                ("TEXTCOLOR", (2, ridx), (2, ridx), GOOD),
                ("FONTNAME", (2, ridx), (2, ridx), "Helvetica-Bold")]
    t = Table(body, colWidths=[3.2 * cm, 3.6 * cm, 4.4 * cm,
                                4.8 * cm])
    t.setStyle(std_table_style())
    t.setStyle(TableStyle([
        ("ALIGN", (0, 1), (0, -1), "LEFT"),
        ("ALIGN", (1, 1), (-1, -1), "RIGHT"),
    ] + style_extras))
    return t


def section_footprint(styles: dict[str, ParagraphStyle],
                      fair_fp: list[FootprintRow],
                      tickless_fp: list[FootprintRow]) -> list:
    flow: list = [Paragraph("Firmware footprint", styles["h1"])]
    flow.append(Paragraph(
        "Static firmware size indicators extracted from the "
        "manifest-bound publication ELF of each (RTOS, profile) - the "
        "same binary whose SHA-256 is locked in the campaign manifest "
        "and listed in the Integrity section. Metric definitions are "
        "binding per ADR-023.", styles["body"]))
    flow.append(Paragraph(
        "<b>Code size</b> = .text + .rodata (read-only code and "
        "constants in flash). <b>Static RAM used</b> = .data + .bss + "
        "noinit, with the ChibiOS .heap linker reservation excluded "
        "(CH_CFG_USE_HEAP=FALSE, no allocation) and the per-RTOS "
        "committed main/process stacks added where they are not "
        "already a labelled section. <b>Tail reservation</b> is "
        "informational only: spare RAM held for the descending main "
        "stack (FreeRTOS), runtime k_thread_create stacks (Zephyr) or "
        "the linker heap reservation (ChibiOS); it is NOT part of the "
        "static-RAM figure.", styles["small"]))

    for profile, rows in (("fair_perf", fair_fp),
                          ("realistic_tickless", tickless_fp)):
        flow.append(Paragraph(PROFILE_LABELS[profile], styles["h2"]))
        flow.append(footprint_table(rows, styles))
        srcs = {r.elf_source for r in rows}
        matched = [r.rtos for r in rows if r.lock_sha256_match]
        if srcs == {"raw"} and rows and len(matched) == len(rows):
            note = (f"Computed from results/raw/&lt;rtos&gt;_{profile}"
                    "_run01.elf; every ELF SHA-256 matches the "
                    "campaign lock.")
        else:
            note = ("Source: " + ", ".join(sorted(srcs))
                    + "; SHA-256 lock match: "
                    + (", ".join(matched) if matched else "none") + ".")
        flow.append(Paragraph(note, styles["caption"]))
        flow.append(Spacer(1, 4 * mm))

    flow.append(Paragraph(
        "libc disclaimer (ADR-009): the three RTOSes intentionally "
        "link three different C libraries - ChibiOS newlib (full), "
        "FreeRTOS newlib-nano, Zephyr picolibc. The code-size figure "
        "therefore bundles kernel + HAL + libc and is not a pure "
        "kernel-text comparison; a per-archive breakdown is a planned "
        "follow-up.", styles["small"]))
    return flow


def section_integrity(styles: dict[str, ParagraphStyle]) -> list:
    flow: list = [Paragraph(
        "Integrity and reproducibility", styles["h1"])]
    flow.append(Paragraph(
        "The publication gate is enforced at three layers: "
        "(1) per-run validation, captured in the "
        "<i>*.validated.json</i> manifest written by the collector "
        "alongside the CSV; (2) per-campaign lock, written by the "
        "lab campaign script after every (RTOS, profile) is "
        "complete; (3) build reproducibility, expressed as "
        "ELF / MAP SHA-256 homogeneity across the five runs of a "
        "given target. All numbers in this report come exclusively "
        "from validated runs.", styles["body"]))

    flow.append(Paragraph(
        "Campaign locks - ELF and MAP SHA-256",
        styles["h2"]))
    for profile in PROFILES:
        lock = load_lock(profile)
        flow.append(Paragraph(profile, styles["h3"]))
        hdr = ["RTOS", "Artefact", "SHA-256 (truncated)"]
        body_rows: list[list[str]] = [hdr]
        for rtos in RTOSES:
            entry = lock["rtoses"][rtos]
            body_rows.append([RTOS_LABELS[rtos], "ELF",
                               entry["elf_sha256"][:48] + "..."])
            body_rows.append(["", "MAP",
                               entry["map_sha256"][:48] + "..."])
        t = Table(body_rows, colWidths=[2.5 * cm, 2.5 * cm,
                                          11.0 * cm])
        t.setStyle(std_table_style())
        t.setStyle(TableStyle([
            ("ALIGN", (0, 1), (-1, -1), "LEFT"),
            ("FONTNAME", (2, 1), (2, -1), "Courier"),
            ("FONTSIZE", (2, 1), (2, -1), 8.0),
        ]))
        flow.append(t)
        flow.append(Spacer(1, 2 * mm))

    flow.append(Paragraph(
        "Per-run validation status", styles["h2"]))
    hdr = ["RTOS", "Profile", "Run", "Validated",
           "clock (Hz)", "VOS", "FLASH_ACR", "tickless", "WFI"]
    body_rows: list[list[str]] = [hdr]
    style_extras: list[tuple] = []
    ridx = 0
    for profile in PROFILES:
        for rtos in RTOSES:
            for run in ("01", "02", "03", "04", "05"):
                ridx += 1
                v = load_validated(rtos, profile, run)
                ok = bool(v.get("validated", False))
                body_rows.append([
                    RTOS_LABELS[rtos], profile, run,
                    "yes" if ok else "NO",
                    str(v.get("system_clock_hz", "")),
                    v.get("vos_level", ""),
                    v.get("flash_acr", ""),
                    v.get("tickless", ""),
                    v.get("wfi_in_idle", ""),
                ])
                if not ok:
                    style_extras.append(
                        ("TEXTCOLOR", (3, ridx), (3, ridx), BAD))
                else:
                    style_extras.append(
                        ("TEXTCOLOR", (3, ridx), (3, ridx), GOOD))
    t = Table(body_rows, colWidths=[
        1.8 * cm, 2.8 * cm, 0.9 * cm, 1.6 * cm,
        2.2 * cm, 1.2 * cm, 2.0 * cm,
        1.7 * cm, 1.3 * cm,
    ])
    t.setStyle(std_table_style())
    t.setStyle(TableStyle([
        ("ALIGN", (0, 1), (-1, -1), "CENTER"),
    ] + style_extras))
    flow.append(t)
    return flow


def section_conclusions(styles: dict[str, ParagraphStyle],
                         fair: list[AggRow],
                         tickless: list[AggRow]) -> list:
    flow: list = [Paragraph("Conclusions", styles["h1"])]

    # Headline = realistic_tickless; baseline = fair_perf.
    c1 = lookup_row(tickless, "chibios", "t1_irq").median
    f1 = lookup_row(tickless, "freertos", "t1_irq").median
    z1 = lookup_row(tickless, "zephyr", "t1_irq").median
    c2 = lookup_row(tickless, "chibios", "t2_handoff").median
    f2 = lookup_row(tickless, "freertos", "t2_handoff").median
    z2 = lookup_row(tickless, "zephyr", "t2_handoff").median
    c3 = lookup_row(tickless, "chibios", "t3_mtx_uncont").median
    f3 = lookup_row(tickless, "freertos", "t3_mtx_uncont").median
    z3 = lookup_row(tickless, "zephyr", "t3_mtx_uncont").median
    c4 = lookup_row(tickless, "chibios", "t4_mtx_pi").median
    f4 = lookup_row(tickless, "freertos", "t4_mtx_pi").median
    z4 = lookup_row(tickless, "zephyr", "t4_mtx_pi").median
    c1_fp = lookup_row(fair, "chibios", "t1_irq").median
    f1_fp = lookup_row(fair, "freertos", "t1_irq").median
    z1_fp = lookup_row(fair, "zephyr", "t1_irq").median

    bullets = [
        f"<b>T1 - IRQ -> thread:</b> Under realistic_tickless "
        f"(headline), ChibiOS showed the lowest median at {c1} cycles, "
        f"against FreeRTOS {f1} and Zephyr {z1}. The fair_perf "
        f"controlled baseline preserves the ranking (ChibiOS {c1_fp}, "
        f"FreeRTOS {f1_fp}, Zephyr {z1_fp}). The FreeRTOS rise from "
        f"{f1_fp} to {f1} ({f1 - f1_fp:+d} cycles) is the largest "
        "profile-to-profile change under this benchmark configuration, "
        f"reported as measured; ChibiOS ({c1 - c1_fp:+d}) and Zephyr "
        f"({z1 - z1_fp:+d}) move much less. Internal root-cause "
        "attribution is outside Phase 1 scope.",
        f"<b>T2 - Thread handoff:</b> ChibiOS showed the lowest "
        f"median latency at {c2} cycles, against FreeRTOS {f2} and "
        f"Zephyr {z2}. The measured median ratio in this test is "
        "approximately 4x under this benchmark configuration; the "
        "result is reported as measured, without attributing the delta "
        "to a single internal implementation cause.",
        f"<b>T3 - Mutex uncontended:</b> ChibiOS {c3} cycles is the "
        f"shortest fast path; Zephyr {z3} is second. The test measures "
        "mutex lock/unlock, so the FreeRTOS mutex API "
        "(xSemaphoreTake/Give on a statically-created mutex) is the "
        "correct primitive under test; "
        f"its higher {f3}-cycle path reflects that FreeRTOS implements "
        "mutexes on its queue/semaphore core, which is intrinsic to the "
        "kernel and not a configuration the benchmark imposed.",
        f"<b>T4 - Mutex contended + PI:</b> ChibiOS showed the "
        f"lowest contended-path latency at {c4} cycles, with "
        f"FreeRTOS at {f4} and Zephyr at {z4}. Priority inheritance "
        "is correct in all three kernels: 500/500 PI scenarios "
        "pass per RTOS per profile.",
        "<b>Reproducibility:</b> run_spread is zero cycles on every "
        "(RTOS, test) cell across the campaign. All 30 "
        "run01..run05 captures (3 RTOS x 2 profiles x 5 firmware "
        "loads) passed the publication gate; the six run00 warmup "
        "captures are discarded.",
        "<b>Honest scope:</b> Phase 1 publishes the DWT cycle delta "
        "A4 - A1 for T1, not the hardware-event-to-thread external "
        "latency. The hardware-routed IRQ entry path "
        "(NVIC, stacking, vector fetch) is intentionally excluded "
        "and will be measured by the logic-analyzer in Phase 2 per "
        "ADR-015.",
    ]
    for b in bullets:
        flow.append(Paragraph(f"&bull; {b}", styles["body"]))
        flow.append(Spacer(1, 1 * mm))
    return flow


def section_appendix_build(styles: dict[str, ParagraphStyle]) -> list:
    flow: list = [Paragraph(
        "Appendix A - Build commands", styles["h1"])]
    flow.append(Paragraph(
        "Each port has a single, deterministic build entry point. "
        "All ports honour the <i>PROFILE</i> selector (fair_perf, "
        "realistic_tickless, debug_dev) so that the same source tree "
        "produces the publication firmware variants without "
        "ambiguity.", styles["body"]))

    code_blocks = [
        ("ChibiOS",
         "cd chibios/benchmark_chibios\n"
         "make PROFILE=fair_perf -j\n"
         "make PROFILE=realistic_tickless -j"),
        ("FreeRTOS",
         "cd freertos/benchmark_freertos\n"
         "cmake -B build/fair_perf -G \"MinGW Makefiles\" "
         "-DPROFILE=fair_perf\n"
         "cmake --build build/fair_perf\n"
         "cmake -B build/realistic_tickless -G \"MinGW Makefiles\" "
         "-DPROFILE=realistic_tickless\n"
         "cmake --build build/realistic_tickless"),
        ("Zephyr (board stm32h750b_dk)",
         "cd zephyr\n"
         ".venv/Scripts/activate.bat   (Windows)\n"
         ". .venv/bin/activate         (Linux)\n"
         "west build -d build/fair_perf -b stm32h750b_dk "
         "benchmark_zephyr -p always -- "
         "-DPROFILE=fair_perf\n"
         "west build -d build/realistic_tickless -b "
         "stm32h750b_dk benchmark_zephyr -p always -- "
         "-DPROFILE=realistic_tickless"),
    ]
    for label, code in code_blocks:
        flow.append(Paragraph(label, styles["h3"]))
        flow.append(Paragraph(
            code.replace("\n", "<br/>"), styles["mono"]))
    return flow


def section_appendix_pins(styles: dict[str, ParagraphStyle]) -> list:
    flow: list = [Paragraph(
        "Appendix B - GPIO mapping (logic-analyzer)", styles["h1"])]
    flow.append(Paragraph(
        "Six GPIO signals are exposed on the STMod+ connector P1 "
        "of the STM32H750B-DK for logic-analyzer capture. In Phase "
        "1 they are routed by the firmware for parity with the "
        "future Phase 2 dual-source measurement and are not part "
        "of the reported headline. See ADR-007 for the rationale "
        "behind the pin assignment.", styles["body"]))
    rows = [
        ["Signal", "MCU pin", "STMod+ P1 pin", "Role"],
        ["A0_HW", "PA0", "1", "TIM2 CH1 PWM mode 2 - hardware IRQ "
                              "stimulus for T1"],
        ["A1", "PH1", "17", "LOW_LOCK - mutex lock by LOW (T4)"],
        ["A2", "PH4", "19", "HIGH_WAIT - HIGH blocked on mutex (T4)"],
        ["A3", "PH8", "20", "LOW_UNLOCK - LOW releases mutex (T4)"],
        ["A4", "PH12", "11", "HIGH_ACQUIRE - HIGH acquires mutex (T4)"],
        ["MEDIUM_RUN", "PI11", "18", "MEDIUM scheduled (PI excludes "
                                      "MEDIUM, T4)"],
    ]
    t = Table(rows, colWidths=[
        2.6 * cm, 2.0 * cm, 2.8 * cm, 8.6 * cm,
    ])
    t.setStyle(std_table_style())
    t.setStyle(TableStyle([
        ("ALIGN", (0, 1), (-1, -1), "LEFT"),
        ("VALIGN", (0, 1), (-1, -1), "TOP"),
    ]))
    flow.append(t)
    return flow


def section_conditions(styles: dict[str, ParagraphStyle],
                       sample_banner: dict[str, str]) -> list:
    flow: list = [Paragraph("Benchmark conditions", styles["h1"])]
    flow.append(Paragraph(
        "The comparison below is valid only under the exact "
        "conditions stated here.", styles["body"]))
    published = PUBLICATION_STATUS == "published"
    repo = (PUBLIC_REPOSITORY_URL if published
            else "pending public release (planned tag phase1-v1.0)")
    logs = (PUBLIC_RAW_LOGS_URL if published
            else "pending public release (curated archive prepared, "
                 "committed in-repo)")
    tcell = styles["tcell"]
    def v(s: str) -> Paragraph:
        """Wrap value cell as Paragraph so long strings wrap to the
        column width instead of overflowing past the page right
        edge (fix 2026-05-20: pre-fix this table had 3 cells whose
        value was a flat string and ReportLab does not auto-wrap
        flat strings -> text was truncated off the page on p.6)."""
        return Paragraph(s, tcell)
    rows = [
        ["Item", "Value"],
        ["Board / MCU",
            v("STM32H750B-DK / STM32H750XBH6 (Cortex-M7, DP-FPU)")],
        ["CPU clock / cache / flash",
            v("480 MHz (VOS0); I-Cache + D-Cache ON; "
              "FLASH_ACR = 0x34 (4 wait states)")],
        ["Compiler / optimization",
            v("arm-none-eabi-gcc 14.2.Rel1; -O2 -fomit-frame-pointer "
              "-falign-functions=16; no LTO")],
        ["RTOS versions / source",
            v("ChibiOS 21.11.5 / RT 7.0.6 (git tag ver21.11.5); FreeRTOS "
              "V11.3.0 (tag V11.3.0); Zephyr 4.4.0 (tag v4.4.0)")],
        ["Profile configuration",
            v("realistic_tickless (headline): tickless ON, WFI ON. "
              "fair_perf (controlled-isolation baseline): tickless OFF, "
              "WFI OFF. No asserts, debug or logging in the measured "
              "path.")],
        ["Measurement method",
            v("Cortex-M7 DWT CYCCNT cycle deltas inside the firmware. "
              "Phase 1 publishes A4 - A1 (ISR entry -> thread "
              "running); the external hardware-event-to-ISR portion "
              "is Phase 2 (logic analyzer).")],
        ["Iterations",
            v("1000 warmup (discarded) + 10000 valid per run for "
              "T1/T2/T3; 100 one-shot scenarios for T4; 5 validated "
              "firmware loads per (RTOS, profile).")],
        ["Repository", v(repo)],
        ["Raw logs", v(logs)],
        ["Scope",
            v("Results apply only to this benchmark configuration.")],
    ]
    t = Table(rows, colWidths=[4.2 * cm, 12.8 * cm])
    t.setStyle(std_table_style())
    t.setStyle(TableStyle([
        ("ALIGN", (0, 1), (-1, -1), "LEFT"),
        ("VALIGN", (0, 1), (-1, -1), "TOP"),
    ]))
    flow.append(t)
    if PUBLICATION_STATUS != "published":
        flow.append(Spacer(1, 3 * mm))
        flow.append(Paragraph(
            "<b>Release candidate - final legal review required before "
            "external publication.</b> The curated raw-log archive is "
            "prepared and committed in-repo, but is not yet published at "
            "an immutable public URL; that URL resolves when the release "
            "tag is created. Reproducibility is from source under the "
            "stated conditions.", styles["body"]))
    return flow


def section_legal_notice(styles: dict[str, ParagraphStyle]) -> list:
    flow: list = [Paragraph(
        "Legal notice and trademarks", styles["h1"])]
    flow.append(Paragraph(
        "FreeRTOS is a trademark of Amazon Web Services, Inc. "
        "Zephyr and Zephyr Project are trademarks of The Linux "
        "Foundation. All other trademarks are the property of "
        "their respective owners. Chibilogic s.r.l. is not "
        "affiliated with, endorsed by, or sponsored by Amazon Web "
        "Services, the FreeRTOS project, the Zephyr Project, or "
        "The Linux Foundation. The comparison is based on "
        "independently executed benchmarks under the stated test "
        "conditions.", styles["body"]))
    flow.append(Spacer(1, 3 * mm))
    flow.append(Paragraph(
        "This document is not legal advice; a final legal review "
        "is recommended before official publication.",
        styles["body"]))
    flow.append(Spacer(1, 3 * mm))
    flow.append(Paragraph(
        "FreeRTOS and Zephyr are excellent RTOS projects with "
        "different design goals. This comparison focuses only on "
        "real-time latency under the tested conditions.",
        styles["body"]))
    return flow


# ---------------------------------------------------------------------
# Banner parser
# ---------------------------------------------------------------------

def parse_banner(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8",
                                errors="ignore").splitlines():
        m = re.match(r"\s+([A-Za-z0-9_>\-\s]+?)\s+:\s+(.+?)\s*$",
                      line)
        if m:
            key = m.group(1).strip()
            val = m.group(2).strip()
            if key and val and key not in out:
                out[key] = val
        elif "SystemClock" in line and ":" in line:
            k, v = line.split(":", 1)
            out["SystemClock"] = v.strip().split()[0] + " Hz"
    return out


# ---------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------

def load_zephyr_config(profile: str) -> dict:
    with open(SUMMARY / "zephyr_config" / f"{profile}.json",
              encoding="utf-8") as fh:
        return json.load(fh)


def section_appendix_zephyr_config(
        styles: dict[str, ParagraphStyle]) -> list:
    flow: list = [Paragraph(
        "Appendix C - Zephyr resolved configuration", styles["h1"])]
    flow.append(Paragraph(
        "Latency-relevant Kconfig symbols as RESOLVED in the generated "
        "<i>.config</i> for each publishable profile (not the raw "
        "<i>prj.conf</i> fragments). <i>not set</i> means the symbol is "
        "absent from the generated configuration. Snapshotted from "
        "<i>zephyr/build/&lt;profile&gt;/zephyr/.config</i> by "
        "<i>scripts/zephyr_config_snapshot.py</i>.", styles["body"]))
    flow.append(Spacer(1, 3 * mm))
    cf = load_zephyr_config("fair_perf")["symbols"]
    ct = load_zephyr_config("realistic_tickless")["symbols"]
    rows = [_hrow(["Kconfig symbol", "fair_perf",
                   "realistic_tickless"], styles)]
    for s in cf:
        rows.append([Paragraph(s, styles["tcell"]),
                     Paragraph(str(cf[s]), styles["tcell"]),
                     Paragraph(str(ct[s]), styles["tcell"])])
    t = Table(rows, colWidths=[8.0 * cm, 4.0 * cm, 4.0 * cm])
    t.setStyle(std_table_style())
    t.setStyle(TableStyle([
        ("ALIGN", (1, 1), (-1, -1), "LEFT"),
        ("FONTNAME", (0, 1), (0, -1), "Courier"),
        ("FONTSIZE", (0, 1), (-1, -1), 8),
    ]))
    flow.append(t)
    return flow


def validate_publication_metadata() -> None:
    """Publication gate: a 'published' report MUST carry real
    repository and raw-log URLs, else fail fast rather than
    silently emitting a published-looking PDF with 'pending'
    placeholders (Codex codereview-001 IMPORTANT 1)."""
    if PUBLICATION_STATUS not in ("draft", "published"):
        raise ValueError(
            f"invalid PUBLICATION_STATUS: {PUBLICATION_STATUS!r}")
    if PUBLICATION_STATUS == "published":
        missing = []
        if not PUBLIC_REPOSITORY_URL:
            missing.append("PUBLIC_REPOSITORY_URL")
        if not PUBLIC_RAW_LOGS_URL:
            missing.append("PUBLIC_RAW_LOGS_URL")
        if missing:
            raise ValueError(
                "published report requires " + ", ".join(missing))
    # ADR-023: the footprint section is mandatory; a report cannot be
    # built without the per-profile footprint JSON (generated by
    # report_results.py --footprint).
    fp_missing = [
        p for p in PROFILES
        if not (SUMMARY / "footprint" / f"{p}_footprint.json").exists()
    ]
    if fp_missing:
        raise FileNotFoundError(
            "footprint JSON missing for profile(s): "
            + ", ".join(fp_missing)
            + ". Run 'report_results.py --footprint' (ADR-023) before "
              "building the report.")
    # The Zephyr resolved-config appendix is mandatory: the report must
    # show resolved Kconfig, not raw prj.conf fragments.
    zc_missing = [
        p for p in PROFILES
        if not (SUMMARY / "zephyr_config" / f"{p}.json").exists()
    ]
    if zc_missing:
        raise FileNotFoundError(
            "Zephyr resolved-config JSON missing for profile(s): "
            + ", ".join(zc_missing)
            + ". Run 'report_results.py --footprint' (which also "
              "snapshots the resolved Zephyr Kconfig) after a Zephyr "
              "build, before building the report.")


def main() -> int:
    validate_publication_metadata()
    DOCS.mkdir(parents=True, exist_ok=True)

    fair = load_aggregate("fair_perf")
    tickless = load_aggregate("realistic_tickless")
    fair_fp = load_footprint("fair_perf")
    tickless_fp = load_footprint("realistic_tickless")
    sample_banner = parse_banner(
        RAW / "chibios_fair_perf_run01.banner.txt")

    styles = make_styles()
    doc = make_doc(OUTPUT_PDF)

    flow: list = []
    # Cover
    flow += section_cover(styles)
    # Switch to body template for the rest.
    flow.append(NextPageTemplate("body"))
    flow.append(PageBreak())
    # Abstract
    flow += section_abstract(styles, fair, tickless)
    flow.append(PageBreak())
    # Environment
    flow += section_environment(styles, sample_banner)
    flow.append(PageBreak())
    # Methodology
    flow += section_methodology(styles)
    flow.append(PageBreak())
    # Benchmark conditions (legal-compliance block, adjacent to tables)
    flow += section_conditions(styles, sample_banner)
    flow.append(PageBreak())
    # Results realistic_tickless (headline)
    flow += section_profile("realistic_tickless", tickless, styles)
    flow.append(PageBreak())
    # Results fair_perf (controlled-isolation baseline)
    flow += section_profile("fair_perf", fair, styles)
    flow.append(PageBreak())
    # Cross profile
    flow += section_cross_profile(styles, fair, tickless)
    flow.append(PageBreak())
    # Firmware footprint (ADR-023)
    flow += section_footprint(styles, fair_fp, tickless_fp)
    flow.append(PageBreak())
    # Integrity
    flow += section_integrity(styles)
    flow.append(PageBreak())
    # Conclusions
    flow += section_conclusions(styles, fair, tickless)
    flow.append(PageBreak())
    # Legal notice and trademarks (discuss.txt sec. 8 + sec. 5)
    flow += section_legal_notice(styles)
    flow.append(PageBreak())
    # Appendices
    flow += section_appendix_build(styles)
    flow.append(PageBreak())
    flow += section_appendix_pins(styles)
    flow.append(PageBreak())
    flow += section_appendix_zephyr_config(styles)

    doc.build(flow)
    print(f"OK: {OUTPUT_PDF}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
