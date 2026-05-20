#Requires -Version 5.1
<#
.SYNOPSIS
  Thin PowerShell wrapper around scripts/lab_runner.py (cross-platform).
  Maintains backward CLI compatibility with the pre-Commit-4 lab_smoke.ps1.
.DESCRIPTION
  Codex 2026-05-20-commit-4-ps-thin-wrapper-001 (Commit 4 of the
  Linux readiness migration). Orchestration moved to
  scripts/lab_runner.py; this script translates PowerShell-style
  parameters into the runner CLI surface and execs it. Exit code
  propagated verbatim.
#>
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,

    [ValidateSet("chibios", "freertos", "zephyr")]
    [string]$Rtos = "chibios",

    [ValidateSet("fair_perf", "realistic_tickless", "debug_dev")]
    [string]$Profile = "fair_perf",

    [string]$RunId = "01",
    [string]$Port = "COM5",
    [int]$Baud = 115200,

    [int]$CollectorTimeoutSec = 600,
    [int]$CollectorStartDelaySec = 2,

    [string]$Python = "python",
    [string]$OpenOcd = "openocd",
    [string]$Make = "make",

    [switch]$Warmup,
    [switch]$Clean,
    [switch]$SkipBuild,
    [switch]$SkipReportPlot,
    [switch]$QuietCollector,

    [ValidateSet("la", "dwt_only")]
    [string]$PublicationMode = "dwt_only",

    [string]$ElfFile = "",
    [string]$MapFile = "",
    [string]$ExpectedElfSha = "",
    [string]$ExpectedMapSha = "",

    [switch]$OnlyBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$runner = Join-Path $PSScriptRoot "lab_runner.py"
if (-not (Test-Path $runner)) {
    throw "lab_runner.py not found at $runner"
}

# Codex BLOCKING 1: fail fast on -RepoRoot mismatch (do not
# warn-and-ignore). lab_runner.py uses __file__.parent.parent.
$wrapperRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$resolvedRepoRoot = (Resolve-Path $RepoRoot).Path
if ($resolvedRepoRoot -ne $wrapperRoot) {
    throw "RepoRoot=$resolvedRepoRoot does not match wrapper location $wrapperRoot; lab_runner.py uses its own location and cannot be retargeted from this wrapper."
}

# $OpenOcd / $Make compatibility: if a non-default path is given,
# prepend its parent directory to PATH so lab_runner.py finds it.
if ($OpenOcd -ne "openocd" -and (Test-Path $OpenOcd)) {
    $env:PATH = (Split-Path -Parent $OpenOcd) + [IO.Path]::PathSeparator + $env:PATH
}
if ($Make -ne "make" -and (Test-Path $Make)) {
    $env:PATH = (Split-Path -Parent $Make) + [IO.Path]::PathSeparator + $env:PATH
}

if ($OnlyBuild) {
    $argv = @($runner, "build-only",
              "--rtos", $Rtos,
              "--profile", $Profile,
              "--publication-mode", $PublicationMode)
    if ($Clean) { $argv += "--clean" }
} else {
    $argv = @($runner, "smoke",
              "--rtos", $Rtos,
              "--profile", $Profile,
              "--run-id", $RunId,
              "--port", $Port,
              "--baud", "$Baud",
              "--collector-timeout-sec", "$CollectorTimeoutSec",
              "--collector-start-delay-sec", "$CollectorStartDelaySec",
              "--publication-mode", $PublicationMode)
    if ($Warmup)         { $argv += "--warmup" }
    if ($Clean)          { $argv += "--clean" }
    if ($SkipBuild)      { $argv += "--skip-build" }
    if ($SkipReportPlot) { $argv += "--skip-report-plot" }
    if ($QuietCollector) { $argv += "--quiet-collector" }
    if ($ElfFile)        { $argv += @("--elf-file", $ElfFile) }
    if ($MapFile)        { $argv += @("--map-file", $MapFile) }
    if ($ExpectedElfSha) { $argv += @("--expected-elf-sha", $ExpectedElfSha) }
    if ($ExpectedMapSha) { $argv += @("--expected-map-sha", $ExpectedMapSha) }
}

# Native invocation: PS 5.1 wraps native stderr (e.g. openocd's
# version banner) as RemoteException/NativeCommandError, which
# trips $ErrorActionPreference="Stop" set above and kills the
# wrapper before reaching `exit $LASTEXITCODE`. Lower EAP for
# the subprocess; the subprocess exit code is the authoritative
# signal.
$ErrorActionPreference = "Continue"
Write-Host "> $Python $($argv -join ' ')" -ForegroundColor DarkGray
& $Python @argv
exit $LASTEXITCODE
