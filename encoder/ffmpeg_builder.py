"""FFmpeg command builder for mediaworker.

Constructs FFmpeg command lines based on configuration and file specifics.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import List

from .config import Config, EncoderSettings
from .utils import find_subtitle_files
from .subtitles import build_subtitle_disposition_args, build_subtitle_metadata_args


def probe_audio_channels(file_path: Path) -> int:
    """Probe audio stream to determine channel count using ffprobe.

    Args:
        file_path: Path to the media file.

    Returns:
        Number of audio channels (defaults to 2 if probing fails).
    """
    try:
        cmd = [
            "ffprobe",
            "-v", "error",
            "-select_streams", "a:0",
            "-show_entries", "stream=channels",
            "-of", "json",
            str(file_path)
        ]
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        if result.returncode == 0:
            data = json.loads(result.stdout)
            streams = data.get("streams", [])
            if streams:
                return streams[0].get("channels", 2)
    except Exception:
        pass  # Fall back to default
    return 2  # Default to stereo


def build_ffmpeg_cmd(
    config: Config,
    input_path: Path,
    output_path: Path,
) -> List[str]:
    """Build FFmpeg command for encoding a single video file.

    Args:
        config: Application configuration.
        input_path: Absolute path to the source video file.
        output_path: Absolute path where the encoded file should be written.

    Returns:
        List of strings suitable for passing to subprocess.run().
    """
    encoder = config.encoder
    ffmpeg_cmd = [config.ffmpeg.path] + config.ffmpeg.extra_args

    # Input
    ffmpeg_cmd.extend(["-i", str(input_path)])

    # Video settings
    if encoder.copy_video:
        ffmpeg_cmd.extend(["-c:v", "copy"])
    else:
        ffmpeg_cmd.extend(["-c:v", encoder.video_codec, "-preset", encoder.preset, "-crf", str(encoder.crf)])
        # Scaling
        if encoder.max_width or encoder.max_height:
            scale_filter = []
            if encoder.max_width:
                scale_filter.append(f"w='min({encoder.max_width},iw)'")
            if encoder.max_height:
                scale_filter.append(f"h='min({encoder.max_height},ih)'")
            # Ensure even dimensions (required by many codecs)
            scale_filter.append("w='(iw/mod(iw,2))'")
            scale_filter.append("h='(ih/mod(ih,2))'")
            vf = ",".join(scale_filter)
            ffmpeg_cmd.extend(["-vf", f"scale={vf}"] if encoder.scale_down_only else [f"scale={vf}"])

    # Audio settings
    if encoder.copy_audio:
        ffmpeg_cmd.extend(["-c:a", "copy"])
    else:
        ffmpeg_cmd.extend(["-c:a", encoder.audio_codec, "-b:a", encoder.audio_bitrate])

        # Opus-specific settings
        if encoder.audio_codec == "libopus":
            ffmpeg_cmd.extend(["-vbr", "on"])  # Use VBR for opus

            # For opus, adjust channel layout based on source
            channels = probe_audio_channels(input_path)
            if channels <= 2:
                ffmpeg_cmd.extend(["-channel_layout", "stereo"])
                # For stereo opus, 96k is good
                if encoder.audio_bitrate == "96k":  # Only adjust if using default
                    pass  # Keep 96k for stereo
            elif channels <= 6:
                ffmpeg_cmd.extend(["-channel_layout", "surround"])
                # For surround sound opus, 192k is better
                if encoder.audio_bitrate == "96k":  # Only adjust if using default
                    ffmpeg_cmd[-2] = "-b:a"
                    ffmpeg_cmd[-1] = "192k"  # Replace the bitrate

    # Subtitle handling: attach all matching subtitle files as streams
    subtitle_files = find_subtitle_files(input_path, config.subtitle_extensions)
    for i, sub_file in enumerate(subtitle_files):
        ffmpeg_cmd.extend(["-i", str(sub_file)])

    # Map directives
    # Map video from first input (0:v)
    ffmpeg_cmd.extend(["-map", "0:v"])
    # Map audio from first input (0:a)
    ffmpeg_cmd.extend(["-map", "0:a?"])  # optional audio
    # Map subtitles: each subtitle file is an additional input, starting at index 1
    for i in range(len(subtitle_files)):
        ffmpeg_cmd.extend(["-map", f"{i+1}:s?"])  # optional subtitle stream

    # Metadata: preserve metadata (optional)
    ffmpeg_cmd.extend(["-map_metadata", "0"])

    # Add subtitle metadata (language, title)
    ffmpeg_cmd.extend(build_subtitle_metadata_args(config, subtitle_files))

    # Add subtitle disposition flags (default, forced, hearing_impaired)
    ffmpeg_cmd.extend(build_subtitle_disposition_args(config, subtitle_files))

    # Optional: Disable subtitle encoding if we're copying
    # Not needed as mapping is handled above

    # Output
    ffmpeg_cmd.append(str(output_path))

    return ffmpeg_cmd


def run_ffmpeg(cmd: List[str]) -> subprocess.CompletedProcess:
    """Run FFmpeg command and return the result.

    Args:
        cmd: Command list as built by build_ffmpeg_cmd.

    Returns:
        CompletedProcess instance.

    Raises:
        subprocess.CalledProcessError if FFmpeg returns non-zero exit code.
    """
    # For logging, we might want to keep the command as string
    # but we'll let the caller handle logging.
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


if __name__ == "__main__":
    # Simple self-test
    import tempfile
    from .config import Config, DirectorySettings, EncoderSettings, FFmpegSettings

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        # Create dummy config
        cfg = Config(
            directories=DirectorySettings(
                input=tmp_path / "input",
                output=tmp_path / "output",
                processing=tmp_path / "processing",
                logs=tmp_path / "logs",
            ),
            encoder=EncoderSettings(),
            ffmpeg=FFmpegSettings(),
        )
        # Create dummy video file
        video = cfg.directories.input / "test.mkv"
        video.touch()
        # Create dummy subtitle
        sub = cfg.directories.input / "test.srt"
        sub.touch()
        output = cfg.directories.output / "test.mkv"
        cmd = build_ffmpeg_cmd(cfg, video, output)
        print("FFmpeg command:", " ".join(cmd))