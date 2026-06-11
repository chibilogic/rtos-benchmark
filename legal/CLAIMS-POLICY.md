# Comparative-claims policy (Phase 1)

> READY FOR LEGAL REVIEW — NOT LEGAL SIGN-OFF.
>
> Italian comparative advertising (D.Lgs 145/2007) is lawful only if it is
> objective, not misleading, not denigratory, compares homogeneous goods, does
> not create confusion, and is based on verifiable characteristics. Every claim
> must stay tied to board, RTOS version, profile and metric.

## Allowed
- "In Phase 1 DWT-only measurements on STM32H750B-DK, under the documented
  configuration, ChibiOS showed the lowest median latency in the measured
  scenarios."
- "Neutral, reproducible cross-RTOS latency benchmark on STM32H750B-DK comparing
  ChibiOS, FreeRTOS and Zephyr under documented conditions."
- "Results are valid for the tested board, toolchain, RTOS versions,
  configuration and benchmark scenarios."
- "Raw logs, checksums, configuration files and source references are published
  to allow independent verification."

## Forbidden
- "ChibiOS is faster than FreeRTOS and Zephyr." (too general / unbounded)
- "ChibiOS beats Zephyr." (aggressive / potentially denigratory)
- "FreeRTOS is slower." (not sufficiently circumscribed)

## Strictly forbidden
- "FreeRTOS and Zephyr are slower / bloated / inferior." (denigratory)

## Repository conformance (engineering verification)
The repository public content conforms to the lists above: no forbidden claims;
per-test "lowest median (this test)" framing; the report abstract is neutral and
qualified; profile-to-profile deltas are reported as measured, without
attributing them to a single internal cause; an explicit "Scope and non-claims"
section is present. (See also `notes/CLAIM-POLICY-phase1.md` for the
engineering-side sweep.)

EXTERNAL marketing copy is OUT of the engineering gate: it requires
counsel/marketing approval and must stay scoped to a named
board / version / profile / metric.

READY FOR LEGAL REVIEW — NOT LEGAL SIGN-OFF.
