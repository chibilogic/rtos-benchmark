/* SPDX-License-Identifier: MIT */
/*
 * Copyright (C) 2025-2026  Chibilogic s.r.l. www.chibilogic.com
 */

/**
 * @file    syscalls_stubs.c
 * @brief   Minimal newlib syscall stubs for the FreeRTOS port.
 *
 * The benchmark does not use file I/O; we only need __errno so libm
 * (sqrtf in benchmark_stats.c) links cleanly. Other syscalls are
 * already stubbed by --specs=nosys.specs.
 */

static int __errno_storage;

int *__errno(void)
{
    return &__errno_storage;
}
