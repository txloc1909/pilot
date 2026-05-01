"""Entry point for the pilot CLI.

The real implementation will initialise the appropriate mode (interactive,
RPC, etc.) based on CLI arguments. For now this file only prints a placeholder
message so that the command `pilot` works out‑of‑the‑box.
"""

import sys
from argparse import ArgumentParser

def main() -> None:
    parser = ArgumentParser(prog="pilot", description="Personal coding agent harness")
    parser.add_argument("--rpc", action="store_true", help="Run in RPC mode (stub)")
    args = parser.parse_args()

    if args.rpc:
        print("[pilot] RPC mode not yet implemented.")
        sys.exit(0)
    else:
        print("[pilot] Interactive mode not yet implemented.")
        sys.exit(0)

if __name__ == "__main__":
    main()
