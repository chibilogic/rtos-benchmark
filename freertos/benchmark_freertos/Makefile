# SPDX-License-Identifier: GPL-3.0-or-later
#
# Wrapper Makefile so Eclipse (and humans) can build the FreeRTOS port
# with a uniform `make PROFILE=...` interface, just like the ChibiOS
# port.
#
# Profiles (ADR-011):
#   make PROFILE=fair_perf            (default)
#   make PROFILE=realistic_tickless
#
# This Makefile delegates to CMake. The actual build settings are in
# CMakeLists.txt; here we only handle "configure if needed, then build".

PROFILE   ?= fair_perf
BUILD_DIR := build/$(PROFILE)
# Platform-aware generator default. Override with: make GENERATOR="..."
ifeq ($(OS),Windows_NT)
  GENERATOR ?= MinGW Makefiles
else
  GENERATOR ?= Unix Makefiles
endif

# AUTORUN (ADR-016): when AUTORUN=1, the firmware skips the B1
# button gating between tests. Required for Phase 1 DWT-only
# publication runs (ADR-015). Default is 0 (Mode LA / B1 gated).
# The value is forwarded to cmake on every configure so the
# cached BENCH_AUTORUN cannot diverge from the value the operator
# just requested (Codex round-3 2b).
AUTORUN ?= 0
ifeq ($(AUTORUN),1)
  AUTORUN_VAL := 1
else
  AUTORUN_VAL := 0
endif

.PHONY: all configure build clean distclean

all: build

# `configure` is PHONY: cmake -B is idempotent on no-change and
# updates the cache otherwise. This guarantees that the value of
# BENCH_AUTORUN in the generated build files matches the value
# passed on the make command line, even if the build dir already
# exists with a stale cache entry.
configure:
	cmake -S . -B $(BUILD_DIR) -G "$(GENERATOR)" \
	      -DCMAKE_TOOLCHAIN_FILE=cmake/arm-none-eabi.cmake \
	      -DBENCH_PROFILE=$(PROFILE) \
	      -DBENCH_AUTORUN=$(AUTORUN_VAL)

build: configure
	cmake --build $(BUILD_DIR)

clean:
	-cmake --build $(BUILD_DIR) --target clean

distclean:
	rm -rf build/$(PROFILE)
