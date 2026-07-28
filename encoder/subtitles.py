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


def _stem_no_ext(subtitle_path: Path) -> str:
    """Filename stem with *all* trailing subtitle extensions stripped.

    ``Path.stem`` only drops one suffix, but release subtitles often use a
    ``.eng.srt`` / ``.por.ass`` form where the language code sits before the
    extension. We want the bare title portion (``"Brazilian (Forced)"``), so we
    peel every recognized subtitle suffix.

    Example: ``"Brazilian (Forced).por.srt"`` -> ``"Brazilian (Forced)"``.
    """
    name = subtitle_path.name
    for ext in (".srt", ".ass", ".ssa", ".sub", ".idx"):
        if name.lower().endswith(ext):
            return name[: -len(ext)]
    return name


_LANG_OVERRIDES = {
    "english": "eng", "spanish": "spa", "french": "fre", "german": "ger",
    "italian": "ita", "portuguese": "por", "russian": "rus", "japanese": "jpn",
    "korean": "kor", "chinese": "chi", "arabic": "ara", "hindi": "hin",
}

# ponytail: one full-name table shared by language->name lookups, not two
# parallel dicts drifting apart. Maps the 3-letter code to the display name.
_LANG_NAMES = {
    "eng": "English", "spa": "Spanish", "fre": "French", "ger": "German",
    "ita": "Italian", "por": "Portuguese", "rus": "Russian", "jpn": "Japanese",
    "kor": "Korean", "chi": "Chinese", "ara": "Arabic", "hin": "Hindi",
    "dan": "Danish", "dut": "Dutch", "fin": "Finnish", "nob": "Norwegian",
    "swe": "Swedish", "slv": "Slovenian", "ukr": "Ukrainian", "pol": "Polish",
    "tur": "Turkish", "tha": "Thai", "vie": "Vietnamese", "ind": "Indonesian",
    "may": "Malay", "heb": "Hebrew", "cze": "Czech", "hun": "Hungarian",
    "rum": "Romanian", "gre": "Greek",
}


def get_subtitle_language(subtitle_path: Path) -> str:
    """Extract a 3-letter ISO-639-3 language code from subtitle filename.

    Mirrors msr.bat: the language is the **last 3 characters of the stem** and
    is *trusted* (not validated against a hard-coded Allow-list), so it catches
    codes the old substring heuristic missed (``slv``/``dan``/``nob``/``swe``
    were wrongly falling back to ``und`` and being dropped by ffmpeg).

    Overrides, in priority order (matching the reference):
      * spoken-language word in the name ("English", "Spanish", ...) -> code;
      * ``.HI`` marker -> ``und`` (unless ``eng`` precedes it, then ``eng``);
      * the trailing 3-char code itself, unless it's the media extension
        ("srt"/"ass"/...) -> ``und``;
      * a known 2-letter code -> its 3-letter form;
      * otherwise ``und``.

    Args:
        subtitle_path: Path to subtitle file.

    Returns:
        Language code (e.g. "eng", "por", "slv", "und" for undefined).
    """
    name = subtitle_path.name
    name_lower = name.lower()
    stem = subtitle_path.stem.lower()

    # Spoken-language override (highest priority): "English", "Spanish", ...
    for word, code in _LANG_OVERRIDES.items():
        if word in name_lower:
            return code

    # .HI marker (hearing impaired): lang is the 3 chars preceding ".hi" if
    # they form a code, else "eng" if the name mentions eng, else "und".
    if stem.endswith(".hi"):
        before = stem[:-3]
        if len(before) >= 3 and before[-3:].isalpha() \
                and before[-3:] not in ("srt", "ass", "ssa", "sub", "idx"):
            if before[-4:-3] == "." or before[-3:] == before:
                return before[-3:]
        return "eng" if "eng" in name_lower else "und"

    # Trailing 3-letter code, except when it's actually the media extension.
    # Path.stem has already stripped ".srt" etc., so for "dan.srt" the stem is
    # "dan" and the code is "dan". For "Brazilian (Forced).por.srt" the stem is
    # "Brazilian (Forced).por" -> last 3 = "por".
    if len(stem) >= 3 and stem[-3:].isalpha() and stem[-3:] not in ("srt", "ass", "ssa", "sub", "idx"):
        return stem[-3:]

    # 2-letter fallback (e.g. "en.srt" -> "eng").
    two_to_three = {
        "en": "eng", "es": "spa", "fr": "fre", "de": "ger", "it": "ita",
        "pt": "por", "ru": "rus", "ja": "jpn", "ko": "kor", "zh": "chi",
        "ar": "ara", "hi": "hin", "da": "dan", "nl": "dut", "fi": "fin",
        "nb": "nob", "sv": "swe", "sl": "slv", "uk": "ukr", "pl": "pol",
    }
    if len(stem) >= 2 and stem in two_to_three:
        return two_to_three[stem]

    return "und"


