<#
lab_campaign.ps1 -- full 5x3 DWT campaign launcher with build-once
per (rtos, profile) and artefact-hash lock.

Flow (Codex round-3 2b):
  1. For each rtos: call lab_smoke.ps1 -OnlyBuild to produce the
     ELF / MAP artefacts via the Makefile wrappers. Compute the
     SHA256 of both and stash in $campaignHashes.
  2. Write `results/manifest/<profile>_campaign.lock.json` with
     the full per-rtos hash list, publication mode, and a UTC
     timestamp.
  3. For each rtos: run run00 (warmup, MANDATORY for
     publishable per ADR-013; -SkipWarmup is exploratory /
     non-publishable only) + run01..run05
     via lab_smoke.ps1 -SkipBuild -ElfFile -MapFile
     -ExpectedElfSha -ExpectedMapSha. lab_smoke aborts before
     flashing if the actual file hash drifted from the lock.
  4. At the end: run `report_results.py --publication-gate` and
     `plot_results.py` on the profile.

The campaign-lock model guarantees that all 6 runs of a (rtos,
profile) flashed the same firmware; if the lock breaks the
campaign aborts before any misleading "validated" stamp is
emitted by the collector.

Usage:
    .\scripts\lab_campaign.ps1 -RepoRoot D:\...\rtos-benchmark `
        -Port COM5 -Profile fair_perf -PublicationMode dwt_only
#>

[CmdletBinding()]
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$Port    = "COM5",

    # Codex round 2026-05-14-bucket-c4-lab-scripts-audit-001
    # IMPORTANT 2 — bind-time validation matching ADR-011.
    [ValidateSet("fair_perf", "realistic_tickless",
                 "debug_dev")]
    [string]$Profile = "fair_perf",

    [int]$Baud       = 115200,
    [int]$CollectorTimeoutSec = 600,

    # Codex round 2026-05-14-bucket-c4-lab-scripts-audit-001
    # IMPORTANT 2 — bind-time validation. Every element of
    # $Rtoses must be one of the 3 supported ports; an
    # invalid value fails the script before any build is
    # attempted.
    [ValidateSet("chibios", "freertos", "zephyr")]
    [string[]]$Rtoses = @("chibios", "freertos", "zephyr"),

    [int[]]$RunIds   = 1..5,
    # -SkipWarmup is for exploratory / non-publishable
    # captures only. Publishable profiles
    # (`fair_perf` / `realistic_tickless`) require a
    # validated run00 capture per ADR-013; the
    # `report_results.py --publication-gate` fails if
    # run00 is missing for any (rtos, profile).
    [switch]$SkipWarmup,
    [switch]$SkipReport,

    # Skip the entire capture phase and only run report + plot on
    # the .csv / .validated.json files already present under
    # results/raw. Useful to recover from a previous campaign that
    # finished captures but failed at the report stage.
    [switch]$OnlyReport,

    # 2b-C (Codex round-3) — campaign publication mode. Phase 1
    # default is dwt_only (ADR-015). All lab_smoke invocations
    # below inherit the same mode so the per-run validated.json
    # passes the report_results.py homogeneity check.
    [ValidateSet("la", "dwt_only")]
    [string]$PublicationMode = "dwt_only"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Banner {
    param([string]$Message)
    Write-Host ""
    Write-Host ("=" * 60) -ForegroundColor Magenta
    Write-Host $Message -ForegroundColor Magenta
    Write-Host ("=" * 60) -ForegroundColor Magenta
}

function Get-CanonicalElf {
    # Same Makefile-wrapper layout used by lab_smoke.ps1's
    # Get-XxxElf functions; replicated here so lab_campaign is
    # self-contained.
    param([string]$Rtos, [string]$Profile, [string]$RepoRoot)
    switch ($Rtos) {
        "chibios"  { return (Join-Path $RepoRoot "chibios\benchmark_chibios\build\$Profile\benchmark_chibios.elf") }
        "freertos" { return (Join-Path $RepoRoot "freertos\benchmark_freertos\build\$Profile\benchmark_freertos.elf") }
        "zephyr"   { return (Join-Path $RepoRoot "zephyr\build\$Profile\zephyr\zephyr.elf") }
        default    { throw "Unknown rtos: $Rtos" }
    }
}

function Get-CanonicalMap {
    param([string]$Rtos, [string]$Profile, [string]$RepoRoot)
    switch ($Rtos) {
        "chibios"  { return (Join-Path $RepoRoot "chibios\benchmark_chibios\build\$Profile\benchmark_chibios.map") }
        "freertos" { return (Join-Path $RepoRoot "freertos\benchmark_freertos\build\$Profile\benchmark_freertos.map") }
        "zephyr"   { return (Join-Path $RepoRoot "zephyr\build\$Profile\zephyr\zephyr.map") }
        default    { throw "Unknown rtos: $Rtos" }
    }
}

function Get-FileSha256Lower {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        throw "File not found: $Path"
    }
    return (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLower()
}

$smokeScript = Join-Path $PSScriptRoot "lab_smoke.ps1"
if (-not (Test-Path $smokeScript)) {
    throw "lab_smoke.ps1 not found at $smokeScript"
}

$campaignStartTime = Get-Date

# ---------------------------------------------------------------------
# Phase 1: build-once + artefact hash lock
# ---------------------------------------------------------------------

$campaignHashes = @{}

if (-not $OnlyReport) {
    foreach ($rtos in $Rtoses) {
        Write-Banner "$rtos / $Profile / build-once (lock artefact hash)"
        & $smokeScript `
            -RepoRoot $RepoRoot `
            -Rtos $rtos `
            -Port $Port `
            -Baud $Baud `
            -CollectorTimeoutSec $CollectorTimeoutSec `
            -Profile $Profile `
            -PublicationMode $PublicationMode `
            -OnlyBuild
        if ($LASTEXITCODE -ne 0) {
            throw "FAIL: build-once for $rtos / $Profile failed"
        }

        $elf = Get-CanonicalElf -Rtos $rtos -Profile $Profile -RepoRoot $RepoRoot
        $map = Get-CanonicalMap -Rtos $rtos -Profile $Profile -RepoRoot $RepoRoot
        $elfSha = Get-FileSha256Lower -Path $elf
        $mapSha = Get-FileSha256Lower -Path $map
        Write-Host "  $rtos ELF: $elf"
        Write-Host "  $rtos ELF SHA: $elfSha" -ForegroundColor DarkGray
        Write-Host "  $rtos MAP: $map"
        Write-Host "  $rtos MAP SHA: $mapSha" -ForegroundColor DarkGray

        $campaignHashes[$rtos] = @{
            elf          = $elf
            elf_sha256   = $elfSha
            map          = $map
            map_sha256   = $mapSha
        }
    }

    # Write the campaign lock under results/manifest/ (NOT
    # results/raw/, to avoid collision with RUN_FILE_RE which
    # parses *_<profile>_run<NN>.* from results/raw/).
    $manifestDir = Join-Path $RepoRoot "results\manifest"
    if (-not (Test-Path $manifestDir)) {
        New-Item -Path $manifestDir -ItemType Directory `
            -Force | Out-Null
    }
    $lockPath = Join-Path $manifestDir "${Profile}_campaign.lock.json"
    $lockObj = [ordered]@{
        schema           = "rtos-benchmark/campaign-lock/v1"
        profile          = $Profile
        publication_mode = $PublicationMode
        timestamp_utc    = (Get-Date).ToUniversalTime().ToString("o")
        rtoses           = [ordered]@{}
    }
    foreach ($rtos in $Rtoses) {
        $lockObj.rtoses[$rtos] = $campaignHashes[$rtos]
    }
    $lockObj | ConvertTo-Json -Depth 4 |
        Out-File -FilePath $lockPath -Encoding utf8
    Write-Host ""
    Write-Host "Campaign lock written: $lockPath" -ForegroundColor Green
}

