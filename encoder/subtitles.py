"""Subtitle handling for mediaworker.

Functions for selecting, configuring, and processing subtitle tracks.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .config import Config


# Known subtitle modifier suffixes (without the dot) that can be stripped
# from the end of a subtitle stem to get the base name for comparison
KNOWN_SUFFIXES = {
    # English indicators
    'eng', 'english', 'en',
    # Other language codes (2-3 letters)
    'spa', 'fre', 'ger', 'hin', 'ita', 'jpn', 'kor', 'rus',
    'dan', 'dut', 'fin', 'nob', 'swe', 'slv', 'ukr', 'pol',
    'tur', 'tha', 'vie', 'ind', 'may', 'heb', 'cze', 'hun',
    'rum', 'gre',
    # SDH indicators
    'sdh', 'hardofhearing', 'hearingimpairment', 'hi',
    # Forced
    'forced',
}


def select_default_subtitle(subtitles: List[Path]) -> Path | None:
    """Choose a default subtitle track from the list.

    Implements logic similar to msr.bat:
    - Prefers English subtitles
    - Handles SDH (Subtitles for the Deaf and Hard-of-hearing)
    - Prefers non-forced subtitles as default unless only forced exists

    Args:
        subtitles: List of subtitle file paths.

    Returns:
        The selected subtitle path, or None if no subtitles.
    """
    if not subtitles:
        return None

    def subtitle_score(path: Path) -> tuple:
        name = path.name.lower()
        stem = path.stem.lower()

        # Check for language indicators
        lang_score = 0
        # English indicators - check in order of preference
        if "english" in name:
            lang_score = 3
        elif "eng" in name:
            lang_score = 2
        elif ".en" in name:
            lang_score = 2
        # Check for a language code in the stem (e.g., "Movie.eng.srt" -> "eng")
        # We look at the segments split by dots, from right to left.
        if get_subtitle_language(path) != "und":
            lang_score = 1  # Generic language code

        # Check for SDH (Subtitles for Deaf and Hard-of-hearing)
        sdh_penalty = 0
        if any(indicator in name for indicator in ["sdh", "hardofhearing", "hearingimpairment"]):
            sdh_penalty = 1
        # Handle .HI marker (common in some releases)
        if stem.endswith(".hi"):
            sdh_penalty = 1

        # Check for forced
        forced_penalty = 0
        if "forced" in name:
            forced_penalty = 1

        # Return tuple for sorting: (-lang_score, sdh_penalty, forced_penalty, name)
        # Negative lang_score because we want higher scores first
        return (-lang_score, sdh_penalty, forced_penalty, name)

    sorted_subtitles = sorted(subtitles, key=subtitle_score)
    return sorted_subtitles[0]


def needs_forced_flag(subtitle_path: Path) -> bool:
    """Determine if a subtitle should be marked as forced.

    Heuristic: if filename contains 'forced' (case-insensitive).

    Args:
        subtitle_path: Path to subtitle file.

    Returns:
        True if forced flag should be set.
    """
    name = subtitle_path.name.lower()
    return "forced" in name


def needs_sdh_flag(subtitle_path: Path) -> bool:
    """Determine if a subtitle is for the hearing impaired (SDH).

    Heuristic: checks for common SDH indicators in filename.

    Args:
        subtitle_path: Path to subtitle file.

    Returns:
        True if SDH flag should be set.
    """
    name = subtitle_path.name.lower()
    stem = subtitle_path.stem.lower()
    # Common SDH indicators
    sdh_indicators = ["sdh", "hardofhearing", "hearingimpairment"]
    if any(indicator in name for indicator in sdh_indicators):
        return True

    # Handle .HI marker (common in some releases)
    if stem.endswith(".hi"):
        return True

    return False


def _strip_known_suffixes(stem: str) -> str:
    """Remove trailing known-suffix tokens (``.eng``, ``.hi``, ...) from a stem.

    Strips repeatedly, case-insensitively, until no more match, so a name like
    ``"Movie.eng.hi"`` loses both tokens.
    """
    while True:
        removed = False
        stem_lower = stem.lower()
        for suffix in KNOWN_SUFFIXES:
            if stem_lower.endswith('.' + suffix):
                # Remove the dot and suffix
                stem = stem[:-(len(suffix)+1)]
                removed = True
                break
        if not removed:
            break
    return stem


def _is_main_subtitle(subtitle_path: Path, video_path: Path | None) -> bool:
    """True when ``subtitle_path`` is the same-named sub for ``video_path``.

    Release naming convention: a subtitle sitting next to the video with the
    same base name (``Movie.2026.mp4`` -> ``Movie.2026.srt``) is the primary
    English track (see msr.bat's ``MAIN_SUB``).
    """
    if video_path is None:
        return False

    video_stem = video_path.stem
    # Get the subtitle stem without the extension (.srt, .ass, etc.)
    subtitle_stem = _stem_no_ext(subtitle_path)
    # Remove known suffixes (like .eng, .hi, .forced, etc.) from the end.
    stem = _strip_known_suffixes(subtitle_stem)
    return stem == video_stem


def _stem_no_ext(subtitle_path: Path) -> str:
    """Filename stem with *all* trailing subtitle extensions stripped.

    ``Path.stem`` only drops one suffix, but release subtitles often use a
    ``.eng.srt`` / ``.por.ass`` form where the language code sits before the
    extension. We want the bare title portion (``"Brazilian (Forced)"``), so we
    peel every recognized subtitle suffix.

    Example: ``"Brazilian (Forced).por.srt`` -> ``"Brazilian (Forced)"``.
    """
    name = subtitle_path.name
    for ext in (".srt", ".ass", ".ssa", ".sub", ".idx"):
        if name.lower().endswith(ext):
            return name[: -len(ext)]
    return name


def build_subtitle_disposition_args(
    config: Config,
    subtitle_files: List[Path],
    video_path: Path | None = None,
) -> List[str]:
    """Build FFmpeg disposition arguments for subtitle streams.

    Args:
        config: Application configuration.
        subtitle_files: List of subtitle file paths found for the video.
        video_path: Source video path, used to identify the same-named main
            subtitle so it can be marked ``default`` per the release convention.

    Returns:
        List of FFmpeg arguments for disposition settings.
    """
    args: List[str] = []

    if not subtitle_files:
        return args

    # Determine which subtitle should be default
    # The same-named main subtitle is conventionally English and the default.
    main_sub_titles = [
        s for s in subtitle_files if _is_main_subtitle(s, video_path)
    ]
    if main_sub_titles:
        # Among same-named subtitles, pick the best one using select_default_subtitle
        default_sub = select_default_subtitle(main_sub_titles)
    else:
        default_sub = select_default_subtitle(subtitle_files)

    for i, sub_file in enumerate(subtitle_files):
        disposition_flags = []

        # Check if this should be the default subtitle
        if sub_file == default_sub:
            disposition_flags.append("default")

        # Check if forced
        if needs_forced_flag(sub_file):
            disposition_flags.append("forced")

        # Check if SDH (hearing impaired)
        if needs_sdh_flag(sub_file):
            disposition_flags.append("hearing_impaired")

        # Add disposition argument if any flags
        if disposition_flags:
            # ffmpeg combines multiple dispositions with '+', not a space.
            # A space ("default hearing_impaired") fails with return code 234
            # "Undefined constant ... in 'defaulthearing_impaired'" / "Error
            # setting output stream dispositions".
            args.extend(["-disposition:s:" + str(i), "+".join(disposition_flags)])

    return args


def build_subtitle_metadata_args(
    config: Config,
    subtitle_files: List[Path],
    video_path: Path | None = None,
) -> List[str]:
    """Build FFmpeg metadata arguments for subtitle streams (language, title).
    Args:
        config: Application configuration.
        subtitle_files: List of subtitle file paths found for the video.
        video_path: Source video path, used to identify the same-named main
            subtitle for the 'default' flag in title generation.
    Returns:
        List of FFmpeg arguments for subtitle metadata.
    """
    args: List[str] = []
    if not subtitle_files:
        return args

    # Determine default language fallback from config
    default_lang = config.encoder.default_subtitle_language

    for i, sub_file in enumerate(subtitle_files):
        language = get_subtitle_language(sub_file)

        # If it's the only subtitle and language is undetermined, use config fallback
        if len(subtitle_files) == 1 and language == "und":
            language = default_lang

        # A single external subtitle needs no title; its language metadata alone
        # identifies it. Titles are reserved for multi-sub files.
        if len(subtitle_files) > 1:
            label = get_subtitle_label(sub_file)
            if label is not None:
                args.extend([f"-metadata:s:s:{i}", f"title={label}"])

        # Only add language metadata if we have a value (not None)
        if language:
            args.extend([f"-metadata:s:s:{i}", f"language={language}"])
    return args


def _sanitize_label(label: str | None) -> str | None:
    """Sanitize a subtitle label by trimming whitespace and normalizing.

    Args:
        label: Raw label string from subtitle header or filename.

    Returns:
        Sanitized label or None if input was None or empty after sanitizing.
    """
    if label is None:
        return None
    label = label.strip()
    if not label:
        return None
    # Collapse multiple whitespace
    return " ".join(label.split())


def get_subtitle_label(subtitle_path: Path) -> str | None:
    """Extract a descriptive label from a subtitle filename, or None.

    Release subtitles often carry a human title before the language token
    (``"Brazilian (Forced).por.srt"`` -> ``"Brazilian (Forced)"``). When the
    name is just a bare code/indicator (``"eng.srt"``, ``"spa.hi.srt"``) there
    is no descriptive label, and we return None so no title metadata is written.

    Args:
        subtitle_path: Path to subtitle file.

    Returns:
        The descriptive label, or None for bare-code filenames.
    """
    stem = _strip_known_suffixes(_stem_no_ext(subtitle_path))

    # A bare code or indicator (e.g. "eng", "spa") is not a descriptive label.
    if stem.lower() in KNOWN_SUFFIXES:
        return None

    return _sanitize_label(stem)


def get_subtitle_language(subtitle_path: Path) -> str:
    """Extract a 3-letter ISO-639-3 language code from subtitle filename.

    Heuristic: splits the stem by dots and looks for the first 2- or 3-letter
    alpha segment from the right that isn't a known modifier.
    Returns "und" (undetermined) if no language can be detected.

    Args:
        subtitle_path: Path to subtitle file.

    Returns:
        A language code string.
    """
    name = subtitle_path.name.lower()
    stem = subtitle_path.stem.lower()

    # Look for language codes in the stem segments (right to left)
    # e.g., "Movie.eng.hi.srt" -> parts=["movie", "eng", "hi"] -> returns "eng"
    for part in reversed(stem.split('.')):
        if (len(part) == 2 or len(part) == 3) and part.isalpha() and part not in {'sdh', 'hi', 'forced'}:
            # To avoid misinterpreting "III" or "The" as languages,
            # we only accept it if it's in our known language list.
            if part in KNOWN_SUFFIXES:
                return part

    # Fallback for English indicators anywhere in the name
    if any(indicator in name for indicator in ["eng", "english", ".en"]):
        return "eng"

    # Fallback to undetermined
    return "und"


# Test data for when the module is run directly
if __name__ == "__main__":
    # Test the label/SDH/language detection
    subs = [
        Path("English.srt"),                     # bare language name -> no label
        Path("en.srt"),                          # 2-letter code -> no label
        Path("eng.hi.srt"),                      # .HI english -> disp, lang eng, no label
        Path("spa.hi.srt"),                      # .HI non-english -> disp, lang und, no label
        Path("Slovenia.slv.srt"),                # label "Slovenia"
        Path("Ukraine (Forced).ukr.srt"),        # label "Ukraine (Forced)"
        Path("Ukraine.ukr.srt"),                 # label "Ukraine"
        Path("dan.srt"),                         # bare code -> no label
        Path("dut.srt"),
        Path("fin.srt"),
        Path("ger.srt"),
        Path("hin.srt"),
        Path("ita.srt"),
        Path("nob.srt"),
        Path("swe.srt"),
    ]
    print("Default subtitle:", select_default_subtitle(subs).name if subs else None)
    for s in subs:
        print(
            f"{s.name:>25}: "
            f"forced={int(needs_forced_flag(s))} "
            f"sdh={int(needs_sdh_flag(s))} "
            f"language={get_subtitle_language(s)} "
            f"label={get_subtitle_label(s)}"
        )
