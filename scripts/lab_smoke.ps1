<# 
lab_smoke.ps1 - smoke test helper for the STM32H750B-DK RTOS benchmark.

Purpose:
  Runs an RTOS smoke capture (default chibios; use `-Rtos
  freertos` or `-Rtos zephyr` to target the other ports)
  with the safe ordering:

    build
    cflags_audit (C3-step3, via Invoke-CflagsAuditForRtos)
    openocd program <elf> verify exit     # no "reset" argument
    start collect_results.py              # collector opens UART first
    openocd init; reset run; exit          # firmware starts now
    wait collector
    analyze_results.py
    report_results.py
    plot_results.py

Default use from repo root:

  powershell -ExecutionPolicy Bypass -File .\scripts\lab_smoke.ps1 `
      -Port COM5 `
      -Warmup `
      -RunId 01 `
      -Clean

Notes:
  - The warmup run is run00 and is automatically excluded by report_results.py.
  - Reports generated without --publication-gate are exploratory by design.
  - TEST 1 / TEST 4 source labels depend on -PublicationMode (ADR-015):
      * 'dwt_only' (Phase 1 default) -> source = DWT
      * 'la'                         -> source = DWT_validation
  - AUTORUN is derived from -PublicationMode (dwt_only -> 1, la -> 0).
#>

[CmdletBinding()]
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

    # 2b-B (Codex round-3) - publication-mode-driven build.
    [ValidateSet("la", "dwt_only")]
    [string]$PublicationMode = "dwt_only",

    # 2b-B - explicit artefact paths (used by lab_campaign.ps1 to
    # reuse the build-once artefacts across run01..run05). If
    # empty, the script derives them from $Rtos / $Profile via the
    # Makefile-wrapper layout.
    [string]$ElfFile = "",
    [string]$MapFile = "",

    # 2b-B - campaign-lock SHA256 (lowercase hex). If non-empty,
    # the actual ELF / MAP hash MUST match before the flash step
    # runs, otherwise the campaign is treated as having flashed a
    # stale binary and aborts before touching the chip.
    [string]$ExpectedElfSha = "",
    [string]$ExpectedMapSha = "",

    # 2b-C - build-only mode: invoke the Makefile wrapper and exit
    # without flashing or collecting. Used by lab_campaign.ps1 to
    # build artefacts once per (rtos, profile) before locking
    # their SHA256 for the run loop.
    [switch]$OnlyBuild
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# C3-step3 - dot-source the shared cflags-audit helper so
# every Build-<Rtos> function below can call
# `Invoke-CflagsAuditForRtos` against the right build dir
# after each port's build.
. (Join-Path $PSScriptRoot "lab_helpers\run_cflags_audit.ps1")

# 2b-B - AUTORUN is derived from the publication mode:
#   dwt_only (Phase 1, ADR-015) -> B1 gating bypass allowed -> AUTORUN=1
#   la                         -> B1 gating mandatory       -> AUTORUN=0
$AutorunVal = if ($PublicationMode -eq "dwt_only") { "1" } else { "0" }

function Get-FileSha256Lower {
    param([string]$Path)
    if (-not (Test-Path $Path)) {
        throw "File not found: $Path"
    }
    return (Get-FileHash -Path $Path -Algorithm SHA256).Hash.ToLower()
}

function Assert-Sha256 {
    # Print the actual hash for the operator log; if @p Expected
    # is non-empty, abort on mismatch (campaign-lock model,
    # Codex round-3 2b).
    param(
        [Parameter(Mandatory=$true)][string]$Path,
        [Parameter(Mandatory=$true)][string]$Label,
        [string]$Expected = ""
    )
    $actual = Get-FileSha256Lower -Path $Path
    Write-Host "  $Label SHA256 : $actual" -ForegroundColor DarkGray
    if ($Expected.Length -gt 0) {
        if ($actual -ne $Expected.ToLower()) {
            throw "$Label SHA mismatch (campaign artefact drift): actual=$actual expected=$Expected. Refusing to flash a stale binary."
        }
        Write-Host "  $Label SHA matches expected." -ForegroundColor DarkGreen
    }
}

function Write-Step {
    param([string]$Message)
    Write-Host ""
    Write-Host "===== $Message =====" -ForegroundColor Cyan
}

