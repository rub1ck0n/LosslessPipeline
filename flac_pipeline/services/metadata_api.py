import re
from difflib import SequenceMatcher
import httpx
from config import HEADERS, DEEZER_GENRE_IDS, normalize_genre
from models.album import AlbumInfo, TrackInfo


def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower().strip(), b.lower().strip()).ratio()


def _score_candidate(
    target_artist: str,
    target_album: str,
    cand_artist: str,
    cand_album: str,
    expected_tracks: int,
    cand_tracks: int,
) -> float:
    artist_sim = _similarity(target_artist, cand_artist)
    clean_cand_alb = re.sub(r"\s*[-(\[](deluxe|single|ep|explicit).*?[)\]]?", "", cand_album, flags=re.I)
    album_sim = max(_similarity(target_album, cand_album), _similarity(target_album, clean_cand_alb))

    if artist_sim < 0.45:
        return 0.0

    track_bonus = 0.0
    if expected_tracks > 0 and cand_tracks > 0:
        diff = abs(expected_tracks - cand_tracks)
        if diff == 0:
            track_bonus = 0.20
        elif diff <= 2:
            track_bonus = 0.10
        elif diff > 8:
            track_bonus = -0.15

    raw_score = (artist_sim * 0.55) + (album_sim * 0.35) + track_bonus
    return round(min(99.0, max(1.0, raw_score * 100)), 1)


def fetch_genre_fallback(artist: str, album: str) -> str:
    with httpx.Client(timeout=8.0, headers=HEADERS) as client:
        for country in ("us", "ru"):
            try:
                resp = client.get(
                    "https://itunes.apple.com/search",
                    params={"term": f"{artist} {album}", "entity": "album", "limit": 8, "country": country},
                )
                if resp.status_code == 200:
                    for item in resp.json().get("results", []):
                        if _similarity(artist, item.get("artistName", "")) >= 0.55:
                            g = normalize_genre(item.get("primaryGenreName", ""))
                            if g != "Unknown":
                                return g
            except Exception:
                pass

        try:
            resp = client.get("https://api.deezer.com/search/album", params={"q": f"{artist} {album}", "limit": 8})
            if resp.status_code == 200:
                for item in resp.json().get("data", []):
                    if _similarity(artist, item.get("artist", {}).get("name", "")) >= 0.55:
                        gid = int(item.get("genre_id", -1))
                        if gid in DEEZER_GENRE_IDS:
                            return DEEZER_GENRE_IDS[gid]
        except Exception:
            pass

        for country in ("us", "ru"):
            try:
                resp = client.get(
                    "https://itunes.apple.com/search",
                    params={"term": artist, "entity": "song", "limit": 8, "country": country},
                )
                if resp.status_code == 200:
                    for item in resp.json().get("results", []):
                        if _similarity(artist, item.get("artistName", "")) >= 0.65:
                            g = normalize_genre(item.get("primaryGenreName", ""))
                            if g != "Unknown":
                                return g
            except Exception:
                pass

        try:
            resp = client.get(
                "https://musicbrainz.org/ws/2/artist/",
                params={"query": f'artist:"{artist}"', "fmt": "json", "limit": 3},
            )
            if resp.status_code == 200:
                for art in resp.json().get("artists", []):
                    if _similarity(artist, art.get("name", "")) >= 0.65:
                        tags = sorted(art.get("tags", []), key=lambda t: int(t.get("count", 0)), reverse=True)
                        for t in tags:
                            g = normalize_genre(t.get("name", ""))
                            if g != "Unknown":
                                return g
        except Exception:
            pass

    return "Unknown"


