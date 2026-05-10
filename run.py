"""Entry shim: `python run.py` from repo root."""

from reddit_intel.main import main

if __name__ == "__main__":
    raise SystemExit(main())
