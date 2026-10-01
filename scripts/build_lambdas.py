"""Build the deployment bundles that Terraform uploads.

    build/ingest.zip     healthcare_pipeline + google-auth/requests (Linux wheels)
    build/transform.zip  healthcare_pipeline only; pandas/pyarrow come from the
                         AWS SDK for pandas Lambda layer, boto3 from the runtime
    build/app.zip        Streamlit app + healthcare_pipeline for the EC2 host

Run with ``make build``. Zips are written deterministically so unchanged code
produces the same hash and Terraform does not redeploy.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
PACKAGE = ROOT / "src" / "healthcare_pipeline"
LAMBDA_PYTHON = "3.12"
FIXED_TIME = (2020, 1, 1, 0, 0, 0)


def _zip_dir(source: Path, destination: Path) -> None:
    destination.unlink(missing_ok=True)
    with zipfile.ZipFile(destination, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_dir() or "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            info = zipfile.ZipInfo(path.relative_to(source).as_posix(), FIXED_TIME)
            info.external_attr = 0o644 << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    print(f"wrote {destination.relative_to(ROOT)} ({destination.stat().st_size / 1e6:.1f} MB)")


def _copy_package(target: Path) -> None:
    shutil.copytree(PACKAGE, target / PACKAGE.name, ignore=shutil.ignore_patterns("__pycache__"))


def _install_group(group: str, target: Path) -> None:
    requirements = target.parent / f"{group}-requirements.txt"
    exported = subprocess.run(
        ["uv", "export", "--frozen", "--only-group", group, "--no-hashes", "--no-emit-project"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    requirements.write_text(exported)
    subprocess.run(
        [
            "uv",
            "pip",
            "install",
            "--quiet",
            "--requirement",
            str(requirements),
            "--target",
            str(target),
            "--python-platform",
            "x86_64-manylinux2014",
            "--python-version",
            LAMBDA_PYTHON,
            "--only-binary",
            ":all:",
        ],
        cwd=ROOT,
        check=True,
    )


def main() -> None:
    BUILD.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)

        ingest = tmp_path / "ingest"
        ingest.mkdir()
        _install_group("ingest", ingest)
        _copy_package(ingest)
        _zip_dir(ingest, BUILD / "ingest.zip")

        transform = tmp_path / "transform"
        transform.mkdir()
        _copy_package(transform)
        _zip_dir(transform, BUILD / "transform.zip")

        app = tmp_path / "app"
        app.mkdir()
        _copy_package(app)
        shutil.copy(ROOT / "app" / "streamlit_app.py", app / "streamlit_app.py")
        _zip_dir(app, BUILD / "app.zip")


if __name__ == "__main__":
    sys.exit(main())
