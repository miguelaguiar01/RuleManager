#!/usr/bin/env python3
"""Short entry point for the data audit, so you can run:

    uv run audit.py --provider bb
    uv run audit.py --provider wm --source mv
    uv run audit.py                      # every provider in the config

Equivalent to `python -m analysis`.
"""
from analysis.__main__ import main

if __name__ == "__main__":
    main()
