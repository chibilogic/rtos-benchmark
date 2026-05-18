# SPDX-License-Identifier: GPL-3.0-or-later
#
# Shared helper for the C3-step3 lab integration of the
# cross-RTOS ADR-009 effective-flag audit.
#
# Dot-source from `lab_smoke.ps1` (which is itself invoked by
# `lab_campaign.ps1` via `-OnlyBuild`). After each port's build
# the smoke script calls `Invoke-CflagsAuditForRtos` to read
# back the compile_commands.json that the build system
# emitted and verify it against the ADR-009 contract.
#
# Sources of compile_commands.json:
#   - ChibiOS  : synthesised by `make compile-commands
#                PROFILE=<p>` (which runs `make -B -n` and pipes
#                the recipe text through
#                `scripts/chibios_synth_compile_commands.py`).
#                The helper invokes the make target as the
#                first step of the chibios path.
#   - FreeRTOS : emitted by cmake when
#                `CMAKE_EXPORT_COMPILE_COMMANDS` is ON (set in
#                `freertos/benchmark_freertos/CMakeLists.txt`).
#                Always present after a successful build.
#   - Zephyr   : emitted by cmake (Zephyr forces export
#                unconditionally via its Makefile wrapper).
#                Always present after a successful build.
#
# Throws on audit failure. The caller is expected to use
# try/catch only if it needs to continue past a NO-GO; the
# default behaviour is to abort the lab session, matching the
# `lab_smoke.ps1` Invoke-Checked convention.

function Invoke-CflagsAuditForRtos {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)]
        [ValidateSet("chibios", "freertos", "zephyr")]
        [string]$Rtos,

        [Parameter(Mandatory)]
        [ValidateSet("fair_perf", "realistic_tickless",
                     "debug_dev")]
        [string]$Profile,

        [Parameter(Mandatory)]
        [string]$RepoRoot,

        [Parameter(Mandatory)]
        [string]$Python,

        # Required only for the chibios path (needed by the
        # `make compile-commands` invocation). Optional for
        # freertos / zephyr.
        [string]$Make = $null
    )

    switch ($Rtos) {
        "chibios" {
            $wd = Join-Path $RepoRoot `
                    "chibios\benchmark_chibios"
            $buildDir = Join-Path $wd "build\$Profile"
            if (-not $Make) {
                throw ("Invoke-CflagsAuditForRtos: -Make is " +
                       "required for rtos=chibios")
            }
            Write-Host ("  [cflags_audit] ChibiOS " +
                        "compile-commands synth ($Profile)") `
                       -ForegroundColor DarkGray
            Push-Location $wd
            try {
                # Lab-session bug fix 2026-05-14 (P47):
                # native commands writing to stderr cause
                # PS 5.1 with ErrorActionPreference=Stop to
                # throw NativeCommandError before we read
                # $LASTEXITCODE. Relax for the call.
                $eapBackup = $ErrorActionPreference
                $ErrorActionPreference = 'Continue'
                try {
                    & $Make "PROFILE=$Profile" "compile-commands"
                }
                finally {
                    $ErrorActionPreference = $eapBackup
                }
                if ($LASTEXITCODE -ne 0) {
                    throw ("ChibiOS make compile-commands " +
                           "failed (exit $LASTEXITCODE) for " +
                           "profile $Profile")
                }
            }
            finally {
                Pop-Location
            }
        }
        "freertos" {
            $buildDir = Join-Path $RepoRoot `
                ("freertos\benchmark_freertos\build\" +
                 "$Profile")
        }
        "zephyr" {
            $buildDir = Join-Path $RepoRoot `
                "zephyr\build\$Profile"
        }
    }

    Write-Host ("  [cflags_audit] $Rtos / $Profile") `
               -ForegroundColor DarkGray
    $auditScript = Join-Path $RepoRoot `
                            "scripts\cflags_audit.py"
    # Lab-session bug fix 2026-05-14 (P47): same stderr-as-
    # error issue applies to python.exe invocations.
    $eapBackup = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try {
        & $Python $auditScript `
            "--rtos" $Rtos `
            "--build-dir" $buildDir `
            "--profile" $Profile
    }
    finally {
        $ErrorActionPreference = $eapBackup
    }
    if ($LASTEXITCODE -ne 0) {
        throw ("cflags_audit failed: rtos=$Rtos, " +
               "profile=$Profile, buildDir=$buildDir " +
               "(exit $LASTEXITCODE). See ADR-009.")
    }
}
