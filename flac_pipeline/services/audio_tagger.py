import re
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path
from mutagen.flac import FLAC, Picture
from config import normalize_genre, sanitize_filename
from models.album import AlbumInfo, TrackInfo


def find_flac_files(folder_path: str | Path) -> list[Path]:
    path = Path(folder_path)
    if path.is_file() and path.suffix.lower() == ".flac":
        return [path]
    if not path.exists():
        return []
    return sorted(p for p in path.rglob("*") if p.is_file() and p.suffix.lower() == ".flac")


def read_all_raw_flac_tags(flac_path: str | Path) -> dict:
    path = Path(flac_path)
    audio = FLAC(path)
    info = audio.info
    size_mb = path.stat().st_size / (1024 * 1024)
    kbps = round(info.bitrate / 1000) if getattr(info, "bitrate", 0) else round((size_mb * 8192) / max(1, info.length))
    md5_hex = f"{info.md5_signature:032x}" if getattr(info, "md5_signature", 0) else "Не задан"

    tags_list: list[tuple[str, str]] = []
    if audio.tags:
        for k, v in audio.tags.items():
            val_str = ", ".join(str(x) for x in v) if isinstance(v, list) else str(v)
            tags_list.append((str(k).upper(), val_str))

    pics_list: list[str] = []
    for idx, p in enumerate(audio.pictures, start=1):
        size_kb = len(p.data) / 1024
        pics_list.append(
            f"Обложка #{idx}: {p.mime}, {p.width}×{p.height} пикс., {p.depth} бит, {size_kb:.1f} КБ"
        )

    return {
        "file_name": path.name,
        "full_path": str(path.resolve()),
        "size_mb": f"{size_mb:.2f} МБ",
        "stream": f"FLAC {info.bits_per_sample}-bit / {info.sample_rate} Гц • {info.channels} кан. • ~{kbps} kbps",
        "duration_sec": round(info.length),
        "md5": md5_hex,
        "pictures": pics_list,
        "tags": tags_list,
    }


def scan_folder_for_albums(folder_path: str | Path) -> list[AlbumInfo]:
    flac_files = find_flac_files(folder_path)
    if not flac_files:
        return []

    grouped_files: dict[tuple[str, str], list[Path]] = defaultdict(list)

    for flac_file in flac_files:
        audio = FLAC(flac_file)
        artist = audio.get("albumartist", audio.get("artist", [""]))[0].strip()
        album = audio.get("album", [""])[0].strip()

        if not artist:
            parts = [p.strip() for p in flac_file.stem.split(" - ")]
            if len(parts) >= 3 and parts[0].isdigit():
                artist = parts[1]
            elif len(parts) == 2 and not parts[0].isdigit():
                artist = parts[0]
            else:
                artist = flac_file.parent.name

        if not album:
            album = flac_file.parent.name

        key = (artist.lower(), album.lower())
        grouped_files[key].append(flac_file)

    albums_list: list[AlbumInfo] = []

    for (_art_key, _alb_key), files in grouped_files.items():
        first_audio = FLAC(files[0])
        artist = first_audio.get("albumartist", first_audio.get("artist", [files[0].parent.name]))[0].strip()
        album = first_audio.get("album", [files[0].parent.name])[0].strip()
        raw_date = first_audio.get("releasedate", first_audio.get("date", first_audio.get("year", [""])))[0].strip()
        year = raw_date[:4]
        release_date = raw_date if len(raw_date) == 10 else ""

        detected_genre = "Unknown"
        for f_check in files:
            a_check = FLAC(f_check)
            g_list = a_check.get("genre", [])
            if g_list and g_list[0].strip():
                norm_g = normalize_genre(g_list[0])
                if norm_g != "Unknown":
                    detected_genre = norm_g
                    break

        label = first_audio.get("label", first_audio.get("organization", [""]))[0].strip()
        copyright_text = first_audio.get("copyright", [""])[0].strip()
        upc = first_audio.get("upc", first_audio.get("barcode", [""]))[0].strip()
        alb_explicit = first_audio.get("explicit", first_audio.get("itunesadvisory", ["0"]))[0] in ("1", "true", "True")

        cover_bytes = first_audio.pictures[0].data if first_audio.pictures else None

        tracks: list[TrackInfo] = []
        total = len(files)

        for idx, f_path in enumerate(files, start=1):
            audio = FLAC(f_path)
            raw_title = audio.get("title", [f_path.stem])[0]
            if "title" not in audio:
                raw_title = re.sub(r"^(\d+[-.]?\d*)\s*[-._]?\s*", "", raw_title)

            raw_tr_num = str(audio.get("tracknumber", [str(idx)])[0]).split("/")[0].strip()
            track_num = int(raw_tr_num) if raw_tr_num.isdigit() else idx

            raw_disc = str(audio.get("discnumber", ["1"])[0]).split("/")[0].strip()
            disc_num = int(raw_disc) if raw_disc.isdigit() else 1

            tr_artist = audio.get("artist", [artist])[0].strip()
            isrc = audio.get("isrc", [""])[0].strip()
            composer = audio.get("composer", [""])[0].strip()
            tr_explicit = audio.get("explicit", audio.get("itunesadvisory", ["0"]))[0] in ("1", "true", "True")

            tracks.append(
                TrackInfo(
                    title=raw_title.strip(),
                    track_number=track_num,
                    track_total=total,
                    disc_number=disc_num,
                    disc_total=1,
                    duration_sec=round(audio.info.length),
                    track_artist=tr_artist,
                    isrc=isrc,
                    composer=composer,
                    explicit=tr_explicit or alb_explicit,
                    synced_lyrics=audio.get("lyrics", [None])[0],
                    file_path=f_path,
                )
            )

        unique_discs = sorted({t.disc_number for t in tracks})
        disc_total = len(unique_discs) if len(unique_discs) > 1 else 1
        for t in tracks:
            if disc_total == 1:
                t.disc_number = 1
            t.disc_total = disc_total

        tracks.sort(key=lambda x: (x.disc_number, x.track_number))

        albums_list.append(
            AlbumInfo(
                artist=artist,
                album=album,
                year=year,
                release_date=release_date,
                genre=detected_genre,
                label=label,
                copyright_text=copyright_text,
                upc=upc,
                explicit=alb_explicit,
                disc_total=disc_total,
                source="Local Files",
                cover_bytes=cover_bytes,
                folder_path=files[0].parent,
                tracks=tracks,
            )
        )

    return albums_list


