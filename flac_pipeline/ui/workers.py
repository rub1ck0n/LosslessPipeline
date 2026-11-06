from pathlib import Path
from PySide6.QtCore import QThread, Signal
from models.album import AlbumInfo
from services.cache_manager import app_cache
from services.metadata_api import (
    search_album_candidates,
    search_cover_candidates,
    fetch_candidate_details,
    fetch_genre_fallback,
)
from services.lyrics_api import fetch_synced_lyrics
from services.audio_tagger import (
    scan_folder_for_albums,
    match_album_tracks_with_remote,
    write_track_tags,
)
from services.quality_checker import inspect_flac_quality


class FolderScanWorker(QThread):
    status_Signal = Signal(str)
    finished_Signal = Signal(object)
    error_Signal = Signal(str)

    def __init__(self, folder_path: Path, force_rescan: bool = False):
        super().__init__()
        self.folder_path = folder_path
        self.force_rescan = force_rescan

    def run(self) -> None:
        try:
            self.status_Signal.emit(f"Импорт папки: {self.folder_path}...")
            albums = scan_folder_for_albums(self.folder_path)
            if not albums:
                self.error_Signal.emit(f"В папке '{self.folder_path}' не найдено файлов .flac!")
                return

            for alb in albums:
                if not alb.genre or alb.genre == "Unknown":
                    cached_g = None if self.force_rescan else app_cache.get_cached_genre(alb.artist, alb.album)
                    if cached_g:
                        alb.genre = cached_g
                    else:
                        self.status_Signal.emit(f"Определяю жанр релиза: {alb.artist} — {alb.album}...")
                        detected_g = fetch_genre_fallback(alb.artist, alb.album)
                        if detected_g != "Unknown":
                            alb.genre = detected_g
                            app_cache.set_cached_genre(alb.artist, alb.album, detected_g)

            check_spectrum = app_cache.get_setting("auto_check_spectrum", True)
            all_tracks = [t for alb in albums for t in alb.tracks]
            total = len(all_tracks)
            cached_hits = 0

            for idx, track in enumerate(all_tracks, start=1):
                if not track.file_path or not track.file_path.exists():
                    continue

                cached = None if self.force_rescan else app_cache.get_file_cache(track.file_path)
                if cached and cached.get("quality_label"):
                    track.quality_label = cached["quality_label"]
                    track.is_authentic_flac = cached.get("is_authentic", True)
                    if not track.synced_lyrics and cached.get("synced_lyrics"):
                        track.synced_lyrics = cached["synced_lyrics"]
                    cached_hits += 1
                elif check_spectrum:
                    self.status_Signal.emit(f"[{idx}/{total}] Анализ спектра: {track.file_path.name}...")
                    q_res = inspect_flac_quality(track.file_path)
                    track.is_authentic_flac = q_res["is_authentic"]
                    track.quality_label = q_res["label"]
                    app_cache.update_file_cache(
                        track.file_path,
                        quality_label=track.quality_label,
                        is_authentic=track.is_authentic_flac,
                        synced_lyrics=track.synced_lyrics,
                    )

            app_cache.set_last_folder(self.folder_path)
            app_cache.save()

            self.status_Signal.emit(
                f"Загружено релизов: {len(albums)} (треков: {total}, из кэша: {cached_hits})."
            )
            self.finished_Signal.emit(albums)
        except Exception as e:
            self.error_Signal.emit(f"Ошибка чтения папки: {e}")


class CandidatesSearchWorker(QThread):
    status_Signal = Signal(str)
    finished_Signal = Signal(list)
    error_Signal = Signal(str)

    def __init__(self, artist: str, album: str, expected_tracks: int):
        super().__init__()
        self.artist = artist
        self.album = album
        self.expected_tracks = expected_tracks

    def run(self) -> None:
        try:
            self.status_Signal.emit(f"Поиск подходящих релизов для '{self.artist} — {self.album}'...")
            candidates = search_album_candidates(self.artist, self.album, self.expected_tracks)
            self.finished_Signal.emit(candidates)
        except Exception as e:
            self.error_Signal.emit(f"Ошибка поиска релизов: {e}")


class CoverSearchWorker(QThread):
    status_Signal = Signal(str)
    finished_Signal = Signal(list)
    error_Signal = Signal(str)

    def __init__(self, artist: str, album: str):
        super().__init__()
        self.artist = artist
        self.album = album

    def run(self) -> None:
        try:
            self.status_Signal.emit(f"Загружаю Топ-5 обложек для '{self.artist} — {self.album}'...")
            covers = search_cover_candidates(self.artist, self.album)
            self.finished_Signal.emit(covers)
        except Exception as e:
            self.error_Signal.emit(f"Ошибка поиска обложек: {e}")


