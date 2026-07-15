"""Simple filesystem-based queue for media processing.

Keeps track of pending and processed files using plain text files.
Each line in the queue file is an absolute path to a media file.
"""

from __future__ import annotations

from pathlib import Path


def load_queue(queue_file: Path) -> list[Path]:
    """Load pending file paths from the queue file.

    Empty lines and lines starting with '#' are ignored.

    Args:
        queue_file: Path to the queue text file.

    Returns:
        List of absolute Path objects.
    """
    if not queue_file.is_file():
        return []
    lines = queue_file.read_text(encoding="utf-8").splitlines()
    paths: list[Path] = []
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        paths.append(Path(line))
    return paths


def save_queue(queue_file: Path, paths: list[Path]) -> None:
    """Save list of paths to the queue file, overwriting existing content.

    Args:
        queue_file: Path to the queue text file.
        paths: List of absolute Path objects to store.
    """
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    with queue_file.open("w", encoding="utf-8") as f:
        for p in paths:
            f.write(str(p) + "\n")


def move_to_done(queue_file: Path, done_file: Path, path: Path) -> None:
    """Move a single path from queue to done file.

    Removes the path from queue_file and appends it to done_file.

    Args:
        queue_file: Path to the queue text file.
        done_file: Path to the done text file.
        path: The Path to move.
    """
    # Load current queue
    pending = load_queue(queue_file)
    # Remove the path (first occurrence)
    new_pending = [p for p in pending if p != path]
    # Write back updated queue
    save_queue(queue_file, new_pending)
    # Append to done file
    done_file.parent.mkdir(parents=True, exist_ok=True)
    with done_file.open("a", encoding="utf-8") as f:
        f.write(str(path) + "\n")


def move_to_failed(queue_file: Path, failed_file: Path, path: Path) -> None:
    """Remove a path from the queue and append it to the failed file.

    Mirrors move_to_done: pulls the path out of the queue (so subsequent
    get_pending_files calls skip it) and records it in failed.txt for review.

    Args:
        queue_file: Path to the queue text file.
        failed_file: Path to the failed text file.
        path: The Path to move.
    """
    pending = load_queue(queue_file)
    new_pending = [p for p in pending if p != path]
    save_queue(queue_file, new_pending)
    failed_file.parent.mkdir(parents=True, exist_ok=True)
    with failed_file.open("a", encoding="utf-8") as f:
        f.write(str(path) + "\n")


def clear_queue(queue_file: Path) -> None:
    """Remove all entries from the queue file.

    Args:
        queue_file: Path to the queue text file.
    """
    save_queue(queue_file, [])


def is_processed(done_file: Path, path: Path) -> bool:
    """Check if a path has already been processed (exists in done file).

    Args:
        done_file: Path to the done text file.
        path: Path to check.

    Returns:
        True if path is in done file, False otherwise.
    """
    if not done_file.is_file():
        return False
    done = load_queue(done_file)
    return path in done


if __name__ == "__main__":
    # Simple self-test
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        qfile = tmp / "queue.txt"
        dfile = tmp / "done.txt"
        p1 = tmp / "a.mkv"
        p2 = tmp / "b.mkv"
        p1.touch()
        p2.touch()
        save_queue(qfile, [p1, p2])
        print("Initial queue:", load_queue(qfile))
        move_to_done(qfile, dfile, p1)
        print("After moving a.mkv:")
        print("  queue:", load_queue(qfile))
        print("  done:", load_queue(dfile))