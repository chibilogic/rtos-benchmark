#Requires -Version 5.1
<#
.SYNOPSIS
  Thin PowerShell wrapper around scripts/lab_runner.py campaign.
  Maintains backward CLI compatibility with the pre-Commit-4
  lab_campaign.ps1.
.DESCRIPTION
  See lab_smoke.ps1 header for the Commit 4 migration context
  (Codex 2026-05-20-commit-4-ps-thin-wrapper-001).
#>
param(
    [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [string]$Port    = "COM5",

    [ValidateSet("fair_perf", "realistic_tickless", "debug_dev")]
    [string]$Profile = "fair_perf",

    [int]$Baud       = 115200,
    [int]$CollectorTimeoutSec = 600,

    [ValidateSet("chibios", "freertos", "zephyr")]
    [string[]]$Rtoses = @("chibios", "freertos", "zephyr"),

    [int[]]$RunIds   = 1..5,

    [switch]$SkipWarmup,
    [switch]$SkipReport,
    [switch]$OnlyReport,

    [ValidateSet("la", "dwt_only")]
    [string]$PublicationMode = "dwt_only"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$runner = Join-Path $PSScriptRoot "lab_runner.py"
if (-not (Test-Path $runner)) {
    throw "lab_runner.py not found at $runner"
}

$wrapperRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$resolvedRepoRoot = (Resolve-Path $RepoRoot).Path
if ($resolvedRepoRoot -ne $wrapperRoot) {
    throw "RepoRoot=$resolvedRepoRoot does not match wrapper location $wrapperRoot; lab_runner.py uses its own location and cannot be retargeted from this wrapper."
}

$argv = @($runner, "campaign",
          "--profile", $Profile,
          "--port", $Port,
          "--baud", "$Baud",
          "--collector-timeout-sec", "$CollectorTimeoutSec",
          "--publication-mode", $PublicationMode,
          "--rtoses") + $Rtoses +
        @("--run-ids") + ($RunIds | ForEach-Object { "$_" })
if ($SkipWarmup) { $argv += "--skip-warmup" }
if ($SkipReport) { $argv += "--skip-report" }
if ($OnlyReport) { $argv += "--only-report" }

# Same PS 5.1 native-stderr workaround as lab_smoke.ps1.
$ErrorActionPreference = "Continue"
Write-Host "> python $($argv -join ' ')" -ForegroundColor DarkGray
& python @argv
exit $LASTEXITCODE
