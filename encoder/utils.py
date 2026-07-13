"""Utility functions for mediaworker.

Provides logging setup, safe file operations, and helper functions.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path

def setup_logging(log_dir: Path, level: int = logging.INFO) -> logging.Logger:
    """Configure logging to both file and stdout.

    Args:
        log_dir: Directory where log file will be created.
        level: Logging level (default: INFO).

    Returns:
        Configured logger instance.
    """
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "mediaworker.log"

    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )
    return logging.getLogger("mediaworker")


def ensure_dir(path: Path) -> None:
    """Ensure a directory exists, creating parents if necessary.

    Args:
        path: Directory to create.
    """
    path.mkdir(parents=True, exist_ok=True)


def safe_rename(src: Path, dst: Path) -> None:
    """Atomically rename a file, replacing destination if it exists.

    Uses os.replace which is atomic on POSIX and Windows (replaces file).

    Args:
        src: Source file path.
        dst: Destination file path.
    """
    # Ensure parent directory exists
    ensure_dir(dst.parent)
    # Replace destination if exists
    src.replace(dst)


def copy2(src: Path, dst: Path) -> None:
    """Copy file with metadata, creating parent directories.

    Args:
        src: Source file.
        dst: Destination file.
    """
    import shutil

    ensure_dir(dst.parent)
    shutil.copy2(src, dst)


def find_subtitle_files(video_path: Path, subtitle_exts: set[str]) -> list[Path]:
    """Find subtitle files matching a video file.

    Looks for subtitle files with the same base name (ignoring extension)
    and any of the given extensions, in the same directory as the video.
    Additionally, looks for any subtitle files in a "Subs" subdirectory
    (if it exists) relative to the video file's directory.

    Args:
        video_path: Path to the video file.
        subtitle_exts: Set of subtitle extensions (including dot, lowercased).

    Returns:
        List of matching subtitle paths, with same-directory subtitles first,
        then Subs directory subtitles, each group sorted alphabetically.
    """
    if not video_path.is_file():
        return []

    # Same directory: match by basename
    base = video_path.with_suffix("")
    same_dir: list[Path] = []
    for ext in subtitle_exts:
        candidate = base.with_suffix(ext)
        if candidate.is_file():
            same_dir.append(candidate)
    same_dir.sort()

    # Subs directory: take all files with matching extensions
    subs_dir: list[Path] = []
    subs_path = video_path.parent / "Subs"
    if subs_path.is_dir():
        for ext in subtitle_exts:
            # Use glob to find files with the extension
            subs_dir.extend(subs_path.glob(f"*{ext}"))
        subs_dir.sort()

    # Combine and deduplicate (preserving order: same_dir first)
    seen = set()
    result: list[Path] = []
    for p in same_dir + subs_dir:
        if p not in seen:
            seen.add(p)
            result.append(p)
    return result


def human_readable_bytes(num: float) -> str:
    """Convert byte count to human-readable string.

    Args:
        num: Number of bytes.

    Returns:
        Formatted string (e.g., "1.23 MB").
    """
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if abs(num) < 1024.0:
            return f"{num:3.1f} {unit}"
        num /= 1024.0
    return f"{num:.1f} PB"


if __name__ == "__main__":
    # Simple self-test
    logger = setup_logging(Path("./logs"), logging.DEBUG)
    logger.info("Utility module test log")
    print(human_readable_bytes(1234567))