def get_subtitle_title(subtitle_path: Path) -> str:
    """Build a display title for a subtitle track from its filename.

    The title is the release label from the filename with the trailing lang
    marker (``.lll`` or ``.HI``) stripped; ``"SDH"`` leaning-impaired tracks
    get ``" (SDH)"`` appended when the name doesn't already say SDH. Examples:

      ``"SDH.eng.srt"``                -> ``"English (SDH)"``  (SDH + English)
      ``"Brazilian (Forced).por.srt"`` -> ``"Brazilian (Forced)"``
      ``"Ukraine (Forced).ukr.srt"``   -> ``"Ukraine (Forced)"``
      ``"eng.hi.srt"``                 -> ``"English (SDH)"``  (.HI + English)
      ``"spa.hi.srt"``                 -> ``"SDH"``            (.HI, non-English)
      ``"dan.srt"`` / ``"en.srt"``     -> ``""``  (bare code -> no title)

    "Forced" is conveyed as a disposition flag, not baked into the title;
    "(Forced)" stays only where the release label itself contains it.

    Args:
        subtitle_path: Path to subtitle file.

    Returns:
        Title string, or "" when the filename carries only a language code.
    """
    lang = get_subtitle_language(subtitle_path)
    stem = _stem_no_ext(subtitle_path)              # "Brazilian (Forced).por"
    stem_lower = stem.lower()
    is_hi = stem_lower.endswith(".hi")

    # ---- Strip the trailing lang marker (".lll" / ".HI") from the label ----
    label = stem
    if is_hi:
        label = stem[:-3]                            # drop ".HI"
    elif len(stem) >= 4 and stem[-4] == "." and stem[-3:].lower() == lang \
            and lang != "und":
        label = stem[:-4]                            # drop ".lll"
    # 2-letter code "en.srt" / "es.srt": Path.stem is "en"; lang="eng", strip "en"
    elif lang != "und" and stem_lower == lang[:2] and len(stem) == 2:
        label = ""

    # A bare language code (3-letter) leaves label == lang -> no title.
    if label.lower() == lang and lang != "und":
        label = ""

    # ---- " (SDH)" suffix for hearing-impaired tracks ----
    title = label
    hearing = needs_sdh_flag(subtitle_path) or is_hi
    if hearing:
        # Hearing-impaired English with a bare/SDH-only label -> friendly name.
        if lang == "eng" and label.lower() in ("", "sdh"):
            title = "English (SDH)"
        # Other hearing-impaired: append "(SDH)" only if not already in the title.
        elif "sdh" not in stem_lower:
            title = label + " (SDH)" if label else "SDH"

    return " ".join(title.split())