function Invoke-Checked {
    param(
        [Parameter(Mandatory=$true)][string]$FilePath,
        [Parameter(Mandatory=$true)][string[]]$Arguments,
        [string]$WorkingDirectory = $RepoRoot
    )

    Push-Location $WorkingDirectory
    try {
        Write-Host "> $FilePath $($Arguments -join ' ')" -ForegroundColor DarkGray
        # Lab-session bug fix 2026-05-14 (P47): under
        # PowerShell 5.1 with $ErrorActionPreference="Stop",
        # any stderr write by a native command is promoted
        # to a NativeCommandError that terminates the
        # script. FreeRTOS-Kernel emits unused-variable
        # warnings on event_groups.c / stream_buffer.c /
        # port.c that PS5.1 then treats as a fatal error
        # even though make returns exit 0. Temporarily
        # relax ErrorActionPreference around the native
        # call and trust $LASTEXITCODE exclusively for the
        # success/failure decision.
        $eapBackup = $ErrorActionPreference
        $ErrorActionPreference = 'Continue'
        try {
            & $FilePath @Arguments
        }
        finally {
            $ErrorActionPreference = $eapBackup
        }
        if ($LASTEXITCODE -ne 0) {
            throw "Command failed with exit code ${LASTEXITCODE}: $FilePath $($Arguments -join ' ')"
        }
    }
    finally {
        Pop-Location
    }
}

function Get-ChibiOSElf {
    return (Join-Path $RepoRoot "chibios\benchmark_chibios\build\$Profile\benchmark_chibios.elf")
}

function Get-ChibiOSMap {
    return (Join-Path $RepoRoot "chibios\benchmark_chibios\build\$Profile\benchmark_chibios.map")
}

function Build-ChibiOS {
    if ($SkipBuild) { Write-Step "Build ChibiOS skipped"; return }
    Write-Step "Build ChibiOS ($Profile, AUTORUN=$AutorunVal)"
    $wd = Join-Path $RepoRoot "chibios\benchmark_chibios"
    if ($OnlyBuild) {
        # 2b followup (Codex round-3 BLOCKER 1): wipe the build dir
        # before make so AUTORUN reaches every translation unit
        # deterministically (no stale .o, no stale cache).
        $bd = Join-Path $wd "build\$Profile"
        if (Test-Path $bd) {
            Write-Host "  -OnlyBuild: wiping $bd" -ForegroundColor DarkGray
            Remove-Item -Path $bd -Recurse -Force
        }
    }
    Invoke-Checked -FilePath $Make -Arguments @(
        "PROFILE=$Profile",
        "AUTORUN=$AutorunVal",
        "-j"
    ) -WorkingDirectory $wd

    # C3-step3 - ADR-009 effective-flag audit on the ChibiOS
    # build (delegates to the shared helper, which first runs
    # `make compile-commands PROFILE=$Profile` to synthesise
    # compile_commands.json from `make -B -n`, then invokes
    # `cflags_audit.py --rtos chibios`). Throws on failure.
    Write-Step "ChibiOS CFLAGS audit ($Profile)"
    Invoke-CflagsAuditForRtos `
        -Rtos chibios -Profile $Profile `
        -RepoRoot $RepoRoot -Python $Python -Make $Make
}

# --- FreeRTOS -------------------------------------------------------
# Make wrapper -> CMake build under build/$Profile/.

function Get-FreeRTOSElf {
    return (Join-Path $RepoRoot "freertos\benchmark_freertos\build\$Profile\benchmark_freertos.elf")
}

function Get-FreeRTOSMap {
    return (Join-Path $RepoRoot "freertos\benchmark_freertos\build\$Profile\benchmark_freertos.map")
}

