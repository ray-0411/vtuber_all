"""Website compatibility entry point using the publisher's protected sync."""
from pathlib import Path
import runpy
import sys

TARGET = Path(__file__).resolve().parents[2] / "publish/scripts/sync_merged_to_postgres.py"
if __name__ == "__main__":
    root = Path(__file__).resolve().parents[3]
    if not any(a == "--database" or a.startswith("--database=") for a in sys.argv[1:]):
        sys.argv.extend(["--database", str(root / "database/website/merged_live_data.db")])
    if not any(a == "--analytics-cache" or a.startswith("--analytics-cache=") for a in sys.argv[1:]):
        sys.argv.extend(["--analytics-cache", str(root / "database/website/merged_analytics_cache.db")])
    runpy.run_path(str(TARGET), run_name="__main__")
else:
    globals().update({k: v for k, v in runpy.run_path(str(TARGET)).items() if not k.startswith("__")})
