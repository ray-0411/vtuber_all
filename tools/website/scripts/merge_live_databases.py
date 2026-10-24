"""Website entry point delegating to the shared publication implementation."""
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[3]
TARGET = ROOT / "tools/publish/scripts/merge_live_databases.py"
if __name__ == "__main__":
    defaults = {'--current': 'live_data.db', '--legacy': 'legacy_live_data.db', '--audience': 'streamer_audience.db', '--output': 'merged_live_data.db'}
    for flag, filename in defaults.items():
        if not any(arg == flag or arg.startswith(flag + "=") for arg in sys.argv[1:]):
            sys.argv.extend([flag, str(ROOT / "database/website" / filename)])
    runpy.run_path(str(TARGET), run_name="__main__")
else:
    globals().update({k: v for k, v in runpy.run_path(str(TARGET)).items() if not k.startswith("__")})
