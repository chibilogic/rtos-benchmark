# Toolchain runtime notices — Phase 1 prebuilt firmware

The six publishable ELF images statically link runtime components. This file is a
DELIBERATELY OVER-INCLUSIVE reproduction: it bundles the FULL pinned source-tree
licence texts under `LICENSES/` and maps each per-image runtime component to its
text. The bundle is deliberately over-inclusive of the actually-linked subset;
it is reproduced so the redistribution carries the applicable runtime notices.

## Per-image runtime (verified against all six campaign .map files)
- ChibiOS ELFs: newlib (`libg.a`) + math (`libm.a`) + `libgcc.a` (Arm GNU
  Toolchain 14.2.rel1).
- FreeRTOS ELFs: newlib-nano (`libc_nano.a`) + math (`libm.a`) + `libgcc.a`
  (Arm GNU Toolchain 14.2.rel1).
- Zephyr ELFs: picolibc (`picolibc/libc.a`, `liblib__libc__picolibc.a`) +
  `libgcc.a` — picolibc is WEST-MANAGED (pinned commit 01254932...), NOT from the
  Arm toolchain.

## libgcc (all images)
Copyright (C) Free Software Foundation, Inc. GPL-3.0-or-later WITH the GCC Runtime
Library Exception (version 3.1), subject to the Exception's conditions (incl. an
eligible compilation process), which permits linking libgcc into the firmware
without the firmware becoming subject to the GPL by that linkage.
Bundled texts: `LICENSES/GPL-3.0-or-later.txt`,
`LICENSES/GCC-Runtime-Library-Exception-3.1.txt`.

## newlib / newlib-nano + libm (ChibiOS, FreeRTOS)
A collection of permissive BSD-style per-file licences governed collectively by
`COPYING.NEWLIB` (principal holders: Red Hat/Cygnus, The Regents of the University
of California, Sun Microsystems, Arm, among others). libm (the math library) is
part of newlib. COPYING.NEWLIB contains binary-redistribution clauses requiring
the copyright notice, conditions and disclaimer to be reproduced in accompanying
materials.
Bundled text: `LICENSES/COPYING.NEWLIB` (the newlib licence collection for the
Arm GNU Toolchain 14.2.rel1 newlib; upstream:
https://sourceware.org/newlib/COPYING.NEWLIB).

## picolibc (Zephyr)
The Zephyr image links picolibc (west-managed; pinned commit above). The linked
picolibc runtime objects are under BSD-style permissive terms (per-file, see
`COPYING.picolibc`). NOTE: `COPYING.GPL2` in the picolibc tree applies ONLY to
NON-LINKED picolibc TEST files (`test/printf-tests.c`, `test/testcases.c`); it is
bundled here as part of the over-inclusive source-tree reproduction and its
applicability to the published Zephyr ELF is NOT asserted.
Bundled texts: `LICENSES/COPYING.picolibc` (full per-file copyright) and
`LICENSES/COPYING.GPL2` (over-inclusive; picolibc test files only).

## Provenance of the bundled texts
- `COPYING.NEWLIB`, `COPYING.picolibc`, `COPYING.GPL2`: from the pinned picolibc
  west tree (commit 01254932e8e81085817ed61fd858648584ffe37c), line endings
  normalised to LF (the upstream canonical form) and stored byte-for-byte via
  `.gitattributes` (`-text`). SHA-256 (LF):
  - COPYING.NEWLIB    fcfb5ec69b6ab52676dcc4dab7cf4338c8000ef97812dadd35b8592a640a8419
  - COPYING.picolibc  c53b57a90e3f7891ccb9d011f4c2d06fc8b3afefca4b315253b962e3e519a774
  - COPYING.GPL2      231f7edcc7352d7734a96eef0b8030f77982678c516876fcb81e25b32d68564c
- `GCC-Runtime-Library-Exception-3.1.txt`: GCC Runtime Library Exception 3.1
  (gcc-mirror COPYING.RUNTIME; matches the GNU 3.1 text). SHA-256:
  9d6b43ce4d8de0c878bf16b54d8e7a10d9bd42b75178153e3af6a815bdc90f74
- `GPL-3.0-or-later.txt`: the project GPL-3.0 text (also `../LICENSE`).

## Status
The runtime notice texts are bundled under `LICENSES/` (over-inclusive of the
actually-linked subset) so the redistribution carries the applicable notices.
See the ADR-009 libc disclaimer.
