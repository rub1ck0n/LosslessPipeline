import re
import httpx
from config import HEADERS

LRC_LINE_REGEX = re.compile(r"^\[(\d{2}):(\d{2})\.(\d{2,3})\](.*)$")


def _clean_track_title(title: str) -> str:
    cleaned = re.sub(r"\s*[\(\[](feat\.?|ft\.?|prod\.?).*?[\)\]]", "", title, flags=re.IGNORECASE)
    return cleaned.strip()


def fetch_synced_lyrics(artist: str, title: str, album: str, duration_sec: int) -> str | None:
    with httpx.Client(timeout=10.0, headers=HEADERS) as client:
        resp = client.get(
            "https://lrclib.net/api/get",
            params={
                "artist_name": artist,
                "track_name": title,
                "album_name": album,
                "duration": duration_sec,
            },
        )
        if resp.status_code == 200:
            synced = resp.json().get("syncedLyrics")
            if synced:
                return synced

        clean_title = _clean_track_title(title)
        for query_params in (
            {"artist_name": artist, "track_name": clean_title},
            {"q": f"{artist} {clean_title}"},
        ):
            search_resp = client.get("https://lrclib.net/api/search", params=query_params)
            if search_resp.status_code != 200:
                continue

            results = search_resp.json()
            if not isinstance(results, list):
                continue

            with_synced = [r for r in results if r.get("syncedLyrics")]
            if not with_synced:
                continue

            with_synced.sort(key=lambda r: abs(float(r.get("duration") or 0) - duration_sec))
            best = with_synced[0]

            if duration_sec == 0 or abs(float(best.get("duration") or 0) - duration_sec) <= 18:
                return best["syncedLyrics"]

    return None


def search_lyrics_variants(query: str) -> list[dict]:
    with httpx.Client(timeout=10.0, headers=HEADERS) as client:
        resp = client.get("https://lrclib.net/api/search", params={"q": query.strip()})
        if resp.status_code != 200:
            return []
        data = resp.json()
        if not isinstance(data, list):
            return []

        variants = []
        for item in data:
            synced = item.get("syncedLyrics")
            plain = item.get("plainLyrics")
            if not synced and not plain:
                continue
            variants.append({
                "artist": item.get("artistName", ""),
                "title": item.get("trackName", ""),
                "album": item.get("albumName", ""),
                "duration": round(float(item.get("duration") or 0)),
                "has_synced": bool(synced),
                "lyrics": synced or plain,
            })
        variants.sort(key=lambda x: (not x["has_synced"]))
        return variants


def parse_lrc_lines(synced_lyrics: str) -> list[tuple[int, str]]:
    parsed: list[tuple[int, str]] = []
    if not synced_lyrics:
        return parsed
    for line in synced_lyrics.splitlines():
        m = LRC_LINE_REGEX.match(line.strip())
        if m:
            mins, secs, frac, text = m.groups()
            ms = int(frac) * (10 if len(frac) == 2 else 1)
            total_ms = (int(mins) * 60 + int(secs)) * 1000 + ms
            parsed.append((total_ms, text.strip()))
    return parsed


def get_first_vocal_timestamp_ms(synced_lyrics: str) -> int:
    for ts_ms, text in parse_lrc_lines(synced_lyrics):
        if text:
            return ts_ms
    return 0


def shift_lyrics_offset(synced_lyrics: str, offset_ms: int) -> str:
    shifted_lines = []
    for line in synced_lyrics.splitlines():
        match = LRC_LINE_REGEX.match(line.strip())
        if not match:
            shifted_lines.append(line)
            continue

        mins, secs, frac, text = match.groups()
        ms = int(frac) * (10 if len(frac) == 2 else 1)
        total_ms = max(0, (int(mins) * 60 + int(secs)) * 1000 + ms + offset_ms)

        new_mins, rem_ms = divmod(total_ms, 60000)
        new_secs, new_ms = divmod(rem_ms, 1000)
        centisecs = new_ms // 10

        shifted_lines.append(f"[{new_mins:02d}:{new_secs:02d}.{centisecs:02d}]{text}")

    return "\n".join(shifted_lines)