def _is_main_subtitle(subtitle_path: Path, video_path: Path | None) -> bool:
    """True when ``subtitle_path`` is the same-named sub for ``video_path``.

    Release naming convention: a subtitle sitting next to the video with the
    same base name (``Movie.2026.mp4`` -> ``Movie.2026.srt``) is the primary
    English track (see msr.bat's ``MAIN_SUB``). We compare stem-to-stem so a
    ``.eng`` infix or bracketed dotted tag doesn't break the match, and accept
    any subtitle extension.
    """
    if video_path is None:
        return False
    video_stem = video_path.stem
    sub_stem = subtitle_path.stem
    # As a fallback, also accept stem-with-suffix stripped once more, so
    # "Movie.eng.srt" vs video "Movie.mp4" (video_stem "Movie") still matches.
    if video_stem == sub_stem:
        return True
    # subtitle stem may carry a trailing "<video_ext>" artifact; compare the
    # subtitle stem up to the video's base length.
    return sub_stem == video_stem


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
    default_sub = select_default_subtitle(subtitle_files)

    # The same-named main subtitle is conventionally English and the default.
    main_sub = next((s for s in subtitle_files if _is_main_subtitle(s, video_path)), None)

    for i, sub_file in enumerate(subtitle_files):
        disposition_flags = []

        # Check if this should be the default subtitle
        if sub_file == default_sub or sub_file == main_sub:
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
    """Build FFmpeg metadata arguments for subtitle streams.

    Args:
        config: Application configuration.
        subtitle_files: List of subtitle file paths found for the video.
        video_path: Source video path, used to identify the same-named main
            subtitle and label it English ("language=eng", title="English").

    Returns:
        List of FFmpeg arguments for metadata settings.
    """
    args: List[str] = []

    main_sub = next((s for s in subtitle_files if _is_main_subtitle(s, video_path)), None)

    for i, sub_file in enumerate(subtitle_files):
        # Same-named main subtitle -> English by release convention.
        if sub_file == main_sub:
            lang = "eng"
            title = "English"
        else:
            # Language metadata
            lang = get_subtitle_language(sub_file)
            title = get_subtitle_title(sub_file)
        args.extend([f"-metadata:s:s:{i}", f"language={lang}"])

        # Title metadata
        if title:
            args.extend([f"-metadata:s:s:{i}", f"title={title}"])

    return args


if __name__ == "__main__":
    # Self-check against the real filenames from the Michael batch that broke.
    # Verify the previously-wrong values are now correct before trusting this.
    from pathlib import Path
    subs = [
        Path("SDH.eng.srt"),                      # was: lang=eng, title="SDH.eng (SDH)"
        Path("Brazilian (Forced).por.srt"),       # was: lang=por, title="Brazilian (Forced).por"
        Path("Brazilian.por.srt"),               # was: lang=por, title="Brazilian.por"
        Path("European (Forced).spa.srt"),
        Path("Latin American.spa.srt"),
        Path("Forced.ger.srt"),
        Path("Forced.hin.srt"),
        Path("Forced.ita.srt"),
        Path("Slovenia.slv.srt"),                # was: lang MISSING (und dropped), title="Slovenia.slv"
        Path("Ukraine (Forced).ukr.srt"),        # was: lang MISSING
        Path("Ukraine.ukr.srt"),
        Path("dan.srt"),                         # was: lang MISSING, title="dan"
        Path("dut.srt"),
        Path("fin.srt"),
        Path("ger.srt"),
        Path("hin.srt"),
        Path("ita.srt"),
        Path("nob.srt"),
        Path("swe.srt"),
        Path("eng.hi.srt"),                      # .HI english -> hearing_impaired disp, lang eng
        Path("spa.hi.srt"),                      # .HI non-english -> disp, lang und
        Path("English.srt"),                     # spoken-language override -> eng, title "English"
        Path("en.srt"),                          # 2-letter -> eng
    ]
    print("Default subtitle:", select_default_subtitle(subs).name if subs else None)
    for s in subs:
        print(f"{s.name}:")
        print(f"  forced={needs_forced_flag(s):<5} sdh={needs_sdh_flag(s):<5} "
              f"language={get_subtitle_language(s):<4} title={get_subtitle_title(s)!r}")