##############################################################################
# Build globals - RTOS Benchmark, ChibiOS port
##############################################################################
#
# Build profiles (ADR-011):
#
#   make PROFILE=fair_perf            (default, publishable)
#   make PROFILE=realistic_tickless   (publishable, low-power scenario)
#   make PROFILE=debug_dev            (development only, NOT for benchmark)
#
# Each profile builds into build/<profile>/.
#
##############################################################################

# Default profile.
PROFILE ?= fair_perf

# Profile-specific compile flags + macro injection.
ifeq ($(PROFILE),fair_perf)
  PROFILE_DEFINE = -DBENCH_PROFILE_FAIR_PERF=1
  PROFILE_OPT_LEVEL = -O2
else ifeq ($(PROFILE),realistic_tickless)
  PROFILE_DEFINE = -DBENCH_PROFILE_REALISTIC_TICKLESS=1
  PROFILE_OPT_LEVEL = -O2
else ifeq ($(PROFILE),debug_dev)
  # Development-only profile (ADR-011). NOT for publication.
  # Same RTOS config as fair_perf (no asserts, ADR-009) but with
  # -Og -g3 and no frame-pointer omission for usable stack traces.
  PROFILE_DEFINE = -DBENCH_PROFILE_DEBUG_DEV=1
  PROFILE_OPT_LEVEL = -Og
else
  $(error Unknown PROFILE '$(PROFILE)'. Use: fair_perf | realistic_tickless | debug_dev)
endif

# Common GCC flags per ADR-009 (identical across the publishable
# profiles; debug_dev keeps frame pointers for stack traces).
ifeq ($(PROFILE),debug_dev)
  COMMON_OPT = -g3 \
               -ffunction-sections -fdata-sections \
               -fno-common -fno-strict-aliasing
else
  COMMON_OPT = -ggdb \
               -fomit-frame-pointer -falign-functions=16 \
               -ffunction-sections -fdata-sections \
               -fno-common -fno-strict-aliasing
endif

# Compiler options.
ifeq ($(USE_OPT),)
  USE_OPT = $(PROFILE_OPT_LEVEL) $(COMMON_OPT)
endif

# C-specific options.
ifeq ($(USE_COPT),)
  USE_COPT = -std=c11
endif

# C++-specific options.
ifeq ($(USE_CPPOPT),)
  USE_CPPOPT = -fno-rtti
endif

# Dead-code/data elimination.
ifeq ($(USE_LINK_GC),)
  USE_LINK_GC = yes
endif

# Linker extra options. ChibiOS rules.mk already prepends a comma,
# so USE_LDOPT must NOT start with a comma.
# (--cref is already in the default LDFLAGS of rules.mk; we add only
#  --print-memory-usage.)
ifeq ($(USE_LDOPT),)
  USE_LDOPT = --print-memory-usage
endif

# LTO disabled (ADR-009: symmetry with FreeRTOS/Zephyr).
ifeq ($(USE_LTO),)
  USE_LTO = no
endif

ifeq ($(USE_VERBOSE_COMPILE),)
  USE_VERBOSE_COMPILE = no
endif

ifeq ($(USE_SMART_BUILD),)
  USE_SMART_BUILD = yes
endif

##############################################################################
# Architecture-specific options
##############################################################################

ifeq ($(USE_PROCESS_STACKSIZE),)
  USE_PROCESS_STACKSIZE = 0x400
endif

ifeq ($(USE_EXCEPTIONS_STACKSIZE),)
  USE_EXCEPTIONS_STACKSIZE = 0x400
endif

ifeq ($(USE_FPU),)
  USE_FPU = hard
endif

ifeq ($(USE_FPU_OPT),)
  USE_FPU_OPT = -mfloat-abi=$(USE_FPU) -mfpu=fpv5-d16
endif

##############################################################################
# Project, target, sources and paths
##############################################################################

PROJECT = benchmark_chibios

MCU = cortex-m7