function Build-FreeRTOS {
    if ($SkipBuild) { Write-Step "Build FreeRTOS skipped"; return }
    Write-Step "Build FreeRTOS ($Profile, AUTORUN=$AutorunVal)"
    # 2b-B (Codex round-3): delegate to the FreeRTOS Makefile
    # wrapper so the canonical artefact path is `build/$Profile/...`
    # and the AUTORUN value is forwarded deterministically via
    # `-DBENCH_AUTORUN=$AUTORUN_VAL` on every configure.
    $wd = Join-Path $RepoRoot "freertos\benchmark_freertos"
    if ($OnlyBuild) {
        # 2b followup (Codex round-3 BLOCKER 1): wipe the cmake
        # cache + build tree before make so the new AUTORUN flag
        # always reaches every translation unit, not just the ones
        # cmake's incremental dep-tracking happens to invalidate.
        $bd = Join-Path $wd "build\$Profile"
        if (Test-Path $bd) {
            Write-Host "  -OnlyBuild: wiping $bd" -ForegroundColor DarkGray
            Remove-Item -Path $bd -Recurse -Force
        }
    }
    Invoke-Checked -FilePath $Make -Arguments @(
        "PROFILE=$Profile",
        "AUTORUN=$AutorunVal"
    ) -WorkingDirectory $wd

    # C3-step3 - ADR-009 effective-flag audit on the FreeRTOS
    # build. cmake emits compile_commands.json directly thanks
    # to `CMAKE_EXPORT_COMPILE_COMMANDS ON` in
    # `freertos/benchmark_freertos/CMakeLists.txt`. Throws on
    # failure.
    Write-Step "FreeRTOS CFLAGS audit ($Profile)"
    Invoke-CflagsAuditForRtos `
        -Rtos freertos -Profile $Profile `
        -RepoRoot $RepoRoot -Python $Python
}

# --- Zephyr ---------------------------------------------------------
# Make wrapper -> west build under zephyr/build/$Profile/.

function Get-ZephyrElf {
    return (Join-Path $RepoRoot "zephyr\build\$Profile\zephyr\zephyr.elf")
}

function Get-ZephyrMap {
    return (Join-Path $RepoRoot "zephyr\build\$Profile\zephyr\zephyr.map")
}

function Build-Zephyr {
    if ($SkipBuild) { Write-Step "Build Zephyr skipped"; return }
    Write-Step "Build Zephyr ($Profile, AUTORUN=$AutorunVal)"
    # 2b-B (Codex round-3): delegate to the Zephyr Makefile wrapper
    # so the canonical artefact path is `zephyr/build/$Profile/...`
    # and the AUTORUN value is forwarded via west on every build.
    $wd = Join-Path $RepoRoot "zephyr\benchmark_zephyr"
    if ($OnlyBuild) {
        # 2b followup (Codex round-3 BLOCKER 1): do NOT trust west's
        # cache-difference auto-pristine. Explicitly wipe the build
        # dir so the build-once campaign step always reconfigures
        # from scratch with the requested AUTORUN value.
        $bd = Join-Path $RepoRoot "zephyr\build\$Profile"
        if (Test-Path $bd) {
            Write-Host "  -OnlyBuild: wiping $bd" -ForegroundColor DarkGray
            Remove-Item -Path $bd -Recurse -Force
        }
    }
    Invoke-Checked -FilePath $Make -Arguments @(
        "PROFILE=$Profile",
        "AUTORUN=$AutorunVal"
    ) -WorkingDirectory $wd

    # C3-step3 - ADR-009 effective-flag audit on the Zephyr
    # build. cmake (via west) emits compile_commands.json
    # unconditionally for the Zephyr application. Throws on
    # failure. Replaces the legacy direct-script invocation
    # of `zephyr_cflags_audit.py`; the thin wrapper at that
    # path still works for callers that have not migrated to
    # the shared helper, but lab_smoke now uses the helper.
    Write-Step "Zephyr CFLAGS audit ($Profile)"
    Invoke-CflagsAuditForRtos `
        -Rtos zephyr -Profile $Profile `
        -RepoRoot $RepoRoot -Python $Python
}

# --- Dispatcher per current $Rtos -----------------------------------

function Get-CurrentElf {
    switch ($Rtos) {
        "chibios"  { return Get-ChibiOSElf }
        "freertos" { return Get-FreeRTOSElf }
        "zephyr"   { return Get-ZephyrElf }
    }
}

function Get-CurrentMap {
    switch ($Rtos) {
        "chibios"  { return Get-ChibiOSMap }
        "freertos" { return Get-FreeRTOSMap }
        "zephyr"   { return Get-ZephyrMap }
    }
}

function Build-Current {
    switch ($Rtos) {
        "chibios"  { Build-ChibiOS }
        "freertos" { Build-FreeRTOS }
        "zephyr"   { Build-Zephyr }
    }
}

