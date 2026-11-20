import os
import platform
import logging
import subprocess
import shutil
from pathlib import Path

import zipfile

from ..config import MPV_DIRECTORY
from ..common import get_github_release, download_file, remove_anime4k


def _get_os_type() -> str:
    """Get OS type for Anime4K download."""
    return "Windows" if platform.system() == "Windows" else "Mac_Linux"


def _get_latest_release_info() -> dict:
    """Get latest release information from GitHub."""
    try:
        return get_github_release("Tama47/Anime4K")
    except Exception as err:
        logging.error("Failed to get latest Anime4K release: %s", err)
        raise


def _build_download_url(mode: str) -> str:
    """Build download URL for Anime4K based on mode and OS."""
    os_type = _get_os_type()
    latest_release = _get_latest_release_info()

    # Get download path from first release asset
    download_path = os.path.dirname(list(latest_release.values())[0])
    download_link = f"{download_path}/GLSL_{os_type}_{mode}-end.zip"

    return download_link


def _cleanup_macos_artifacts(directory: Path) -> None:
    """Remove macOS-specific artifacts from extraction."""
    macos_path = directory / "__MACOSX"
    if macos_path.exists():
        try:
            shutil.rmtree(macos_path)
            logging.debug("Removed macOS artifacts from %s", macos_path)
        except OSError as err:
            logging.warning("Failed to remove macOS artifacts: %s", err)


def _extract_with_tar(zip_path: Path, dest_path: Path) -> bool:
    """Extract archive using tar command."""
    try:
        subprocess.run(
            ["tar", "-xf", str(zip_path)],
            check=True,
            cwd=str(dest_path),
            capture_output=True,
            text=True,
        )
        logging.debug("Successfully extracted %s to %s", zip_path, dest_path)
        return True
    except subprocess.CalledProcessError as err:
        logging.error(
            "Failed to extract with tar: %s", err.stderr if err.stderr else err
        )
        return False
    except FileNotFoundError:
        logging.error("tar command not found")
        return False


def _extract_with_python(zip_path: Path, dest_path: Path) -> bool:
    """Extract archive using Python's zipfile module as fallback."""
    try:
        with zipfile.ZipFile(zip_path, "r") as zip_ref:
            zip_ref.extractall(dest_path)
        logging.debug(
            "Successfully extracted %s to %s using Python zipfile", zip_path, dest_path
        )
        return True
    except Exception as err:
        logging.error("Failed to extract with Python zipfile: %s", err)
        return False


def _remove_archive(archive_path: Path) -> None:
    """Remove archive file after extraction."""
    try:
        archive_path.unlink()
        logging.debug("Removed archive file: %s", archive_path)
    except OSError as err:
        logging.warning("Failed to remove archive file %s: %s", archive_path, err)


def get_anime4k_download_link(mode: str = "High") -> str:
    """
    Get download link for Anime4K based on mode and platform.

    Args:
        mode: Quality mode ("High", "Medium", "Low", etc.)

    Returns:
        Download URL for the appropriate Anime4K package

    Raises:
        Exception: If unable to get release information
    """
    if mode not in ["High", "Medium", "Low", "Ultra"]:
        logging.warning("Unknown mode '%s', defaulting to 'High'", mode)
        mode = "High"

    return _build_download_url(mode)


def extract_anime4k(zip_path: str, dep_path: str) -> bool:
    """
    Extract Anime4K archive to specified directory.

    Args:
        zip_path: Path to the zip archive
        dep_path: Destination path for extraction

    Returns:
        True if extraction was successful, False otherwise
    """
    zip_path_obj = Path(zip_path)
    dep_path_obj = Path(dep_path)

    if not zip_path_obj.exists():
        logging.error("Archive file not found: %s", zip_path)
        return False

    logging.debug("Extracting Anime4K from %s to %s", zip_path, dep_path)

    # Try tar first (faster and more reliable), then fallback to Python zipfile
    success = _extract_with_tar(zip_path_obj, dep_path_obj)
    if not success:
        logging.info("Falling back to Python zipfile extraction")
        success = _extract_with_python(zip_path_obj, dep_path_obj)

    if success:
        # Clean up archive and macOS artifacts
        _remove_archive(zip_path_obj)
        _cleanup_macos_artifacts(dep_path_obj)
        logging.info("Successfully extracted Anime4K")
        return True

    logging.error("Failed to extract Anime4K archive")
    return False


def download_anime4k(mode: str) -> bool:
    """
    Download and extract Anime4K shaders.

    Args:
        mode: Quality mode ("High", "Medium", "Low", "Remove")

    Returns:
        True if download/extraction was successful, False otherwise
    """
    if mode == "Remove":
        try:
            remove_anime4k()
            logging.info("Anime4K removed successfully")
            return True
        except Exception as err:
            logging.error("Failed to remove Anime4K: %s", err)
            return False

    # Ensure MPV directory exists
    mpv_path = Path(MPV_DIRECTORY)
    mpv_path.mkdir(parents=True, exist_ok=True)

    archive_path = mpv_path / "anime4k.zip"

    if archive_path.exists():
        logging.warning("Archive already exists at: %s", archive_path)
        return True

    try:
        # Get download link and download file
        download_link = get_anime4k_download_link(mode)
        logging.info("Downloading Anime4K (%s mode)...", mode)
        download_file(download_link, str(archive_path))

        # Extract the archive
        success = extract_anime4k(str(archive_path), str(mpv_path))

        if success:
            logging.info("Anime4K download and extraction completed successfully")
        else:
            logging.error("Anime4K extraction failed")

        return success

    except Exception as err:
        logging.error("Failed to download Anime4K: %s", err)
        # Clean up partial download
        if archive_path.exists():
            _remove_archive(archive_path)
        return False


if __name__ == "__main__":
    download_anime4k("High")