CHIBIOS  := ../ChibiOS
CONFDIR  := ./cfg
BUILDDIR := ./build/$(PROFILE)
DEPDIR   := ./.dep/$(PROFILE)

# Licensing files.
include $(CHIBIOS)/os/license/license.mk

# Startup (must precede CSRC= so ALLCSRC/ALLXASMSRC are populated).
include $(CHIBIOS)/os/common/startup/ARMCMx/compilers/GCC/mk/startup_stm32h7xx.mk

# HAL-OSAL.
include $(CHIBIOS)/os/hal/hal.mk
include $(CHIBIOS)/os/hal/ports/STM32/STM32H7xx/platform.mk
include $(CHIBIOS)/os/hal/boards/ST_STM32H750XB_DISCOVERY/board.mk
include $(CHIBIOS)/os/hal/osal/rt-nil/osal.mk

# RT kernel + port.
include $(CHIBIOS)/os/rt/rt.mk
include $(CHIBIOS)/os/common/ports/ARMv7-M/compilers/GCC/mk/port.mk

# Auto-build of ./source/.
include $(CHIBIOS)/tools/mk/autobuild.mk

# rt_test / oslib_test / streams / shell intentionally NOT included:
# the benchmark has its own runner.

# Linker script for STM32H750xB (128 KB Flash).
LDSCRIPT = $(STARTUPLD)/STM32H750xB.ld

# Sources. Test files are added incrementally as ADR-014 lands.
CSRC = $(ALLCSRC) \
       $(TESTSRC) \
       $(CONFDIR)/portab.c \
       ../../common/dwt_cycle_counter.c \
       ../../common/benchmark_stats.c \
       ../../common/bench_button.c \
       main.c \
       test_ctxsw_irq.c \
       test_thread_handoff.c \
       test_mutex_uncontended.c \
       test_mutex_pi.c

CPPSRC  = $(ALLCPPSRC)
ASMSRC  = $(ALLASMSRC)
ASMXSRC = $(ALLXASMSRC)

INCDIR = $(CONFDIR) $(ALLINC) $(TESTINC) ../../common

CWARN   = -Wall -Wextra -Wundef -Wstrict-prototypes
CPPWARN = -Wall -Wextra -Wundef

##############################################################################
# Project compile defines
##############################################################################

UDEFS = -DBENCH_RTOS_CHIBIOS -DSTM32H750xx $(PROFILE_DEFINE)

# Optional: skip the B1 button gating between tests (ADR-016).
# Pass AUTORUN=1 on the make command line, e.g.:
#     make AUTORUN=1 -j
# Default OFF (the publishable flow uses B1 to avoid the LA-arm race).
ifeq ($(AUTORUN),1)
    UDEFS += -DBENCH_AUTORUN=1
endif

UADEFS =
UINCDIR =
ULIBDIR =
ULIBS = -lm

##############################################################################
# Common rules
##############################################################################

RULESPATH = $(CHIBIOS)/os/common/startup/ARMCMx/compilers/GCC/mk
include $(RULESPATH)/arm-none-eabi.mk
include $(RULESPATH)/rules.mk

##############################################################################
# C3-step2: compile_commands.json synthesis (ADR-009 audit support)
##############################################################################
# `make compile-commands PROFILE=<profile>` runs a `make -B -n all`
# dry-run, pipes the recipe text through the synth script, and
# writes $(BUILDDIR)/compile_commands.json. Used by
# scripts/cflags_audit.py --rtos chibios as the read-back of the
# effective compile flags. No object files are produced.

.PHONY: compile-commands
compile-commands:
	@mkdir -p $(BUILDDIR)
	@$(MAKE) -B -n PROFILE=$(PROFILE) all \
	    > $(BUILDDIR)/make-dry-run.log \
	    2> $(BUILDDIR)/make-dry-run.stderr
	@python ../../scripts/chibios_synth_compile_commands.py \
	    --make-log $(BUILDDIR)/make-dry-run.log \
	    --build-dir $(BUILDDIR) \
	    --workdir .
