#!/usr/bin/env python3
"""
collect_results.py

Legge l'output del benchmark dal VCP della board (USART3) e salva
le righe CSV in un file. Mostra anche le statistiche stampate a console.

Uso:
    ./collect_results.py --port /dev/ttyACM0 --rtos chibios \
                         --output results/chibios_results.csv

Opzioni:
    --port      Path della seriale (default: /dev/ttyACM0)
    --baud      Baudrate (default: 115200)
    --rtos      Nome RTOS atteso (chibios | freertos | zephyr)
    --output    File CSV di output (default: results/<rtos>_results.csv)
    --timeout   Secondi senza nuove righe prima di chiudere (default: 30)
"""

import argparse
import re
import sys
import time
from pathlib import Path

try:
    import serial
except ImportError:
    print("ERRORE: pyserial non installato. Esegui: pip install pyserial",
          file=sys.stderr)
    sys.exit(1)


CSV_HEADER = "rtos,test_name,iteration,cycles,microseconds"
CSV_LINE_RE = re.compile(
    r"^(chibios|freertos|zephyr),(\w+),(\d+),(\d+),([\d.]+)$"
)
DONE_MARKER = "BENCHMARK COMPLETE"


def main():
    parser = argparse.ArgumentParser(
        description="Raccoglie i risultati del benchmark via UART."
    )
    parser.add_argument("--port", default="/dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=115200)
    parser.add_argument("--rtos", required=True,
                       choices=["chibios", "freertos", "zephyr"])
    parser.add_argument("--output", default=None)
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    output_path = Path(args.output) if args.output else \
                  Path(f"results/{args.rtos}_results.csv")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    print(f"Apro {args.port} @ {args.baud} baud...")
    print(f"Output: {output_path}")
    print(f"Premi RESET sulla board per avviare il benchmark.\n")

    csv_lines = [CSV_HEADER]
    last_data_time = time.time()
    found_any_data = False
    done_seen = False

    with serial.Serial(args.port, args.baud, timeout=1) as ser:
        while True:
            line = ser.readline().decode("utf-8", errors="ignore").strip()
            if not line:
                # Timeout di lettura: controlla se troppo tempo senza dati
                if found_any_data and \
                   (time.time() - last_data_time) > args.timeout:
                    print(f"\nNessun dato per {args.timeout}s, chiudo.")
                    break
                continue

            last_data_time = time.time()

            # Echo a console
            print(line)

            # Riconosci la fine
            if DONE_MARKER in line:
                done_seen = True
                # Continua a leggere ancora qualche secondo
                # per catturare eventuali righe in coda
                continue

            # Match CSV row
            m = CSV_LINE_RE.match(line)
            if m:
                rtos_in_line = m.group(1)
                if rtos_in_line != args.rtos:
                    print(f"  WARN: rtos mismatch ({rtos_in_line} != "
                          f"{args.rtos}), continuo comunque", file=sys.stderr)
                csv_lines.append(line)
                found_any_data = True

    # Scrivi il CSV
    with output_path.open("w") as f:
        f.write("\n".join(csv_lines) + "\n")

    print(f"\nSalvati {len(csv_lines) - 1} sample in {output_path}")
    if not done_seen:
        print("ATTENZIONE: il marker BENCHMARK COMPLETE non e' stato visto.")
        print("Verifica che il benchmark sia stato eseguito completamente.")


if __name__ == "__main__":
    main()
