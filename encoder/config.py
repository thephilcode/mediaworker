"""Configuration loading for mediaworker.

This module reads configuration from a TOML file and provides
typed settings for the application. It uses only the standard
library (tomllib) for parsing, avoiding external dependencies.
"""
from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal


@dataclass
class EncoderSettings:
    """FFmpeg encoder parameters."""
    preset: str = "medium"
    crf: int = 23
    video_codec: str = "libx264"
    audio_codec: str = "aac"
    audio_bitrate: str = "128k"
    subtitle_codec: str = "copy"
    max_width: int | None = None
    max_height: int | None = None
    scale_down_only: bool = True
    copy_video: bool = False
    copy_audio: bool = False
    # Use VBR for audio (default: on)
    vbr: bool = True
    # Optional comment to add to the output container
    comment: str = ""
    # Max attempts per file before giving up and moving it to failed.txt
    max_attempts: int = 3
    # If set, force this output file extension (including the dot) for all encodes.
    # If None, preserve the input file's extension.
    output_extension: str | None = None
    # If True, replace known codec identifiers in the filename stem with the
    # current video/audio codec identifiers (e.g., replace "x264" with "x265"
    # when encoding to libx265, or "aac" with "opus" when encoding to libopus)
    # to visually distinguish re-encoded files.
    rename_by_codec: bool = False
    # Pixel format passed as -pix_fmt on re-encode (e.g. "yuv420p10le" for
    # 10-bit x265). Empty -> let the codec pick its default (8-bit yuv420p
    # for x265/x264). Ignored when copy_video is True.
    pix_fmt: str = ""
    # Extra params appended as -x265-params when video_codec == "libx265"
    # (colon-separated, no quoting needed; the value is passed as one arg to
    # subprocess, not through a shell). Ignored for other codecs and when
    # copy_video is True. Empty -> no -x265-params flag.
    x265_params: str = ""


@dataclass
class DirectorySettings:
    """Directory paths used by the worker."""
    input: Path
    output: Path
    processing: Path
    logs: Path


@dataclass
class FFmpegSettings:
    """FFmpeg executable location."""
    path: str = "ffmpeg"
    # Optional: extra arguments to prepend to every FFmpeg call
    extra_args: list[str] = field(default_factory=list)


@dataclass
class Config:
    """Application configuration."""
    directories: DirectorySettings
    encoder: EncoderSettings = field(default_factory=EncoderSettings)
    ffmpeg: FFmpegSettings = field(default_factory=FFmpegSettings)
    # Supported video file extensions (lowercase, with dot)
    video_extensions: set[str] = field(
        default_factory=lambda: {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm"}
    )
    # Supported subtitle extensions
    subtitle_extensions: set[str] = field(
        default_factory=lambda: {".srt", ".ass", ".ssa", ".sub", ".idx"}
    )


def load_config(config_path: Path | str = "config.toml") -> Config:
    """Load configuration from a TOML file.

    Args:
        config_path: Path to the TOML configuration file.

    Returns:
        Config object with settings loaded from file, falling back to defaults.

    Raises:
        FileNotFoundError: If the config file does not exist.
        tomllib.TOMLDecodeError: If the file is not valid TOML.
    """
    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    # Helper to get nested dicts safely
    def get_section(name: str, default: dict | None = None) -> dict:
        return data.get(name, default or {})

    # Directories (required)
    dirs_data = get_section("directories")
    directories = DirectorySettings(
        input=Path(dirs_data.get("input", ".")).resolve(),
        output=Path(dirs_data.get("output", "./output")).resolve(),
        processing=Path(dirs_data.get("processing", "./processing")).resolve(),
        logs=Path(dirs_data.get("logs", "./logs")).resolve(),
    )

    # Encoder settings (optional)
    enc_data = get_section("encoder")
    encoder = EncoderSettings(
        preset=enc_data.get("preset", "medium"),
        crf=enc_data.get("crf", 23),
        video_codec=enc_data.get("video_codec", "libx264"),
        audio_codec=enc_data.get("audio_codec", "aac"),
        audio_bitrate=enc_data.get("audio_bitrate", "128k"),
        subtitle_codec=enc_data.get("subtitle_codec", "copy"),
        max_width=enc_data.get("max_width"),
        max_height=enc_data.get("max_height"),
        scale_down_only=enc_data.get("scale_down_only", True),
        copy_video=enc_data.get("copy_video", False),
        copy_audio=enc_data.get("copy_audio", False),
        vbr=enc_data.get("vbr", True),
        comment=enc_data.get("comment", ""),
        max_attempts=enc_data.get("max_attempts", 3),
        output_extension=enc_data.get("output_extension"),
        rename_by_codec=enc_data.get("rename_by_codec", False),
        pix_fmt=enc_data.get("pix_fmt", ""),
        x265_params=enc_data.get("x265_params", ""),
    )

    # FFmpeg settings (optional)
    ffmpeg_data = get_section("ffmpeg")
    ffmpeg = FFmpegSettings(
        path=ffmpeg_data.get("path", "ffmpeg"),
        extra_args=ffmpeg_data.get("extra_args", []),
    )

    # Extensions (optional)
    vid_ext = get_section("video_extensions")
    video_extensions = {ext.lower() for ext in vid_ext} if vid_ext else None
    sub_ext = get_section("subtitle_extensions")
    subtitle_extensions = {ext.lower() for ext in sub_ext} if sub_ext else None

    return Config(
        directories=directories,
        encoder=encoder,
        ffmpeg=ffmpeg,
        video_extensions=video_extensions or {".mkv", ".mp4", ".avi", ".mov", ".wmv", ".flv", ".webm"},
        subtitle_extensions=subtitle_extensions or {".srt", ".ass", ".ssa", ".sub", ".idx"},
    )