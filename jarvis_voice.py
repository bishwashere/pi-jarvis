import sys

sys.pycache_prefix = "/home/jarvis/jarvis/runtime/cache/pycache"

from conversation_loop import run_assistant


if __name__ == "__main__":
    try:
        run_assistant()
    except KeyboardInterrupt:
        print("\nStopped.")