def match_album_tracks_with_remote(local_album: AlbumInfo, remote_album: AlbumInfo) -> AlbumInfo:
    local_files = [t for t in local_album.tracks if t.file_path and t.file_path.exists()]
    if not local_files:
        return remote_album

    if remote_album.genre in ("", "Unknown") and local_album.genre not in ("", "Unknown"):
        remote_album.genre = local_album.genre

    used_remote: set[int] = set()
    matched_tracks: list[TrackInfo] = []

    for loc_track in local_files:
        clean_local = loc_track.title.lower().strip()

        best_idx = None
        best_score = -1.0
        for rem_idx, rem_track in enumerate(remote_album.tracks):
            if rem_idx in used_remote:
                continue
            score = SequenceMatcher(None, clean_local, rem_track.title.lower().strip()).ratio()
            if loc_track.track_number == rem_track.track_number:
                score += 0.15
            if score > best_score:
                best_score = score
                best_idx = rem_idx

        if best_score < 0.40:
            for rem_idx in range(len(remote_album.tracks)):
                if rem_idx not in used_remote:
                    best_idx = rem_idx
                    break

        if best_idx is not None:
            used_remote.add(best_idx)
            rem = remote_album.tracks[best_idx]
            matched_tracks.append(
                TrackInfo(
                    title=rem.title,
                    track_number=rem.track_number,
                    track_total=rem.track_total,
                    disc_number=rem.disc_number,
                    disc_total=rem.disc_total,
                    duration_sec=loc_track.duration_sec,
                    track_artist=rem.track_artist or remote_album.artist,
                    isrc=rem.isrc or loc_track.isrc,
                    composer=rem.composer or loc_track.composer,
                    explicit=rem.explicit or remote_album.explicit,
                    synced_lyrics=rem.synced_lyrics or loc_track.synced_lyrics,
                    file_path=loc_track.file_path,
                    is_authentic_flac=loc_track.is_authentic_flac,
                    quality_label=loc_track.quality_label,
                )
            )
        else:
            matched_tracks.append(loc_track)

    matched_tracks.sort(key=lambda x: (x.disc_number, x.track_number))
    remote_album.tracks = matched_tracks
    if not remote_album.cover_bytes:
        remote_album.cover_bytes = local_album.cover_bytes
    remote_album.folder_path = local_album.folder_path
    return remote_album


def write_track_tags(album_info: AlbumInfo, track: TrackInfo) -> Path:
    if not track.file_path or not track.file_path.exists():
        raise FileNotFoundError(f"Файл для трека '{track.title}' не найден.")

    path = track.file_path
    audio = FLAC(path)

    audio.delete()
    audio.clear_pictures()

    audio["ALBUMARTIST"] = [album_info.artist.strip()]
    audio["ARTIST"] = [(track.track_artist or album_info.artist).strip()]
    audio["ALBUM"] = [album_info.album.strip()]
    audio["TITLE"] = [track.title.strip()]
    audio["TRACKNUMBER"] = [str(track.track_number)]
    audio["TRACKTOTAL"] = [str(track.track_total)]
    audio["DISCNUMBER"] = [str(track.disc_number)]
    audio["DISCTOTAL"] = [str(track.disc_total)]

    if str(album_info.year).strip():
        audio["DATE"] = [str(album_info.year).strip()]
        audio["YEAR"] = [str(album_info.year).strip()]

    clean_genre = normalize_genre(album_info.genre)
    if clean_genre and clean_genre != "Unknown":
        audio["GENRE"] = [clean_genre]
    elif album_info.genre.strip() and album_info.genre.strip() != "Unknown":
        audio["GENRE"] = [album_info.genre.strip()]

    if album_info.release_date.strip():
        audio["RELEASEDATE"] = [album_info.release_date.strip()]
    if track.isrc.strip():
        audio["ISRC"] = [track.isrc.strip()]
    if track.composer.strip():
        audio["COMPOSER"] = [track.composer.strip()]

    is_explicit = track.explicit or album_info.explicit
    audio["EXPLICIT"] = ["1" if is_explicit else "0"]
    audio["ITUNESADVISORY"] = ["1" if is_explicit else "0"]

    if track.synced_lyrics:
        audio["LYRICS"] = [track.synced_lyrics.strip()]

    if album_info.cover_bytes:
        pic = Picture()
        pic.type = 3
        pic.mime = "image/png" if album_info.cover_bytes.startswith(b"\x89PNG") else "image/jpeg"
        pic.desc = "Front Cover"
        pic.data = album_info.cover_bytes
        audio.add_picture(pic)

    audio.save()

    clean_artist = sanitize_filename(album_info.artist)
    clean_title = sanitize_filename(track.title)
    new_path = path.with_name(f"{clean_artist} - {clean_title}.flac")

    if path != new_path:
        path.rename(new_path)
        track.file_path = new_path

    return new_path