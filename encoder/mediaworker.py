"""Main CLI entry point for mediaworker.

Provides subcommands: scan, encode, verify, resume, clean.
"""

from __future__ import annotations

import argparse
import logging
from pathlib import Path

from .config import load_config
from .scanner import get_pending_files
from .worker import worker_loop
from .utils import setup_logging, ensure_dir, human_readable_bytes

logger = logging.getLogger("mediaworker")


def cmd_scan(args: argparse.Namespace) -> None:
    """Scan input directory and list pending files."""
    config = load_config(args.config)
    ensure_dir(config.directories.processing)
    ensure_dir(config.directories.logs)
    setup_logging(config.directories.logs, level=logging.INFO if not args.verbose else logging.DEBUG)

    pending = get_pending_files(config)
    print(f"Found {len(pending)} pending file(s) in {config.directories.input}:")
    for p in pending:
        # Show relative path for brevity
        try:
            rel = p.relative_to(config.directories.input)
        except ValueError:
            rel = p
        print(f"  {rel}")
    if args.verbose and pending:
        total_size = sum(p.stat().st_size for p in pending if p.is_file())
        print(f"Total size: {human_readable_bytes(total_size)}")


def cmd_encode(args: argparse.Namespace) -> None:
    """Process files from the queue."""
    config = load_config(args.config)
    ensure_dir(config.directories.processing)
    ensure_dir(config.directories.output)
    ensure_dir(config.directories.logs)
    setup_logging(config.directories.logs, level=logging.INFO if not args.verbose else logging.DEBUG)

    logger.info("Starting encode command")
    processed = worker_loop(config, target_count=args.count)
    logger.info(f"Encode completed. Processed {processed} file(s).")


def cmd_verify(args: argparse.Namespace) -> None:
    """Verify encoded files against source (placeholder)."""
    # TODO: Implement verification (e.g., check file exists, maybe compare duration, etc.)
    config = load_config(args.config)
    from .queue import load_queue
    done_file = config.directories.processing / "done.txt"
    if not done_file.is_file():
        print("No done files yet.")
        return
    done = load_queue(done_file)
    print(f"Verifying {len(done)} processed file(s)...")
    missing = []
    for p in done:
        out_path = config.directories.output / p.relative_to(config.directories.input)
        if not out_path.is_file():
            missing.append(p)
    if missing:
        print(f"Missing output files for {len(missing)} file(s):")
        for p in missing[:5]:
            print(f"  {p}")
        if len(missing) > 5:
            print(f"  ... and {len(missing)-5} more")
    else:
        print("All processed files have output files present.")


def cmd_resume(args: argparse.Namespace) -> None:
    """Resumes processing (same as encode)."""
    # In this design, encode already processes pending queue, so resume is same.
    # But we could have a separate flag to ignore errors? For now, just call encode.
    print("Resuming processing (equivalent to 'encode')...")
    cmd_encode(args)


def cmd_clean(args: argparse.Namespace) -> None:
    """Clean temporary files."""
    config = load_config(args.config)
    processing_dir = config.directories.processing
    if processing_dir.is_dir():
        import shutil
        print(f"Removing processing directory: {processing_dir}")
        shutil.rmtree(processing_dir)
        print("Processing directory removed.")
    else:
        print("Processing directory does not exist.")
    # Optionally also clear logs? Not by default.
    if args.logs:
        logs_dir = config.directories.logs
        if logs_dir.is_dir():
            import shutil
            print(f"Removing logs directory: {logs_dir}")
            shutil.rmtree(logs_dir)
            print("Logs directory removed.")
        else:
            print("Logs directory does not exist.")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="mediaworker - Automated media encoding worker"
    )
    parser.add_argument(
        "--config",
        type=Path,
        default=Path("config.toml"),
        help="Path to TOML configuration file",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # scan
    scan_parser = subparsers.add_parser("scan", help="Scan input directory and list pending files")
    scan_parser.set_defaults(func=cmd_scan)

    # encode
    encode_parser = subparsers.add_parser("encode", help="Process files from the queue")
    encode_parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Maximum number of files to process (default: all)",
    )
    encode_parser.set_defaults(func=cmd_encode)

    # verify
    verify_parser = subparsers.add_parser("verify", help="Verify encoded files")
    verify_parser.set_defaults(func=cmd_verify)

    # resume
    resume_parser = subparsers.add_parser("resume", help="Resume processing (same as encode)")
    resume_parser.add_argument(
        "--count",
        type=int,
        default=None,
        help="Maximum number of files to process (default: all)",
    )
    resume_parser.set_defaults(func=cmd_resume)

    # clean
    clean_parser = subparsers.add_parser("clean", help="Clean temporary files")
    clean_parser.add_argument(
        "--logs",
        action="store_true",
        help="Also remove logs directory",
    )
    clean_parser.set_defaults(func=cmd_clean)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()