# ---------------------------------------------------------------------
# Phase 2: capture run00 (mandatory warmup for publishable
# profiles per ADR-013; skipping it leaves the campaign
# non-publishable) + run01..run05
# ---------------------------------------------------------------------

if ($OnlyReport) {
    Write-Banner "OnlyReport: skipping all captures"
} else {
foreach ($rtos in $Rtoses) {
    $hashes = $campaignHashes[$rtos]

    if (-not $SkipWarmup) {
        Write-Banner "$rtos / $Profile / run 00 (warmup, excluded from report)"
        & $smokeScript `
            -RepoRoot $RepoRoot `
            -Rtos $rtos `
            -Port $Port `
            -Baud $Baud `
            -CollectorTimeoutSec $CollectorTimeoutSec `
            -Profile $Profile `
            -RunId "00" `
            -PublicationMode $PublicationMode `
            -ElfFile $hashes.elf `
            -MapFile $hashes.map `
            -ExpectedElfSha $hashes.elf_sha256 `
            -ExpectedMapSha $hashes.map_sha256 `
            -SkipBuild `
            -SkipReportPlot `
            -QuietCollector
        if ($LASTEXITCODE -ne 0) {
            throw "FAIL: $rtos run00 (warmup) failed"
        }
    }

    foreach ($n in $RunIds) {
        $runId = "{0:D2}" -f $n
        Write-Banner "$rtos / $Profile / run $runId"
        & $smokeScript `
            -RepoRoot $RepoRoot `
            -Rtos $rtos `
            -Port $Port `
            -Baud $Baud `
            -CollectorTimeoutSec $CollectorTimeoutSec `
            -Profile $Profile `
            -RunId $runId `
            -PublicationMode $PublicationMode `
            -ElfFile $hashes.elf `
            -MapFile $hashes.map `
            -ExpectedElfSha $hashes.elf_sha256 `
            -ExpectedMapSha $hashes.map_sha256 `
            -SkipBuild `
            -SkipReportPlot `
            -QuietCollector
        if ($LASTEXITCODE -ne 0) {
            throw "FAIL: $rtos run$runId failed"
        }
    }
}
}  # end of if (-not $OnlyReport)

