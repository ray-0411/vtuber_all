"""Website entry point delegating to the shared publication implementation."""
from pathlib import Path
import runpy
import sys

ROOT = Path(__file__).resolve().parents[3]
TARGET = ROOT / "tools/publish/scripts/build_analytics_cache.py"
if __name__ == "__main__":
    defaults = {'--source': 'merged_live_data.db', '--output': 'merged_analytics_cache.db'}
    for flag, filename in defaults.items():
        if not any(arg == flag or arg.startswith(flag + "=") for arg in sys.argv[1:]):
            sys.argv.extend([flag, str(ROOT / "database/website" / filename)])
    runpy.run_path(str(TARGET), run_name="__main__")
else:
    globals().update({k: v for k, v in runpy.run_path(str(TARGET)).items() if not k.startswith("__")})
