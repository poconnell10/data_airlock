"""Allow `python -m services.engine.scripts` to print help for simulators."""

from services.engine.scripts.simulate_s3_drops import main

if __name__ == "__main__":
    raise SystemExit(main())
