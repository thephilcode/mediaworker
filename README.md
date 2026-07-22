# mediaworker

Automated media encoding worker for Linux VPS.

## Overview

mediaworker is a Python application that recursively scans an input directory for video files, encodes them using FFmpeg with configurable settings, and places the encoded files in an output directory while preserving the original directory structure.

It is designed to run as a worker on a headless Linux server, with a Windows (or other) client uploading files to the input directory and downloading from the output directory.

This project was born of a workflow I use to re-encode and convert videos in my library to HEVC+OPUS in MKV files to compress files as much as possible with no discernible loss in video and audio quality (my storage space thanked me!). This was achieved with a number of scripts the logic of which was the foundation for this project which merges the entire workflow into one tool.

## Features

- Recursive scanning of input directory
- Preserves directory hierarchy in output
- Automatic subtitle detection and copying
- Configurable encoding presets (CRF, preset, codecs, scaling)
- Filesystem-based job queue (no external dependencies)
- Resumable processing (survives interruptions)
- Handles filenames with spaces and Unicode
- Detailed logging
- No external Python dependencies (uses only standard library)

## Installation

```bash
# Clone the repository
git clone <repository-url>
cd mediaworker

# Install using uv (recommended)
uv pip install -e .

# Or using pip
pip install -e .
```

## Configuration

Copy `config.toml.example` to `config.toml` and adjust the paths and encoding settings as needed.

## Usage

### Scan for media files

```bash
mediaworker scan
```

Lists all video files found in the input directory that are pending processing.

### Start encoding

```bash
mediaworker encode
```

Processes all pending files sequentially. Can be interrupted and resumed.

### Process a limited number of files

```bash
mediaworker encode --count 10
```

Processes only the next 10 items from the queue.

### Resume processing

```bash
mediaworker resume
```

Equivalent to `encode`; processes remaining items in the queue.

### Verify encoded files

```bash
mediaworker verify
```

Checks that output files exist for all processed items (basic verification).

### Clean temporary files

```bash
mediaworker cleanup
```

Removes the processing directory (where intermediate files are stored).

## Configuration File (config.toml)

See the provided `config.toml.example` for documented example settings and comments.

## Development

This project uses only the Python standard library, so no additional packages are required for development.

### Running tests

*(To be implemented)*

```bash
python -m pytest
```

### Code formatting

*(To be implemented)*

```bash
black encoder/
```

## License

MIT