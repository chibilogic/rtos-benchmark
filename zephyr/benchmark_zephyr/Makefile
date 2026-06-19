# SPDX-License-Identifier: Apache-2.0
#
# Wrapper Makefile so Eclipse (and humans) can build the Zephyr port
# with a uniform `make PROFILE=...` interface, like the ChibiOS and
# FreeRTOS ports.
#
# Profiles (ADR-011):
#   make PROFILE=fair_perf            (default)
#   make PROFILE=realistic_tickless
#
# This Makefile delegates to `west build`. The build dir is placed
# at zephyr/build/<profile>/ so that all Zephyr build artefacts stay
# under the zephyr/ subtree (consistent with west conventions).
#
# Requires: env.bat to be active in this shell, and the Zephyr venv
# to be present in zephyr/.venv/ (so `west` resolves).

PROFILE   ?= fair_perf
BOARD     ?= stm32h750b_dk
APP_DIR   := $(CURDIR)
ZEPHYR_ROOT := $(CURDIR)/..
BUILD_DIR := $(ZEPHYR_ROOT)/build/$(PROFILE)
CONF_FILE := conf/$(PROFILE).conf

# AUTORUN (ADR-016): see FreeRTOS Makefile for rationale. Default
# 0 (B1 gated). Forwarded to cmake via west on both configure and
# build so west's cache-difference detection auto-pristines when
# the operator flips the flag between campaigns.
AUTORUN ?= 0
ifeq ($(AUTORUN),1)
  AUTORUN_VAL := 1
else
  AUTORUN_VAL := 0
endif

.PHONY: all configure build clean distclean pristine

# Default target: configure if build dir missing, then build.
# This makes `make PROFILE=...` work on a fresh checkout
# (reviewer round-5 #11 -- previously `make build` on a
# pristine tree failed because the build dir was not yet
# CMake-configured).
all:
	@if [ ! -d $(BUILD_DIR)/zephyr ]; then \
	    $(MAKE) configure; \
	fi
	@$(MAKE) build

configure:
	cd $(ZEPHYR_ROOT) && west build -b $(BOARD) benchmark_zephyr \
	    -d build/$(PROFILE) --pristine \
	    -- -DEXTRA_CONF_FILE=$(CONF_FILE) \
	       -DBENCH_AUTORUN=$(AUTORUN_VAL) \
	       -DCMAKE_EXPORT_COMPILE_COMMANDS=ON

# Force a fresh CMake configure (drops cache + reconfigures).
# Useful after touching CMakeLists.txt / Kconfig / device tree.
pristine: distclean configure

# Incremental rebuild. west auto-pristines if a forwarded -D
# differs from the cached value.
build:
	cd $(ZEPHYR_ROOT) && west build -d build/$(PROFILE) \
	    -- -DBENCH_AUTORUN=$(AUTORUN_VAL)

clean:
	cd $(ZEPHYR_ROOT) && west build -d build/$(PROFILE) -t clean

distclean:
	rm -rf $(BUILD_DIR)
