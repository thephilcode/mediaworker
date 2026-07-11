"""Scanner module for discovering media files.

Walks the input directory recursively and returns a list of video files
that have not yet been processed (based on queue state).
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Set

from .config import Config
from .utils import find_subtitle_files


def scan_videos(config: Config) -> List[Path]:
    """Recursively scan input directory for video files.

    Args:
        config: Application configuration.

    Returns:
        List of absolute paths to video files found.
    """
    video_files: List[Path] = []
    input_dir = config.directories.input
    if not input_dir.is_dir():
        raise NotADirectoryError(f"Input directory does not exist: {input_dir}")

    # Walk recursively
    for ext in config.video_extensions:
        # Use rglob for each extension
        video_files.extend(input_dir.rglob(f"*{ext}"))

    # Deduplicate (in case a file matches multiple extensions, though unlikely)
    # Sort for deterministic order
    video_files = sorted(set(video_files))
    return video_files


def get_pending_files(config: Config) -> List[Path]:
    """Determine which video files still need processing.

    Reads the queue file (if exists) to see which files are pending.
    If no queue file exists, scans input and creates queue.

    Returns:
        List of absolute paths to video files that need processing.
    """
    from .queue import load_queue, save_queue

    processing_dir = config.directories.processing
    queue_file = processing_dir / "queue.txt"

    if queue_file.is_file():
        # Load existing queue
        pending = load_queue(queue_file)
        # Filter to only those that still exist (in case files were removed)
        pending = [p for p in pending if p.is_file()]
        # Update queue file with filtered list
        save_queue(queue_file, pending)
        return pending
    else:
        # No queue yet: scan and create initial queue
        all_videos = scan_videos(config)
        save_queue(queue_file, all_videos)
        return all_videos


def mark_as_processed(config: Config, file_path: Path) -> None:
    """Move a file from pending queue to done list.

    Args:
        config: Application configuration.
        file_path: Absolute path of the file that was processed.
    """
    from .queue import move_to_done

    processing_dir = config.directories.processing
    move_to_done(
        processing_dir / "queue.txt",
        processing_dir / "done.txt",
        file_path,
    )


if __name__ == "__main__":
    # Simple test when run directly
    import tempfile
    from .config import load_config

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # Create dummy config
        cfg = Config(
            directories=type(
                "Dirs",
                (),
                {
                    "input": tmp_path / "input",
                    "output": tmp_path / "output",
                    "processing": tmp_path / "processing",
                    "logs": tmp_path / "logs",
                },
            )()
        )
        cfg.directories.input.mkdir()
        (cfg.directories.input / "test.mkv").touch()
        pending = get_pending_files(cfg)
        print(f"Found {len(pending)} files")