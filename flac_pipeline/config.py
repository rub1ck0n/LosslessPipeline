import re

HEADERS = {"User-Agent": "FLACStudio/2.0"}

GENRE_STANDARD: dict[str, str] = {
    "metal": "Metal",
    "метал": "Metal",
    "heavy metal": "Heavy Metal",
    "тяжелый метал": "Heavy Metal",
    "black metal": "Black Metal",
    "death metal": "Death Metal",
    "thrash metal": "Thrash Metal",
    "nu metal": "Nu Metal",
    "alternative metal": "Alternative Metal",
    "progressive metal": "Progressive Metal",
    "metalcore": "Metalcore",
    "deathcore": "Deathcore",
    "grunge": "Grunge",
    "гранж": "Grunge",
    "rock": "Rock",
    "рок": "Rock",
    "alternative": "Alternative",
    "альтернатива": "Alternative",
    "альтернативная музыка": "Alternative",
    "alternative rock": "Alternative Rock",
    "альтернативный рок": "Alternative Rock",
    "hard rock": "Hard Rock",
    "хард-рок": "Hard Rock",
    "indie": "Indie Rock",
    "инди": "Indie Rock",
    "indie rock": "Indie Rock",
    "инди-рок": "Indie Rock",
    "post-punk": "Post-Punk",
    "пост-панк": "Post-Punk",
    "punk": "Punk Rock",
    "панк": "Punk Rock",
    "punk rock": "Punk Rock",
    "панк-рок": "Punk Rock",
    "pop punk": "Pop Punk",
    "shoegaze": "Shoegaze",
    "emo": "Emo",
    "hip-hop": "Hip-Hop",
    "hip hop": "Hip-Hop",
    "hip-hop/rap": "Hip-Hop",
    "rap": "Hip-Hop",
    "rap/hip hop": "Hip-Hop",
    "хип-хоп": "Hip-Hop",
    "рэп": "Hip-Hop",
    "хип-хоп/рэп": "Hip-Hop",
    "рэп/хип-хоп": "Hip-Hop",
    "trap": "Trap",
    "rage": "Hip-Hop",
    "cloud rap": "Hip-Hop",
    "phonk": "Phonk",
    "r&b": "R&B",
    "r&b/soul": "R&B",
    "r&b/соул": "R&B",
    "electronic": "Electronic",
    "электроника": "Electronic",
    "электронная музыка": "Electronic",
    "электро": "Electronic",
    "dance": "Electronic",
    "танцевальная": "Electronic",
    "танцевальная музыка": "Electronic",
    "electro": "Electronic",
    "house": "House",
    "techno": "Techno",
    "drum & bass": "Drum & Bass",
    "dnb": "Drum & Bass",
    "ambient": "Ambient",
    "synthwave": "Synthwave",
    "hyperpop": "Hyperpop",
    "hardstyle": "Electronic",
    "pop": "Pop",
    "поп": "Pop",
    "поп-музыка": "Pop",
    "indie pop": "Indie Pop",
    "synth-pop": "Synth-Pop",
}

DEEZER_GENRE_IDS: dict[int, str] = {
    132: "Pop",
    116: "Hip-Hop",
    152: "Rock",
    113: "Electronic",
    106: "Electronic",
    165: "R&B",
    85: "Alternative",
    464: "Metal",
    129: "Jazz",
    98: "Classical",
    153: "Blues",
    466: "Folk",
}

STANDARD_GENRES_LIST: list[str] = sorted(set(GENRE_STANDARD.values()))


def normalize_genre(raw_genre: str) -> str:
    if not raw_genre:
        return "Unknown"
    cleaned = raw_genre.strip().lower()
    if cleaned in ("unknown", "неизвестно", "other", "музыка", "music", "various", ""):
        return "Unknown"

    if cleaned in GENRE_STANDARD:
        return GENRE_STANDARD[cleaned]

    for sep in ("/", ",", ";", "&", "-"):
        if sep in cleaned:
            for part in cleaned.split(sep):
                p = part.strip()
                if p in GENRE_STANDARD:
                    return GENRE_STANDARD[p]

    for key, val in GENRE_STANDARD.items():
        if key in cleaned:
            return val

    return raw_genre.strip().title()


def sanitize_filename(text: str) -> str:
    return re.sub(r'[\\/:*?"<>|]', "", text).strip()