$elapsed = (Get-Date) - $campaignStartTime
Write-Banner ("Campaign captures done in {0:N0} s ({1:N1} min)" `
    -f $elapsed.TotalSeconds, $elapsed.TotalMinutes)

if ($SkipReport) {
    Write-Host "SkipReport set -- leaving without running publication gate"
    return
}

# ---------------------------------------------------------------------
# Phase 3: publication-gate report + plots
# ---------------------------------------------------------------------

$reportScript = Join-Path $RepoRoot "scripts\report_results.py"
$plotScript   = Join-Path $RepoRoot "scripts\plot_results.py"
if (-not (Test-Path $reportScript)) {
    throw "report_results.py not found at $reportScript"
}
if (-not (Test-Path $plotScript)) {
    throw "plot_results.py not found at $plotScript"
}

Write-Banner "report_results.py --publication-gate"
$reportArgs = @($reportScript,
                "--profile", $Profile,
                "--publication-gate")
Write-Host ("> python " + ($reportArgs -join ' ')) -ForegroundColor DarkGray
& python @reportArgs
$rc = $LASTEXITCODE
if ($rc -ne 0) {
    throw "publication gate FAILED (exit $rc) -- see stderr above"
}

Write-Banner "plot_results.py"
$plotArgs = @($plotScript, "--profile", $Profile)
Write-Host ("> python " + ($plotArgs -join ' ')) -ForegroundColor DarkGray
& python @plotArgs
$rc = $LASTEXITCODE
if ($rc -ne 0) {
    throw "plot_results.py FAILED (exit $rc)"
}

# --- Final inventory ---

Write-Banner "Final inventory"
$counts = @{}
foreach ($suffix in @("validated.json", "csv", "t4_pi.csv",
                      "banner.txt", "stdout.txt", "map", "elf")) {
    $cnt = (Get-ChildItem `
            (Join-Path $RepoRoot "results\raw\*_${Profile}_run0[1-5].$suffix") `
            -ErrorAction SilentlyContinue).Count
    $counts[$suffix] = $cnt
    Write-Host ("  {0,-20} {1,3}/15" -f $suffix, $cnt)
}

Write-Host ""
Write-Host "DONE. Reports under results\summary; plots under results\plots." `
    -ForegroundColor Green
