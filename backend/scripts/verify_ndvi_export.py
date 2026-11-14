"""Check a Canberra v2 export with the validator used by the API."""
import argparse
from pathlib import Path
import sys

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from services.ndvi_package import validate_package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="Candidate v2 ZIP or export directory")
    args = parser.parse_args()
    try:
        package = validate_package(args.package)
    except ValueError as exc:
        parser.exit(1, f"FAIL: {exc}\n")

    latest = package["result"]
    print(f"PASS: complete package for {latest['date']}")
    print(f"Time-series observations: {len(package['timeseries'])}")
    print(f"Map points: {len(package['geojson']['features'])}")
    print(f"Reporting status: {latest['status']}")
    print("This checks package consistency, not original rasters or ecological accuracy.")
    print("No files changed. Deployment remains disabled.")


if __name__ == "__main__":
    main()