class ApplyCandidateWorker(QThread):
    status_Signal = Signal(str)
    finished_Signal = Signal(object)
    error_Signal = Signal(str)

    def __init__(self, candidate: dict, current_album: AlbumInfo | None, keep_local_cover: bool):
        super().__init__()
        self.candidate = candidate
        self.current_album = current_album
        self.keep_local_cover = keep_local_cover

    def run(self) -> None:
        try:
            self.status_Signal.emit(
                f"Загружаю треклист '{self.candidate['artist']} — {self.candidate['album']}' ({self.candidate['provider']})..."
            )
            remote_album = fetch_candidate_details(self.candidate)
            if not remote_album:
                self.error_Signal.emit("Не удалось загрузить детали выбранного релиза.")
                return

            if self.current_album:
                original_cover = self.current_album.cover_bytes
                target_album = match_album_tracks_with_remote(self.current_album, remote_album)
                if self.keep_local_cover and original_cover:
                    target_album.cover_bytes = original_cover
            else:
                target_album = remote_album

            if target_album.genre and target_album.genre != "Unknown":
                app_cache.set_cached_genre(target_album.artist, target_album.album, target_album.genre)

            total = len(target_album.tracks)
            found_count = 0
            for idx, track in enumerate(target_album.tracks, start=1):
                self.status_Signal.emit(f"[{idx}/{total}] Поиск Synced Lyrics: {track.title}...")
                lrc = fetch_synced_lyrics(
                    target_album.artist, track.title, target_album.album, track.duration_sec
                )
                if lrc:
                    track.synced_lyrics = lrc
                    found_count += 1
                    if track.file_path:
                        app_cache.update_file_cache(track.file_path, synced_lyrics=lrc)

            app_cache.save()
            self.status_Signal.emit(
                f"Готово! Релиз из {target_album.source} (Жанр: {target_album.genre}). Найдено Lyrics: {found_count}/{total}."
            )
            self.finished_Signal.emit(target_album)
        except Exception as e:
            self.error_Signal.emit(f"Ошибка загрузки релиза: {e}")


class LyricsOnlyWorker(QThread):
    status_Signal = Signal(str)
    finished_Signal = Signal(object, int)
    error_Signal = Signal(str)

    def __init__(self, album_info: AlbumInfo):
        super().__init__()
        self.album_info = album_info

    def run(self) -> None:
        try:
            if not self.album_info.genre or self.album_info.genre == "Unknown":
                self.status_Signal.emit(
                    f"Определяю жанр для {self.album_info.artist} — {self.album_info.album}..."
                )
                detected = fetch_genre_fallback(self.album_info.artist, self.album_info.album)
                if detected != "Unknown":
                    self.album_info.genre = detected
                    app_cache.set_cached_genre(self.album_info.artist, self.album_info.album, detected)

            total = len(self.album_info.tracks)
            found_count = 0
            for idx, track in enumerate(self.album_info.tracks, start=1):
                self.status_Signal.emit(
                    f"[{idx}/{total}] Ищу текст на LRCLIB: {self.album_info.artist} — {track.title}..."
                )
                lrc = fetch_synced_lyrics(
                    self.album_info.artist, track.title, self.album_info.album, track.duration_sec
                )
                if lrc:
                    track.synced_lyrics = lrc
                    found_count += 1
                    if track.file_path:
                        app_cache.update_file_cache(track.file_path, synced_lyrics=lrc)

            app_cache.save()
            self.status_Signal.emit(
                f"Готово! Жанр: {self.album_info.genre}. Найдено Synced Lyrics: {found_count} из {total}."
            )
            self.finished_Signal.emit(self.album_info, found_count)
        except Exception as e:
            self.error_Signal.emit(f"Ошибка поиска текстов: {e}")


class TagWriteWorker(QThread):
    status_Signal = Signal(str)
    finished_Signal = Signal(int)
    error_Signal = Signal(str)

    def __init__(self, album_info: AlbumInfo):
        super().__init__()
        self.album_info = album_info

    def run(self) -> None:
        try:
            if self.album_info.genre and self.album_info.genre != "Unknown":
                app_cache.set_cached_genre(
                    self.album_info.artist, self.album_info.album, self.album_info.genre
                )

            saved_count = 0
            for track in self.album_info.tracks:
                if track.file_path and track.file_path.exists():
                    self.status_Signal.emit(f"Записываю теги и обложку: {track.title}...")
                    write_track_tags(self.album_info, track)
                    app_cache.update_file_cache(
                        track.file_path,
                        quality_label=track.quality_label,
                        is_authentic=track.is_authentic_flac,
                        synced_lyrics=track.synced_lyrics,
                    )
                    saved_count += 1
            app_cache.save()
            self.finished_Signal.emit(saved_count)
        except Exception as e:
            self.error_Signal.emit(f"Ошибка записи файлов: {e}")