import json
from pathlib import Path

CACHE_FILE = Path.home() / ".flac_studio_cache.json"


class CacheManager:
    def __init__(self):
        self.data: dict = {
            "last_folder": "",
            "recent_folders": [],
            "volume": 75,
            "shuffle_enabled": False,
            "settings": {
                "auto_load_last_folder": True,
                "auto_check_spectrum": True,
            },
            "album_genres": {},
            "files": {},
        }
        self.load()

    def load(self) -> None:
        if CACHE_FILE.exists():
            try:
                loaded = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    self.data.update(loaded)
            except Exception:
                pass

    def save(self) -> None:
        try:
            CACHE_FILE.write_text(
                json.dumps(self.data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except Exception:
            pass

    def get_volume(self) -> int:
        val = self.data.get("volume", 75)
        return max(0, min(100, int(val)))

    def set_volume(self, volume: int) -> None:
        self.data["volume"] = max(0, min(100, int(volume)))
        self.save()

    def get_shuffle(self) -> bool:
        return bool(self.data.get("shuffle_enabled", False))

    def set_shuffle(self, enabled: bool) -> None:
        self.data["shuffle_enabled"] = bool(enabled)
        self.save()

    def get_cached_genre(self, artist: str, album: str) -> str | None:
        key = f"{artist.strip().lower()}::{album.strip().lower()}"
        genre = self.data.get("album_genres", {}).get(key)
        return genre if genre and genre != "Unknown" else None

    def set_cached_genre(self, artist: str, album: str, genre: str) -> None:
        if genre and genre != "Unknown":
            key = f"{artist.strip().lower()}::{album.strip().lower()}"
            self.data.setdefault("album_genres", {})[key] = genre

    def set_last_folder(self, folder: Path) -> None:
        folder_str = str(folder.resolve())
        self.data["last_folder"] = folder_str
        recents: list[str] = self.data.get("recent_folders", [])
        if folder_str in recents:
            recents.remove(folder_str)
        recents.insert(0, folder_str)
        self.data["recent_folders"] = recents[:8]
        self.save()

    def get_last_folder(self) -> Path | None:
        path_str = self.data.get("last_folder", "")
        if path_str and Path(path_str).exists():
            return Path(path_str)
        return None

    def get_recent_folders(self) -> list[Path]:
        return [Path(p) for p in self.data.get("recent_folders", []) if Path(p).exists()]

    def get_setting(self, key: str, default: bool = True) -> bool:
        return bool(self.data.get("settings", {}).get(key, default))

    def set_setting(self, key: str, value: bool) -> None:
        self.data.setdefault("settings", {})[key] = value
        self.save()

    def get_file_cache(self, file_path: Path) -> dict | None:
        try:
            stat = file_path.stat()
            key = str(file_path.resolve())
            entry = self.data.get("files", {}).get(key)
            if entry and entry.get("mtime") == int(stat.st_mtime) and entry.get("size") == stat.st_size:
                return entry
        except Exception:
            pass
        return None

    def update_file_cache(
        self,
        file_path: Path,
        quality_label: str | None = None,
        is_authentic: bool | None = None,
        waveform: list[float] | None = None,
        synced_lyrics: str | None = None,
    ) -> None:
        try:
            stat = file_path.stat()
            key = str(file_path.resolve())
            entry = self.data.setdefault("files", {}).get(key, {})
            entry["mtime"] = int(stat.st_mtime)
            entry["size"] = stat.st_size
            if quality_label is not None:
                entry["quality_label"] = quality_label
            if is_authentic is not None:
                entry["is_authentic"] = is_authentic
            if waveform is not None:
                entry["waveform"] = waveform
            if synced_lyrics is not None:
                entry["synced_lyrics"] = synced_lyrics
            self.data["files"][key] = entry
        except Exception:
            pass

    def clear_all_cache(self) -> None:
        self.data["files"] = {}
        self.data["album_genres"] = {}
        self.save()


app_cache = CacheManager()