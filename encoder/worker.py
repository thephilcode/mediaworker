"""Worker module for mediaworker.

Processes files from the queue, builds FFmpeg commands, runs encoding,
and handles moving files from processing to output.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from .config import Config
from .ffmpeg_builder import build_ffmpeg_cmd, run_ffmpeg
from .queue import load_queue, save_queue, move_to_done, is_processed
from .scanner import get_pending_files
from .utils import ensure_dir, setup_logging, human_readable_bytes

logger = logging.getLogger("mediaworker")


def process_file(config: Config, input_path: Path) -> bool:
    """Process a single video file.

    Args:
        config: Application configuration.
        input_path: Absolute path to the source video file.

    Returns:
        True if processing succeeded, False otherwise.
    """
    # Determine output path preserving relative structure
    try:
        rel_path = input_path.relative_to(config.directories.input)
    except ValueError:
        # If input_path is not under input directory (should not happen)
        logger.error(f"File {input_path} is not under input directory {config.directories.input}")
        return False

    output_path = config.directories.output / rel_path
    # Ensure output directory exists
    ensure_dir(output_path.parent)

    # Intermediate file in processing directory (to allow atomic move)
    intermediate_path = config.directories.processing / rel_path
    ensure_dir(intermediate_path.parent)

    logger.info(f"Processing: {input_path}")
    logger.info(f"  -> Output: {output_path}")

    # Build FFmpeg command
    try:
        cmd = build_ffmpeg_cmd(config, input_path, intermediate_path)
    except Exception as e:
        logger.exception(f"Failed to build FFmpeg command for {input_path}: {e}")
        return False

    logger.debug(f"FFmpeg command: {' '.join(cmd)}")

    # Run FFmpeg
    try:
        result = run_ffmpeg(cmd)
    except Exception as e:
        logger.exception(f"Failed to run FFmpeg for {input_path}: {e}")
        return False

    if result.returncode != 0:
        logger.error(f"FFmpeg failed for {input_path} with return code {result.returncode}")
        logger.error(f"FFmpeg stderr: {result.stderr[:500]}")  # limit log size
        return False

    # Log output size
    try:
        in_size = input_path.stat().st_size
        out_size = intermediate_path.stat().st_size
        logger.info(
            f"Encoded {human_readable_bytes(in_size)} -> {human_readable_bytes(out_size)} "
            f"({out_size/in_size*100:.1f}% of original)"
        )
    except FileNotFoundError:
        pass  # sizes not critical

    # Atomically move intermediate to output (replace if exists)
    try:
        intermediate_path.replace(output_path)
    except Exception as e:
        logger.exception(f"Failed to move {intermediate_path} to {output_path}: {e}")
        return False

    logger.info(f"Successfully processed {input_path}")
    return True


def worker_loop(config: Config, target_count: Optional[int] = None) -> int:
    """Process files from the queue until queue empty or target reached.

    Args:
        config: Application configuration.
        target_count: Maximum number of files to process (None for all).

    Returns:
        Number of files processed successfully.
    """
    processed = 0
    failed = 0

    while True:
        pending = get_pending_files(config)
        if not pending:
            logger.info("No pending files in queue.")
            break

        if target_count is not None and processed >= target_count:
            logger.info(f"Reached target count of {target_count} files.")
            break

        file_path = pending[0]  # process in order
        logger.info(f"Starting file {processed + 1} of {len(pending)}: {file_path.name}")

        success = process_file(config, file_path)
        if success:
            # Mark as processed (move from queue to done)
            move_to_done(
                config.directories.processing / "queue.txt",
                config.directories.processing / "done.txt",
                file_path,
            )
            processed += 1
        else:
            failed += 1
            # Leave in queue for retry (could implement retry limit later)
            logger.error(f"Failed to process {file_path}; it remains in queue for retry.")

    logger.info(f"Worker loop finished. Processed: {processed}, Failed: {failed}")
    return processed


def main() -> None:
    """CLI entry point for the worker subcommand."""
    import argparse

    parser = argparse.ArgumentParser(description="Encode media files from the queue.")
    parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Maximum number of files to process (default: all)",
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="Path to TOML configuration file",
    )
    args = parser.parse_args()

    # Setup logging early
    try:
        config = load_config(args.config)
    except Exception as e:
        print(f"Failed to load config: {e}", file=sys.stderr)
        sys.exit(1)

    log_dir = config.directories.logs
    ensure_dir(log_dir)
    setup_logging(log_dir, level=logging.INFO)

    logger.info("Starting mediaworker encoder")
    logger.info(f"Config loaded from: {args.config}")
    logger.info(f"Input: {config.directories.input}")
    logger.info(f"Output: {config.directories.output}")
    logger.info(f"Processing: {config.directories.processing}")
    logger.info(f"Logs: {config.directories.logs}")

    worker_loop(config, target_count=args.count)


if __name__ == "__main__":
    main()