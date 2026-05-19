# Host-build Makefile for the bench_compute_stats unit test
# (round-8 Item 5).
#
# Usage:
#   make            - build and run the test
#   make build      - build only
#   make run        - run the existing binary
#   make clean      - remove build artefacts
#
# Compiler: any host gcc / clang. No ARM cross-toolchain needed.
# This proves that bench_compute_stats() is RTOS-agnostic and pure
# C - exactly the property the firmware relies on.

CC      ?= gcc
CFLAGS  := -O2 -Wall -Wextra -Wno-unused-parameter -std=c11 \
           -DBENCH_HOST_BUILD \
           -DBENCH_RTOS_CHIBIOS \
           -DBENCH_PROFILE_FAIR_PERF \
           -I ../../common
LDFLAGS := -lm

SRCS    := test_bench_stats.c ../../common/benchmark_stats.c
TARGET  := test_bench_stats

ifeq ($(OS),Windows_NT)
  TARGET := $(TARGET).exe
endif

.PHONY: all build run clean

all: build run

build: $(TARGET)

$(TARGET): $(SRCS)
	$(CC) $(CFLAGS) -o $@ $^ $(LDFLAGS)

run: $(TARGET)
	./$(TARGET)

clean:
	rm -f $(TARGET)
