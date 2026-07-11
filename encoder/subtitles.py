"""Subtitle handling for mediaworker.

Functions for selecting, configuring, and processing subtitle tracks.
"""

from __future__ import annotations

from pathlib import Path
from typing import List, Optional

from .config import Config


def select_default_subtitle(subtitles: List[Path]) -> Path | None:
    """Choose a default subtitle track from the list.

    Implements logic similar to msr.bat:
    - Prefers English subtitles
    - Handles SDH (Subtitles for the Deaf and Hard-of-hearing)
    - Prefers non-forced subtitles as default unless only forced exists

    Args:
        subtitles: List of subtitle file paths.

    Returns:
        Path to be used as default, or None if list empty.
    """
    if not subtitles:
        return None

    # Sort with preferences:
    # 1. English language (eng) [maybe English in name]
    # 2. Non-SDH over SDH (unless SDH is the only English)
    # 3. Non-forced over forced
    # 4. Alphabetical as tiebreaker

    def subtitle_score(path: Path) -> tuple:
        name = path.name.lower()
        stem = path.stem.lower()

        # Check for language indicators
        lang_score = 0
        # English indicators
        if any(indicator in name for indicator in ["eng", "english", ".en"]):
            lang_score = 2
        elif name.endswith(".srt") or name.endswith(".ass") or name.endswith(".ssa"):
            # Check if it's a 3-letter language code
            if len(stem) >= 3 and stem[-3:].isalpha():
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
        True if subtitle should be marked as hearing impaired.
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


def get_subtitle_language(subtitle_path: Path) -> str:
    """Extract language code from subtitle filename.

    Args:
        subtitle_path: Path to subtitle file.

    Returns:
        Language code (e.g., "eng", "spa", "und" for undefined).
    """
    name = subtitle_path.name.lower()
    stem = subtitle_path.stem.lower()

    # Check for explicit language indicators
    if "eng" in name or "english" in name:
        return "eng"
    elif "spa" in name or "spanish" in name:
        return "spa"
    elif "fre" in name or "french" in name or "fra" in name:
        return "fre"
    elif "ger" in name or "german" in name or "deu" in name:
        return "ger"
    elif "ita" in name or "italian" in name:
        return "ita"
    elif "por" in name or "portuguese" in name:
        return "por"
    elif "rus" in name or "russian" in name:
        return "rus"
    elif "jap" in name or "japanese" in name or "jpn" in name:
        return "jap"
    elif "kor" in name or "korean" in name:
        return "kor"
    elif "chi" in name or "chinese" in name or "zho" in name:
        return "chi"
    elif "ara" in name or "arabic" in name:
        return "ara"
    elif "hin" in name or "hindi" in name:
        return "hin"

    # Check for 3-letter language code at the end (before .srt/.ass/etc)
    # Common pattern: filename.eng.srt or filenameeng.srt
    if len(stem) >= 3:
        # Check if last 3 chars are alphabetic (language code)
        if stem[-3:].isalpha():
            potential_lang = stem[-3:]
            # Validate it looks like a language code
            if potential_lang in ["eng", "spa", "fre", "ger", "ita", "por", "rus", "jap", "kor", "chi", "ara", "hin"]:
                return potential_lang

    # Check for 2-letter language code
    if len(stem) >= 2:
        potential_lang = stem[-2:]
        if potential_lang in ["en", "es", "fr", "de", "it", "pt", "ru", "ja", "ko", "zh", "ar", "hi"]:
            # Convert to 3-letter code where possible
            lang_map = {
                "en": "eng",
                "es": "spa",
                "fr": "fre",
                "de": "ger",
                "it": "ita",
                "pt": "por",
                "ru": "rus",
                "ja": "jap",
                "ko": "kor",
                "zh": "chi",
                "ar": "ara",
                "hi": "hin",
            }
            return lang_map.get(potential_lang, potential_lang)

    # Default to undefined
    return "und"


