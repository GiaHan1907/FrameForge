"""Entry point for ``python -m frameforge``.

Runs the CLI headless mode — process videos from terminal without Streamlit.
"""

from core.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