def search_album_candidates(artist: str, album: str, expected_tracks: int = 0) -> list[dict]:
    candidates: list[dict] = []
    seen_keys: set[tuple[str, str, int]] = set()

    try:
        with httpx.Client(timeout=10.0, headers=HEADERS) as client:
            for query in (f"{artist} {album}", artist):
                resp = client.get("https://api.deezer.com/search/album", params={"q": query, "limit": 15})
                if resp.status_code != 200:
                    continue
                for item in resp.json().get("data", []):
                    c_artist = item.get("artist", {}).get("name", "")
                    c_album = item.get("title", "")
                    c_tracks = int(item.get("nb_tracks", 0))
                    score = _score_candidate(artist, album, c_artist, c_album, expected_tracks, c_tracks)
                    if score < 40.0:
                        continue
                    dedup_key = (c_artist.lower(), c_album.lower(), c_tracks)
                    if dedup_key in seen_keys:
                        continue
                    seen_keys.add(dedup_key)
                    gid = int(item.get("genre_id", -1))
                    candidates.append({
                        "provider": "Deezer",
                        "id": item["id"],
                        "artist": c_artist,
                        "album": c_album,
                        "track_count": c_tracks,
                        "year": "",
                        "genre": DEEZER_GENRE_IDS.get(gid, "Unknown"),
                        "cover_preview_url": item.get("cover_medium", ""),
                        "cover_hi_res_url": item.get("cover_xl") or item.get("cover_big", ""),
                        "score": score,
                    })
                if candidates:
                    break
    except Exception:
        pass

    try:
        with httpx.Client(timeout=10.0, headers=HEADERS) as client:
            for country in ("us", "ru"):
                resp = client.get(
                    "https://itunes.apple.com/search",
                    params={"term": f"{artist} {album}", "entity": "album", "limit": 15, "country": country},
                )
                if resp.status_code != 200:
                    continue
                for item in resp.json().get("results", []):
                    c_artist = item.get("artistName", "")
                    c_album = item.get("collectionName", "").removesuffix(" - Single").removesuffix(" - EP")
                    c_tracks = int(item.get("trackCount", 0))
                    score = _score_candidate(artist, album, c_artist, c_album, expected_tracks, c_tracks)
                    if score < 40.0:
                        continue
                    dedup_key = (c_artist.lower(), c_album.lower(), c_tracks)
                    if dedup_key in seen_keys:
                        continue
                    seen_keys.add(dedup_key)
                    art100 = item.get("artworkUrl100", "")
                    hi_res = re.sub(r"\d+x\d+bb\.jpg$", "10000x10000-999.jpg", art100) if art100 else ""
                    candidates.append({
                        "provider": f"iTunes ({country.upper()})",
                        "id": item["collectionId"],
                        "country": country,
                        "artist": c_artist,
                        "album": c_album,
                        "track_count": c_tracks,
                        "year": item.get("releaseDate", "")[:4],
                        "genre": normalize_genre(item.get("primaryGenreName", "Unknown")),
                        "cover_preview_url": art100,
                        "cover_hi_res_url": hi_res,
                        "score": score,
                    })
    except Exception:
        pass

    candidates.sort(key=lambda c: c["score"], reverse=True)
    return candidates[:5]


def search_cover_candidates(artist: str, album: str) -> list[dict]:
    raw_candidates = search_album_candidates(artist, album, expected_tracks=0)
    cover_results: list[dict] = []
    seen_urls: set[str] = set()

    with httpx.Client(timeout=12.0, headers=HEADERS) as client:
        for cand in raw_candidates:
            url = cand.get("cover_hi_res_url") or cand.get("cover_preview_url")
            if not url or url in seen_urls:
                continue
            seen_urls.add(url)
            try:
                resp = client.get(url)
                if resp.status_code == 200 and len(resp.content) > 1024:
                    cover_results.append({
                        "provider": cand["provider"],
                        "artist": cand["artist"],
                        "album": cand["album"],
                        "score": cand["score"],
                        "cover_bytes": resp.content,
                    })
            except Exception:
                continue
            if len(cover_results) >= 5:
                break

    return cover_results