def get_subtitle_title(subtitle_path: Path) -> str:
    """Generate a title for the subtitle track based on filename.

    Args:
        subtitle_path: Path to subtitle file.

    Returns:
        Title string for the subtitle track.
    """
    name = subtitle_path.name
    stem = subtitle_path.stem

    # Remove extension to work with stem
    # Handle special case where filename ends with language code like .eng
    # or .en before the actual extension

    # Start with the stem
    title = stem

    # Handle .HI marker (hearing impaired)
    if stem.lower().endswith(".hi"):
        title = stem[:-3]  # Remove .hi
        # Check if there's a language code before .hi
        if len(title) >= 3 and title[-3:].isalpha():
            lang_code = title[-3:]
            title = title[:-3]  # Remove language code
            # Map to full language name
            lang_names = {
                "eng": "English",
                "spa": "Spanish",
                "fre": "French",
                "ger": "German",
                "ita": "Italian",
                "por": "Portuguese",
                "rus": "Russian",
                "jap": "Japanese",
                "kor": "Korean",
                "chi": "Chinese",
                "ara": "Arabic",
                "hin": "Hindi",
            }
            lang_name = lang_names.get(lang_code, lang_code.upper())
            title = f"{lang_name} (SDH)"
        else:
            title = f"{title} (SDH)"

    # Check for explicit language in name
    name_lower = name.lower()
    if "english" in name_lower:
        title = "English"
    elif "spanish" in name_lower:
        title = "Spanish"
    elif "french" in name_lower:
        title = "French"
    elif "german" in name_lower:
        title = "German"
    elif "italian" in name_lower:
        title = "Italian"
    elif "portuguese" in name_lower:
        title = "Portuguese"
    elif "russian" in name_lower:
        title = "Russian"
    elif "japanese" in name_lower:
        title = "Japanese"
    elif "korean" in name_lower:
        title = "Korean"
    elif "chinese" in name_lower:
        title = "Chinese"
    elif "arabic" in name_lower:
        title = "Arabic"
    elif "hindi" in name_lower:
        title = "Hindi"

    # Check if SDH is indicated and add to title if not already present
    if needs_sdh_flag(subtitle_path) and "(sdh)" not in title.lower():
        if title and not title.endswith(" (SDH)"):
            title = f"{title} (SDH)"
        elif not title:
            title = "SDH"

    # Clean up extra spaces
    title = " ".join(title.split())

    # If we still don't have a good title, use the filename without extension
    if not title:
        title = stem

    return title


def build_subtitle_disposition_args(
    config: Config,
    subtitle_files: List[Path],
) -> List[str]:
    """Build FFmpeg disposition arguments for subtitle streams.

    Args:
        config: Application configuration.
        subtitle_files: List of subtitle file paths found for the video.

    Returns:
        List of FFmpeg arguments for disposition settings.
    """
    args: List[str] = []

    if not subtitle_files:
        return args

    # Determine which subtitle should be default
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
            args.extend(["-disposition:s:" + str(i), " ".join(disposition_flags)])

    return args


def build_subtitle_metadata_args(
    config: Config,
    subtitle_files: List[Path],
) -> List[str]:
    """Build FFmpeg metadata arguments for subtitle streams.

    Args:
        config: Application configuration.
        subtitle_files: List of subtitle file paths found for the video.

    Returns:
        List of FFmpeg arguments for metadata settings.
    """
    args: List[str] = []

    for i, sub_file in enumerate(subtitle_files):
        # Language metadata
        lang = get_subtitle_language(sub_file)
        args.extend([f"-metadata:s:s:{i}", f"language={lang}"])

        # Title metadata
        title = get_subtitle_title(sub_file)
        if title:
            args.extend([f"-metadata:s:s:{i}", f"title={title}"])

    return args


if __name__ == "__main__":
    # Simple test
    from pathlib import Path
    subs = [Path("Eng.srt"), Path("Forced.srt"), Path("sgn.ass"), Path("eng.hi.srt"), Path("spa.srt")]
    print("Default:", select_default_subtitle(subs))
    for s in subs:
        print(f"{s.name}:")
        print(f"  forced={needs_forced_flag(s)}")
        print(f"  sdh={needs_sdh_flag(s)}")
        print(f"  language={get_subtitle_language(s)}")
        print(f"  title='{get_subtitle_title(s)}'")