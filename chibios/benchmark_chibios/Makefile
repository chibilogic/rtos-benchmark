##############################################################################
# Build globals
##############################################################################

# Compiler options here.
ifeq ($(USE_OPT),)
  USE_OPT = -O2 -ggdb -fomit-frame-pointer -falign-functions=16
endif

# C specific options here (added to USE_OPT).
ifeq ($(USE_COPT),)
  USE_COPT = -std=c11
endif

# C++ specific options here (added to USE_OPT).
ifeq ($(USE_CPPOPT),)
  USE_CPPOPT = -fno-rtti
endif

# Enable this if you want the linker to remove unused code and data.
ifeq ($(USE_LINK_GC),)
  USE_LINK_GC = yes
endif

# Linker extra options here.
ifeq ($(USE_LDOPT),)
  USE_LDOPT =
endif

# Enable this if you want link time optimizations (LTO).
# DISATTIVATA per coerenza con FreeRTOS/Zephyr nel benchmark.
ifeq ($(USE_LTO),)
  USE_LTO = no
endif

# Enable this if you want to see the full log while compiling.
ifeq ($(USE_VERBOSE_COMPILE),)
  USE_VERBOSE_COMPILE = no
endif

# If enabled, this option makes the build process faster by not compiling
# modules not used in the current configuration.
ifeq ($(USE_SMART_BUILD),)
  USE_SMART_BUILD = yes
endif

##############################################################################
# Architecture or project specific options
##############################################################################

# Stack size to be allocated to the Cortex-M process stack.
ifeq ($(USE_PROCESS_STACKSIZE),)
  USE_PROCESS_STACKSIZE = 0x400
endif

# Stack size to the allocated to the Cortex-M main/exceptions stack.
ifeq ($(USE_EXCEPTIONS_STACKSIZE),)
  USE_EXCEPTIONS_STACKSIZE = 0x400
endif

# Enables the use of FPU.
ifeq ($(USE_FPU),)
  USE_FPU = hard
endif

# FPU-related options.
ifeq ($(USE_FPU_OPT),)
  USE_FPU_OPT = -mfloat-abi=$(USE_FPU) -mfpu=fpv5-d16
endif

##############################################################################
# Project, target, sources and paths
##############################################################################

# Define project name here
PROJECT = benchmark_chibios

# Target settings.
MCU  = cortex-m7

# Imported source files and paths.
CHIBIOS  := ../ChibiOS
CONFDIR  := ./cfg
BUILDDIR := ./build
DEPDIR   := ./.dep

# HAL-OSAL files (optional).
include $(CHIBIOS)/os/hal/hal.mk
include $(CHIBIOS)/os/hal/ports/STM32/STM32H7xx/platform.mk
include $(CHIBIOS)/os/hal/boards/ST_NUCLEO144_H743ZI/board.mk
include $(CHIBIOS)/os/hal/osal/rt-nil/osal.mk

# RTOS files (optional).
include $(CHIBIOS)/os/rt/rt.mk
include $(CHIBIOS)/os/common/ports/ARMv7-M/compilers/GCC/mk/port.mk

# Auto-build files in ./source recursively.
include $(CHIBIOS)/tools/mk/autobuild.mk

# Other files (optional).
include $(CHIBIOS)/os/test/test.mk
include $(CHIBIOS)/test/rt/rt_test.mk
include $(CHIBIOS)/test/oslib/oslib_test.mk
include $(CHIBIOS)/os/hal/lib/streams/streams.mk
include $(CHIBIOS)/os/various/shell/shell.mk

# Define linker script file here.
LDSCRIPT= $(STARTUPLD)/STM32H743xI.ld

# C sources that can be compiled in ARM or THUMB mode depending on the global
# setting.
CSRC = $(ALLCSRC) \
       $(TESTSRC) \
       ../../common/dwt_cycle_counter.c \
       ../../common/benchmark_stats.c \
       main.c \
       test_ctxsw_irq.c \
       test_ctxsw_mutex.c

# C++ sources that can be compiled in ARM or THUMB mode depending on the global
# setting.
CPPSRC =

# Inclusion directories.
INCDIR = $(CONFDIR) $(ALLINC) $(TESTINC) ../../common

# Define C warning options here.
CWARN = -Wall -Wextra -Wundef -Wstrict-prototypes

# Define C++ warning options here.
CPPWARN = -Wall -Wextra -Wundef

##############################################################################
# Project compile options
##############################################################################

# List all user C define here, like -D_DEBUG=1
UDEFS = -DBENCH_RTOS_CHIBIOS

# Define ASM defines here
UADEFS =

# List all user directories here.
UINCDIR =

# List the user directory to look for the libraries here.
ULIBDIR =

# List all user libraries here.
ULIBS = -lm

##############################################################################
# Common rules
##############################################################################

RULESPATH = $(CHIBIOS)/os/common/startup/ARMv7-M/compilers/GCC
include $(RULESPATH)/arm-none-eabi.mk
include $(CHIBIOS)/os/common/startup/ARMv7-M/compilers/GCC/mk/startup_stm32h7xx.mk
include $(CHIBIOS)/tools/mk/rules.mk