def fetch_candidate_details(candidate: dict) -> AlbumInfo | None:
    provider = candidate["provider"]
    with httpx.Client(timeout=15.0, headers=HEADERS) as client:
        if provider == "Deezer":
            resp = client.get(f"https://api.deezer.com/album/{candidate['id']}")
            if resp.status_code != 200:
                return None
            info = resp.json()
            raw_tracks = info.get("tracks", {}).get("data", [])
            if not raw_tracks:
                return None

            cover_bytes = None
            if candidate.get("cover_hi_res_url"):
                img_r = client.get(candidate["cover_hi_res_url"])
                if img_r.status_code == 200:
                    cover_bytes = img_r.content

            genres_data = info.get("genres", {}).get("data", [])
            raw_genre = genres_data[0]["name"] if genres_data else ""
            album_artist = info.get("artist", {}).get("name", candidate["artist"])
            album_title = info.get("title", candidate["album"])

            std_genre = normalize_genre(raw_genre)
            if std_genre == "Unknown":
                gid = int(info.get("genre_id", -1))
                std_genre = DEEZER_GENRE_IDS.get(gid, "Unknown")
            if std_genre == "Unknown":
                std_genre = fetch_genre_fallback(album_artist, album_title)

            release_date = str(info.get("release_date", ""))[:10]

            tracks: list[TrackInfo] = []
            total = len(raw_tracks)
            for idx, t in enumerate(raw_tracks, start=1):
                tr_artist = t.get("artist", {}).get("name", album_artist)
                tracks.append(
                    TrackInfo(
                        title=t.get("title", "").strip(),
                        track_number=int(t.get("track_position", idx)),
                        track_total=total,
                        disc_number=int(t.get("disk_number", 1)),
                        disc_total=1,
                        duration_sec=int(t.get("duration", 0)),
                        track_artist=tr_artist,
                        isrc=str(t.get("isrc", "")),
                        explicit=bool(t.get("explicit_lyrics", False)),
                    )
                )
            disc_total = max((t.disc_number for t in tracks), default=1)
            for t in tracks:
                t.disc_total = disc_total
            tracks.sort(key=lambda x: (x.disc_number, x.track_number))

            return AlbumInfo(
                artist=album_artist,
                album=album_title,
                year=release_date[:4],
                release_date=release_date,
                genre=std_genre,
                label=str(info.get("label", "")),
                upc=str(info.get("upc", "")),
                explicit=bool(info.get("explicit_lyrics", False)),
                disc_total=disc_total,
                source="Deezer",
                cover_bytes=cover_bytes,
                tracks=tracks,
            )

        else:
            country = candidate.get("country", "us")
            resp = client.get(
                "https://itunes.apple.com/lookup",
                params={"id": candidate["id"], "entity": "song", "limit": 200, "country": country},
            )
            if resp.status_code != 200:
                return None
            items = resp.json().get("results", [])
            if len(items) < 2:
                return None

            col = items[0]
            raw_tracks = [i for i in items[1:] if i.get("wrapperType") == "track"]
            cover_bytes = None
            if candidate.get("cover_hi_res_url"):
                img_r = client.get(candidate["cover_hi_res_url"])
                if img_r.status_code == 200:
                    cover_bytes = img_r.content

            album_artist = col.get("artistName", candidate["artist"])
            album_title = col.get("collectionName", candidate["album"]).removesuffix(" - Single").removesuffix(" - EP")
            release_date = str(col.get("releaseDate", ""))[:10]
            copyright_str = str(col.get("copyright", ""))
            is_alb_explicit = col.get("collectionExplicitness") == "explicit"

            std_genre = normalize_genre(col.get("primaryGenreName", ""))
            if std_genre == "Unknown":
                std_genre = fetch_genre_fallback(album_artist, album_title)

            tracks = []
            for t in raw_tracks:
                tracks.append(
                    TrackInfo(
                        title=t.get("trackName", "").strip(),
                        track_number=int(t.get("trackNumber", 1)),
                        track_total=int(t.get("trackCount", len(raw_tracks))),
                        disc_number=int(t.get("discNumber", 1)),
                        disc_total=int(t.get("discCount", 1)),
                        duration_sec=round(t.get("trackTimeMillis", 0) / 1000),
                        track_artist=t.get("artistName", album_artist),
                        explicit=(t.get("trackExplicitness") == "explicit"),
                    )
                )
            tracks.sort(key=lambda x: (x.disc_number, x.track_number))
            disc_total = max((t.disc_total for t in tracks), default=1)

            return AlbumInfo(
                artist=album_artist,
                album=album_title,
                year=release_date[:4],
                release_date=release_date,
                genre=std_genre,
                copyright_text=copyright_str,
                explicit=is_alb_explicit,
                disc_total=disc_total,
                source=provider,
                cover_bytes=cover_bytes,
                tracks=tracks,
            )