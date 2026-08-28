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


def _scale_vf(max_w: int | None, max_h: int | None, scale_down_only: bool) -> str:
    """Build a `-vf scale=` filter preserving aspect ratio with even dims.

    - scale_down_only: never upscale (each bound clamped to source size via min).
    - One bound None: drive that axis only; the other picks `-2` (auto, even).
    """
    if scale_down_only:
        if max_w and max_h:
            opts = [
                f"w='min({max_w}\\,iw)'",
                f"h='min({max_h}\\,ih)'",
                "force_original_aspect_ratio=decrease",
            ]
        elif max_w:
            opts = [f"w='min({max_w}\\,iw)'", "h=-2"]
        else:
            opts = [f"h='min({max_h}\\,ih)'", "w=-2"]
    else:
        # Scale to fill the box (may upscale), aspect preserved, even dims.
        if max_w and max_h:
            opts = [f"w={max_w}", f"h={max_h}", "force_original_aspect_ratio=decrease"]
        elif max_w:
            opts = [f"w={max_w}", "h=-2"]
        else:
            opts = [f"h={max_h}", "w=-2"]
    opts.append("force_divisible_by=2")
    return "scale=" + ":".join(opts)


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

    # Inputs: main video first, then every matching subtitle file.
    # ALL inputs must precede any output options (-c:v, -vf, -map, ...).
    # FFmpeg assigns options between two files to the NEXT file, so output
    # opts placed before later -i inputs get mis-attributed to that input
    # and rejected (return code 234, "Option vf cannot be applied to input url").
    ffmpeg_cmd.extend(["-i", str(input_path)])
    subtitle_files = find_subtitle_files(input_path, config.subtitle_extensions)
    for sub_file in subtitle_files:
        ffmpeg_cmd.extend(["-i", str(sub_file)])

    # Video settings
    if encoder.copy_video:
        ffmpeg_cmd.extend(["-c:v", "copy"])
    else:
        ffmpeg_cmd.extend(["-c:v", encoder.video_codec, "-preset", encoder.preset, "-crf", str(encoder.crf)])
        # Pixel format (e.g. "yuv420p10le" for 10-bit). Empty -> codec default.
        # Applied to any re-encoded video, not just x265.
        if encoder.pix_fmt:
            ffmpeg_cmd.extend(["-pix_fmt", encoder.pix_fmt])
        # x265 tuning params. Only emitted for libx265; other codecs ignore
        # this field. Passed as a single arg (no shell quoting): the colons
        # separate params and need no escaping under subprocess list form.
        if encoder.x265_params and encoder.video_codec == "libx265":
            ffmpeg_cmd.extend(["-x265-params", encoder.x265_params])
        # Scaling (only when re-encoding video).
        # Preserves aspect ratio and forces even dimensions (codec requirement).
        # Commas inside expressions are backslash-escaped so the filtergraph
        # parser doesn't treat them as filter separators.
        if encoder.max_width or encoder.max_height:
            ffmpeg_cmd.extend([
                "-vf",
                _scale_vf(encoder.max_width, encoder.max_height, encoder.scale_down_only),
            ])

    # Audio settings
    if encoder.copy_audio:
        ffmpeg_cmd.extend(["-c:a", "copy"])
    else:
        # Determine audio bitrate for opus
        audio_bitrate = encoder.audio_bitrate
        if encoder.audio_codec == "libopus" and encoder.audio_bitrate == "96k":
            channels = probe_audio_channels(input_path)
            if 2 < channels <= 6:
                audio_bitrate = "192k"

        ffmpeg_cmd.extend(["-c:a", encoder.audio_codec, "-b:a", audio_bitrate])

        # Set mapping family for libopus to handle channel layouts like 5.1(side)
        if encoder.audio_codec == "libopus":
            ffmpeg_cmd.extend(["-mapping_family", "1"])

        # VBR flag (if enabled) - applies to any codec except libopus
        if encoder.vbr and encoder.audio_codec != "libopus":
            ffmpeg_cmd.extend(["-vbr", "on"])

        # No -channel_layout: libopus derives the output layout from the input
        # stream's channel count automatically (5.1 in -> 5.1 out), matching
        # the reference msr.bat. Passing a symbolic name (e.g. "surround") fails:
        # "surround" is not a valid ffmpeg channel layout and libopus's encoder
        # options don't expose channel_layout at all (rc 234, msg8371 in this
        # build). See `ffmpeg -layouts`: valid names are mono/stereo/5.1/etc.

    # Subtitle settings
    subtitle_codec = getattr(encoder, 'subtitle_codec', 'copy')
    ffmpeg_cmd.extend(["-c:s", subtitle_codec])

    # Map directives
    # Map video from first input (0:v)
    ffmpeg_cmd.extend(["-map", "0:v"])
    # Map audio from first input (0:a)
    ffmpeg_cmd.extend(["-map", "0:a?"])  # optional audio
    # Map subtitles from firt input (0:s)
    ffmpeg_cmd.extend(["-map", "0:s?"])  # optional subtitles
    # Map subtitles: each subtitle file is an additional input, starting at index 1
    for i in range(len(subtitle_files)):
        ffmpeg_cmd.extend(["-map", f"{i+1}:s?"])  # optional subtitle stream

    # Metadata: preserve metadata (optional)
    ffmpeg_cmd.extend(["-map_metadata", "0"])

    # Add subtitle metadata (language, title)
    ffmpeg_cmd.extend(build_subtitle_metadata_args(config, subtitle_files, input_path))

    # Add subtitle disposition flags (default, forced, hearing_impaired)
    ffmpeg_cmd.extend(build_subtitle_disposition_args(config, subtitle_files, input_path))

    # Add global and video stream comment if configured
    if encoder.comment:
        ffmpeg_cmd.extend(["-metadata", f"comment={encoder.comment}"])
        ffmpeg_cmd.extend(["-metadata:s:v:0", f"comment={encoder.comment}"])
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