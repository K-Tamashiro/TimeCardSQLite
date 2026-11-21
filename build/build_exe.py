"""Build a standalone Windows executable bundle and portable ZIP using PyInstaller."""

from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from timecard.version import APP_VERSION  # noqa: E402


def _copy_distribution_docs(dist_dir):
    shutil.copy2(ROOT / "build" / "README.txt", dist_dir / "README.txt")
    shutil.copy2(ROOT / "LICENSE", dist_dir / "LICENSE.txt")


def _create_portable_zip(dist_dir, out_dir):
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"PersonalTimeCard-{APP_VERSION}-win64.zip"
    if zip_path.exists():
        zip_path.unlink()
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for file_path in sorted(dist_dir.rglob("*")):
            if file_path.is_file():
                arcname = Path("PersonalTimeCard") / file_path.relative_to(dist_dir)
                zf.write(file_path, arcname.as_posix())
    return zip_path


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
        "--version-file",
        str(ROOT / "build" / "version_info.txt"),
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

    dist_dir = ROOT / "dist" / "PersonalTimeCard"
    _copy_distribution_docs(dist_dir)
    zip_path = _create_portable_zip(dist_dir, ROOT / "Release")

    print("Build finished:", dist_dir / "PersonalTimeCard.exe")
    print("Portable ZIP  :", zip_path)


if __name__ == "__main__":
    main()
