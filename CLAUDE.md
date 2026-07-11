# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Common Commands

### Development Setup
```bash
# Install dependencies (if any external ones are added)
uv pip install -e .

# After installation, the `mediaworker` command is available:
mediaworker --help

# Alternatively, run the module directly:
python -m encoder.mediaworker --help

# Available subcommands:
#   scan    - Discover media files in input directory
#   encode  - Process files from the queue
#   verify  - Check encoded files against source
#   resume  - Continue processing after interruption
#   clean   - Remove temporary files
```

### Testing
```bash
# Run all tests (when test suite is added)
python -m pytest

# Run specific test file
python -m pytest tests/test_encoder.py

# Run single test function
python -m pytest tests/test_encoder.py::test_scan_videos
```

### Code Quality
```bash
# Format code (when formatter is configured)
black encoder/

# Lint code (when linter is configured)
flake8 encoder/
```

## Project Architecture

### High-Level Structure
The mediaworker application follows a modular design with separated concerns:

1. **mediaworker.py** - Main CLI entry point using argparse
2. **scanner.py** - Recursively scans input directory for video files, builds queue
3. **queue.py** - Filesystem-based queue management (no external dependencies)
4. **worker.py** - Core encoding logic, processes files sequentially
5. **ffmpeg_builder.py** - Constructs FFmpeg commands with preset parameters
6. **subtitles.py** - Handles subtitle detection, disposition, and metadata
7. **config.py** - TOML configuration loading and validation
8. **utils.py** - Helper functions for path handling, logging, error recovery

### Key Design Principles
- **Recursive scanning**: Processes all directories uniformly (no movie/series distinction)
- **Preserves hierarchy**: Input directory structure mirrored in output
- **Resumable**: Queue state tracked via filesystem markers
- **Dependency-free**: Uses only Python standard library (pathlib, subprocess, logging, dataclasses, argparse)
- **Fault tolerant**: Continues after failures, preserves original files
- **Unicode safe**: Handles filenames with spaces and international characters

### Data Flow
1. `mediaworker scan` → scanner.py discovers files → queue.py creates queue
2. `mediaworker encode` → worker.py processes queue → ffmpeg_builder.py creates commands
3. Encoding runs via subprocess → results placed in output directory preserving paths
4. `mediaworker verify` → compares source/encoded files (to be implemented)
5. `mediaworker resume` → continues from last processed file
6. `mediaworker clean` → cleans temporary processing files

### Configuration
- Settings stored in `config.toml` (input/output directories, encoder presets, paths)
- Loaded via config.py with validation and defaults
- Designed for easy modification without code changes

### Reliability Features
- Intermediate files written to processing directory before final move
- Logs written to logs directory with rotation (when implemented)
- Atomic file operations to prevent corruption
- Graceful handling of interruptions (SIGTERM, etc.)

### Additional Files
- **pyproject.toml** - Project configuration for uv/pip builds and console script entry point
- **run_queue.sh** - Convenience shell script to run the encode command (uses uv if available)
- **README.md** - Project overview and usage instructions