@echo off
REM ============================================================
REM  RTOS Benchmark - environment activation script
REM
REM  Adds the project-local tools to PATH for THIS session only.
REM  Close the cmd window -> the original PATH is restored.
REM
REM  Required tools under tools/:
REM    - tools\gcc-arm\bin\arm-none-eabi-gcc.exe
REM    - tools\msys2\usr\bin\make.exe
REM    - tools\openocd\bin\openocd.exe
REM    - tools\eclipse\eclipse.exe         (optional, IDE)
REM    - zephyr\.venv\Scripts\west.exe     (optional, only for Zephyr)
REM ============================================================

set ROOT=%~dp0

REM --- Add tools to PATH (in front, take priority) ---
set PATH=%ROOT%tools\gcc-arm\bin;%ROOT%tools\msys2\usr\bin;%ROOT%tools\openocd\bin;%PATH%

REM --- Eclipse (optional) ---
if exist "%ROOT%tools\eclipse\eclipse.exe" set "PATH=%ROOT%tools\eclipse;%PATH%"

REM --- Zephyr venv (optional). Adding Scripts/ to PATH gives us west
REM     and the venv's python without explicit "activate". ---
if exist "%ROOT%zephyr\.venv\Scripts\west.exe" set "PATH=%ROOT%zephyr\.venv\Scripts;%PATH%"

REM --- Tool location variables ---
set OPENOCD_SCRIPTS=%ROOT%tools\openocd\openocd\scripts
set PROJECT_ROOT=%ROOT%

REM --- Zephyr toolchain selection (so west uses our local GCC,
REM     not the Zephyr SDK) ---
set ZEPHYR_TOOLCHAIN_VARIANT=gnuarmemb
set GNUARMEMB_TOOLCHAIN_PATH=%ROOT%tools\gcc-arm

REM --- Startup banner ---
echo.
echo ==========================================
echo   RTOS Benchmark dev env ACTIVE
echo ==========================================
echo Root        : %ROOT%
echo OpenOCD cfg : %OPENOCD_SCRIPTS%
echo Zephyr TC   : %ZEPHYR_TOOLCHAIN_VARIANT% in %GNUARMEMB_TOOLCHAIN_PATH%
echo.

REM --- Tool version check ---
echo Installed tools:
echo ----------------
where arm-none-eabi-gcc >nul 2>&1
if errorlevel 1 (
    echo [X] arm-none-eabi-gcc NOT found in tools\gcc-arm\bin\
) else (
    arm-none-eabi-gcc --version 2>nul | findstr /C:"gcc"
)

where make >nul 2>&1
if errorlevel 1 (
    echo [X] make NOT found in tools\msys2\usr\bin\
) else (
    make --version 2>nul | findstr /C:"GNU Make"
)

where openocd >nul 2>&1
if errorlevel 1 (
    echo [X] openocd NOT found in tools\openocd\bin\
) else (
    openocd --version 2>&1 | findstr /C:"Open On-Chip"
)

where cmake >nul 2>&1
if errorlevel 1 (
    echo [--] cmake NOT in PATH ^(required for FreeRTOS and Zephyr builds^)
) else (
    cmake --version | findstr /R "^cmake version"
)

if exist "%ROOT%tools\eclipse\eclipse.exe" (
    echo [OK] Eclipse           : %ROOT%tools\eclipse\eclipse.exe
) else (
    echo [--] Eclipse           : not installed in tools\eclipse\ ^(optional^)
)

if exist "%ROOT%zephyr\.venv\Scripts\west.exe" (
    where west >nul 2>&1
    if not errorlevel 1 (
        for /f "tokens=*" %%v in ('west --version 2^>nul') do echo [OK] west             : %%v
    )
) else (
    echo [--] Zephyr west       : not found ^(only needed for Zephyr builds^)
)

echo.
echo Type 'exit' to leave the environment.
echo.

REM --- Interactive cmd in the project root ---
cmd /k "cd /d %ROOT%"