function Flash-NoReset {
    param([string]$ElfPath)

    if (-not (Test-Path $ElfPath)) {
        throw "ELF not found: $ElfPath"
    }

    # OpenOCD's Tcl interpreter treats backslash inside double-quoted
    # strings as an escape character (\b, \r, \f...). On Windows, raw
    # paths like "...\benchmark_chibios\build\fair_perf\..." get
    # mangled. Convert to forward slashes (Windows accepts them in
    # file APIs and OpenOCD's Tcl leaves them alone).
    $elfFwd = $ElfPath -replace '\\', '/'

    Write-Step "Flash $Rtos, no reset"
    Invoke-Checked -FilePath $OpenOcd -Arguments @(
        "-f", "interface/stlink.cfg",
        "-f", "target/stm32h7x.cfg",
        "-c", "reset_config srst_only srst_nogate connect_assert_srst",
        "-c", "program `"$elfFwd`" verify exit"
    ) -WorkingDirectory $RepoRoot
}

function Reset-Run {
    Write-Step "Reset and run"
    Invoke-Checked -FilePath $OpenOcd -Arguments @(
        "-f", "interface/stlink.cfg",
        "-f", "target/stm32h7x.cfg",
        "-c", "reset_config srst_only srst_nogate connect_assert_srst",
        "-c", "init; reset run; exit"
    ) -WorkingDirectory $RepoRoot
}

function Remove-RunArtifacts {
    param([string]$ThisRunId)

    $raw = Join-Path $RepoRoot "results\raw"
    $summary = Join-Path $RepoRoot "results\summary"
    $plots = Join-Path $RepoRoot "results\plots"

    if (Test-Path $raw) {
        Get-ChildItem $raw -Filter "$Rtos`_$Profile`_run$ThisRunId.*" -ErrorAction SilentlyContinue |
            Remove-Item -Force -ErrorAction SilentlyContinue
    }

    if ($ThisRunId -eq $RunId) {
        if (Test-Path $summary) { Remove-Item $summary -Recurse -Force -ErrorAction SilentlyContinue }
        if (Test-Path $plots)   { Remove-Item $plots   -Recurse -Force -ErrorAction SilentlyContinue }
    }
}

function Start-Collector {
    param(
        [string]$ThisRunId,
        [string]$Prefix,
        [string]$ElfPath,
        [string]$MapPath
    )

    $collectorOut = "$Prefix.collector.out.txt"
    $collectorErr = "$Prefix.collector.err.txt"

    # Round-13 fix 1: do NOT use the automatic $args variable name.
    # PowerShell's $args is an automatic variable that holds the
    # un-named parameters of the enclosing function/script; shadowing
    # it here works but is fragile under Set-StrictMode.
    # 2b-B (Codex round-3): --publication-mode + --elf-file /
    # --map-file are now mandatory for publishable profiles; the
    # collector itself enforces the requirement (collect_results.py
    # 2a). The lab_smoke flow passes them unconditionally; the
    # collector will fail-stop if either file is missing.
    $collectorArgs = @(
        (Join-Path $RepoRoot "scripts\collect_results.py"),
        "--port", $Port,
        "--baud", "$Baud",
        "--rtos", $Rtos,
        "--profile", $Profile,
        "--run-id", $ThisRunId,
        "--output", $Prefix,
        "--timeout", "$CollectorTimeoutSec",
        "--publication-mode", $PublicationMode,
        "--elf-file", $ElfPath,
        "--map-file", $MapPath
    )

    if ($QuietCollector) {
        $collectorArgs += "--quiet"
    }

    Write-Step "Start collector ($Rtos / $Profile / run $ThisRunId)"
    Write-Host "> $Python $($collectorArgs -join ' ')" -ForegroundColor DarkGray

    $p = Start-Process `
        -FilePath $Python `
        -ArgumentList $collectorArgs `
        -WorkingDirectory $RepoRoot `
        -NoNewWindow `
        -RedirectStandardOutput $collectorOut `
        -RedirectStandardError  $collectorErr `
        -PassThru

    # Documented PowerShell quirk: with Start-Process -PassThru the
    # Win32 process handle is closed by the runtime as soon as we
    # stop touching $p, which makes $p.ExitCode read as $null after
    # WaitForExit. Touching .Handle here forces the runtime to keep
    # the handle alive for the lifetime of the variable, so ExitCode
    # is readable later. (Trick from MS-internal forums; see also
    # PowerShell/PowerShell#824.)
    $null = $p.Handle

    return @{
        Process = $p
        Out = $collectorOut
        Err = $collectorErr
    }
}

function Wait-Collector {
    param(
        [hashtable]$Collector,
        [string]$Prefix
    )

    $proc = $Collector.Process
    $maxWaitMs = ($CollectorTimeoutSec + 90) * 1000

    Write-Step "Wait collector"
    $finished = $proc.WaitForExit($maxWaitMs)
    if (-not $finished) {
        try { $proc.Kill() } catch {}
        throw "Collector did not finish within $($CollectorTimeoutSec + 90)s; killed process. See $($Collector.Out) / $($Collector.Err)"
    }
    # MSDN: when WaitForExit(timeout) returns true and stdout/stderr
    # have been redirected, the asynchronous read handlers may still
    # be flushing AND ExitCode may not yet be populated. The doc says:
    # "call the WaitForExit() overload that takes no parameter".
    $proc.WaitForExit()

    # Round-13 fix 3: force UTF-8 reading. The collector writes the
    # serial mirror as UTF-8; Windows PowerShell 5.1 default Get-Content
    # encoding is the OS ANSI codepage (cp1252 in most installs),
    # which would mojibake any non-ASCII byte. PS 7+ defaults to UTF-8
    # but the explicit flag is harmless there too.
    # Get-Content -Raw on an empty (or absent) file returns $null, not
    # "". Under Set-StrictMode -Version Latest calling .Trim() on
    # $null throws "Cannot call a method on a null-valued expression",
    # so we coerce to [string] first.
    $stdoutText = ""
    $stderrText = ""
    if (Test-Path $Collector.Out) {
        $tmp = Get-Content $Collector.Out -Raw -Encoding UTF8 `
            -ErrorAction SilentlyContinue
        if ($null -ne $tmp) { $stdoutText = [string]$tmp }
    }
    if (Test-Path $Collector.Err) {
        $tmp = Get-Content $Collector.Err -Raw -Encoding UTF8 `
            -ErrorAction SilentlyContinue
        if ($null -ne $tmp) { $stderrText = [string]$tmp }
    }

    if ($stdoutText.Trim().Length -gt 0) {
        Write-Host $stdoutText
    }

    if ($proc.ExitCode -ne 0) {
        if ($stderrText.Trim().Length -gt 0) {
            Write-Host $stderrText -ForegroundColor Red
        }
        throw "collect_results.py failed with exit code $($proc.ExitCode). Raw log should still be at $Prefix.stdout.txt"
    }

    if ($stderrText.Trim().Length -gt 0) {
        Write-Host $stderrText -ForegroundColor Yellow
    }
}

function Analyze-Run {
    param([string]$Prefix)

    Write-Step "Analyze firmware stats vs Python recompute"
    Invoke-Checked -FilePath $Python -Arguments @(
        (Join-Path $RepoRoot "scripts\analyze_results.py"),
        $Prefix
    ) -WorkingDirectory $RepoRoot
}

function Invoke-OneRun {
    param([string]$ThisRunId)

    # 2b-B (Codex round-3): allow lab_campaign.ps1 to inject
    # explicit artefact paths so the same build is reused across
    # run00..run05. Default to Makefile-wrapper layout when not
    # provided.
    $elf = if ($ElfFile -ne "") { $ElfFile } else { Get-CurrentElf }
    $map = if ($MapFile -ne "") { $MapFile } else { Get-CurrentMap }
    $prefix = Join-Path $RepoRoot "results\raw\$Rtos`_$Profile`_run$ThisRunId"

    if ($Clean) {
        Remove-RunArtifacts -ThisRunId $ThisRunId
    }

    # 2b-B: print the actual ELF / MAP SHA256 for the operator
    # log; if -ExpectedElfSha / -ExpectedMapSha were passed (lock
    # mode), abort before touching the chip on mismatch.
    Write-Step "Artefact hashes ($Rtos / $Profile)"
    Assert-Sha256 -Path $elf -Label "ELF" -Expected $ExpectedElfSha
    Assert-Sha256 -Path $map -Label "MAP" -Expected $ExpectedMapSha

    Flash-NoReset -ElfPath $elf

    $collector = Start-Collector `
        -ThisRunId $ThisRunId -Prefix $prefix `
        -ElfPath $elf -MapPath $map

    Write-Host ""
    Write-Host "Collector started. Waiting $CollectorStartDelaySec second(s) before reset..." -ForegroundColor Yellow
    Start-Sleep -Seconds $CollectorStartDelaySec

    Reset-Run

    Wait-Collector -Collector $collector -Prefix $prefix

    Analyze-Run -Prefix $prefix

    $validated = "$prefix.validated.json"
    if (-not (Test-Path $validated)) {
        throw "Missing validation manifest after successful collect: $validated"
    }

    Write-Host ""
    Write-Host "Run $ThisRunId OK. Validation manifest: $validated" -ForegroundColor Green
}

function Generate-ExploratoryReportAndPlots {
    if ($SkipReportPlot) {
        Write-Step "Report/plot skipped"
        return
    }

    Write-Step "Generate exploratory report"
    Invoke-Checked -FilePath $Python -Arguments @(
        (Join-Path $RepoRoot "scripts\report_results.py"),
        "--profile", $Profile
    ) -WorkingDirectory $RepoRoot

    Write-Step "Generate plots"
    Invoke-Checked -FilePath $Python -Arguments @(
        (Join-Path $RepoRoot "scripts\plot_results.py"),
        "--profile", $Profile
    ) -WorkingDirectory $RepoRoot
}

function Show-FinalCheck {
    param([string]$ThisRunId)

    $prefix = Join-Path $RepoRoot "results\raw\$Rtos`_$Profile`_run$ThisRunId"

    Write-Step "Final smoke outputs"
    $expected = @(
        "$prefix.stdout.txt",
        "$prefix.csv",
        "$prefix.t4_pi.csv",
        "$prefix.banner.txt",
        "$prefix.validated.json"
    )

    foreach ($p in $expected) {
        if (Test-Path $p) {
            Write-Host "OK  $p" -ForegroundColor Green
        }
        else {
            Write-Host "MISS $p" -ForegroundColor Red
        }
    }

    $banner = "$prefix.banner.txt"
    if (Test-Path $banner) {
        Write-Host ""
        Write-Host "Banner key lines:" -ForegroundColor Cyan
        Select-String -Path $banner -Pattern "RTOS\s+:|RTOS kernel|SystemClock|VOS level|VOSRDY|FLASH_ACR|Tickless|WFI in idle|Optimization" |
            ForEach-Object { Write-Host $_.Line }
    }

    Write-Host ""
    Write-Host "Smoke completed. Remember: reports are exploratory unless generated with --publication-gate." -ForegroundColor Green
}

# ---------------------------------------------------------------------

Write-Step "Pre-flight"
Write-Host "RepoRoot : $RepoRoot"
Write-Host "RTOS     : $Rtos"
Write-Host "Profile  : $Profile"
Write-Host "Port     : $Port"
Write-Host "RunId    : $RunId"
Write-Host "Warmup   : $Warmup"

if (-not (Test-Path $RepoRoot)) {
    throw "RepoRoot not found: $RepoRoot"
}

Build-Current

if ($OnlyBuild) {
    # 2b followup (Codex round-3 IMPORTANT 3): the audit
    # principle requires SHA print on every flow, including
    # -OnlyBuild. lab_campaign will read these from the file
    # system anyway, but the operator log must carry them too.
    Write-Step "Built artefact hashes ($Rtos / $Profile)"
    $builtElf = if ($ElfFile -ne "") { $ElfFile } else { Get-CurrentElf }
    $builtMap = if ($MapFile -ne "") { $MapFile } else { Get-CurrentMap }
    # 2b followup (Codex round-3 PASS_WITH_MINOR): fail hard if
    # the expected ELF or MAP is missing after a build-only run.
    # Assert-Sha256 already throws on missing file; the previous
    # Test-Path guards silently swallowed broken builds - that
    # would only surface later in lab_campaign when it tries to
    # hash the file. Surfacing it here makes -OnlyBuild standalone
    # also fail-hard.
    Assert-Sha256 -Path $builtElf -Label "ELF"
    Assert-Sha256 -Path $builtMap -Label "MAP"
    Write-Step "OnlyBuild: exit after build"
    return
}

if ($Warmup) {
    Invoke-OneRun -ThisRunId "00"
}

Invoke-OneRun -ThisRunId $RunId
Generate-ExploratoryReportAndPlots
Show-FinalCheck -ThisRunId $RunId
