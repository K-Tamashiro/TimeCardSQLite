"""Build a standalone Windows executable bundle using PyInstaller."""

from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--name",
        "PersonalTimeCard",
        "--icon",
        str(ROOT / "timecard" / "favicon.ico"),
        "--add-data",
        f"{ROOT / 'timecard' / 'assets'};timecard/assets",
        "--add-data",
        f"{ROOT / 'timecard' / 'images'};timecard/images",
        "--add-data",
        f"{ROOT / 'timecard' / 'favicon.ico'};timecard",
        str(ROOT / "run_app.py"),
    ]
    print("Running:", " ".join(cmd))
    subprocess.run(cmd, cwd=str(ROOT), check=True)
    print("Build finished:", ROOT / "dist" / "PersonalTimeCard" / "PersonalTimeCard.exe")


if __name__ == "__main__":
    main()
