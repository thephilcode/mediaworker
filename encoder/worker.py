"""Worker module for mediaworker.

Processes files from the queue, builds FFmpeg commands, runs encoding,
and handles moving files from processing to output.
"""

from __future__ import annotations

import logging
import re
import sys
from pathlib import Path
from typing import Optional

from .config import Config, load_config
from .ffmpeg_builder import build_ffmpeg_cmd, run_ffmpeg
from .queue import move_to_done, move_to_failed
from .scanner import get_pending_files
from .utils import ensure_dir, setup_logging, human_readable_bytes

logger = logging.getLogger("mediaworker")


def _canonical_token(encoder_name: str, codec_groups: list[tuple[str, list[str]]]) -> str | None:
    """Return the canonical filename token for ``encoder_name``.

    ``encoder_name`` is the FFmpeg encoder (``"libx265"``, ``"libopus"``); the
    token is the short name releases put in filenames. An exact match on the
    token, a substring of the encoder name (``"x265" in "libx265"``), or an
    explicit alias (``"libopus"`` listed as an alias) all resolve the group.
    """
    for token, aliases in codec_groups:
        if encoder_name == token or token in encoder_name or encoder_name in aliases:
            return token
    return None


def _rewrite_codec(stem: str, encoder_name: str, codec_groups: list[tuple[str, list[str]]]) -> str:
    """Rewrite a filename's codec tokens to reflect a re-encode.

    Only a token that names a codec *different* from the target gets rewritten
    to the target's canonical token. A token that already names the target
    codec (e.g. "HEVC" or "x265" when encoding to libx265) is left untouched,
    so a filename that already advertises the codec ("HEVC x265") is not
    mangled into "x265 x265".
    """
    target = _canonical_token(encoder_name, codec_groups)
    if target is None:
        return stem

    # Map every alias to its group's canonical token.
    alias_to_group: dict[str, str] = {}
    for group_token, aliases in codec_groups:
        for alias in aliases:
            alias_to_group[alias] = group_token

    # Longest aliases first so "eac3" beats "ac3", "H264" vs "avc", etc.
    pattern = re.compile(
        "|".join(re.escape(a) for a in sorted(alias_to_group, key=len, reverse=True))
    )

    def replace(match: re.Match) -> str:
        alias = match.group(0)
        # A token naming the target codec is already correct; leave it.
        if alias_to_group[alias] == target:
            return alias
        return target

    return pattern.sub(replace, stem)


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

    # Apply output extension override if configured
    if config.encoder.output_extension is not None:
        # Validate extension to prevent path traversal
        ext = config.encoder.output_extension
        if not ext.startswith('.'):
            logger.error(f"Output extension must start with a dot: {ext}")
            return False
        # Additional safety: ensure extension contains only safe characters (alphanumeric, dot, hyphen, underscore)
        # This prevents path separators and other dangerous characters
        import re
        if not re.match(r'^[\.\w\-]+$', ext):
            logger.error(f"Output extension contains invalid characters: {ext}")
            return False
        # Only apply if the extension is different from current suffix to avoid unnecessary changes
        if rel_path.suffix != ext:
            rel_path = rel_path.with_suffix(ext)

    # Optionally replace codec identifiers in the filename stem to reflect encoding changes
    if config.encoder.rename_by_codec:
        stem = rel_path.stem
        original_stem = stem
        # Video codec replacement (if not copying video)
        if not config.encoder.copy_video:
            # Each group lists every alias releases use for one codec; the
            # first entry is the canonical token we rename to. A token that
            # already names the target codec is left alone (so "HEVC x265"
            # doesn't become "x265 x265"); tokens naming a *different* codec
            # are rewritten to the target's canonical token.
            video_codec_aliases = [
                ("x264", ["x264", "h264", "H264", "avc", "AVC"]),
                ("x265", ["x265", "h265", "H265", "hevc", "HEVC"]),
                ("vp9",  ["vp9", "VP9", "vp09"]),
                ("av1",  ["av1", "AV1"]),
            ]
            stem = _rewrite_codec(stem, config.encoder.video_codec, video_codec_aliases)
        # Audio codec replacement (if not copying audio)
        if not config.encoder.copy_audio:
            audio_codec_aliases = [
                ("aac",  ["aac", "AAC"]),
                ("ac3",  ["ac3", "AC3"]),
                # Encoder aliases ("libopus", "libmp3lame") so they map to
                # the right group; the rewrite step treats them like any
                # other alias and skips them when the encoder matches them.
                ("opus", ["opus", "OPUS", "libopus"]),
                ("mp3",  ["mp3", "MP3", "libmp3lame"]),
                ("flac", ["flac", "FLAC"]),
                ("ddp",  ["ddp", "DDP", "eac3", "EAC3"]),  # Dolby Digital Plus
            ]
            stem = _rewrite_codec(stem, config.encoder.audio_codec, audio_codec_aliases)
        # If the stem changed, update the relative path
        if stem != original_stem:
            # Preserve the suffix (which may have been changed by output_extension override)
            rel_path = rel_path.parent / (stem + rel_path.suffix)

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
        logger.error(f"FFmpeg command: {' '.join(cmd)}")
        # FFmpeg prints the banner first and errors last; show the tail.
        logger.error(f"FFmpeg stderr (tail): {(result.stderr or '')[-2000:]}")
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
    # ponytail: in-memory attempt count; resets each run. A crash mid-batch loses
    # this, but a re-run re-queues via get_pending_files anyway, so no need to persist.
    attempts: dict[Path, int] = {}
    max_attempts = config.encoder.max_attempts
    queue_file = config.directories.processing / "queue.txt"
    done_file = config.directories.processing / "done.txt"
    failed_file = config.directories.processing / "failed.txt"

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
            move_to_done(queue_file, done_file, file_path)
            processed += 1
            attempts.pop(file_path, None)
        else:
            attempts[file_path] = attempts.get(file_path, 0) + 1
            if attempts[file_path] >= max_attempts:
                # Exhausted retries: pull it out of the queue so the run can
                # continue past it. Recorded in failed.txt for the user to inspect.
                logger.error(
                    f"Giving up on {file_path} after {attempts[file_path]} attempt(s); "
                    f"moved to {failed_file.name} for review."
                )
                move_to_failed(queue_file, failed_file, file_path)
                failed += 1
            else:
                # Leave in queue; get_pending_files re-serves it next iteration.
                logger.error(
                    f"Failed to process {file_path}; will retry "
                    f"({attempts[file_path]}/{max_attempts})."
                )

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