import sys
from pathlib import Path

sys.pycache_prefix = str(
    Path(__file__).resolve().parent / "runtime/cache/pycache"
)

from conversation_loop import run_assistant


if __name__ == "__main__":
    try:
        run_assistant()
    except KeyboardInterrupt:
        print("\nStopped.")
