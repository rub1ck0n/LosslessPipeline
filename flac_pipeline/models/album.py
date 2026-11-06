from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class TrackInfo:
    title: str
    track_number: int
    track_total: int
    disc_number: int = 1
    disc_total: int = 1
    duration_sec: int = 0
    track_artist: str = ""
    isrc: str = ""
    composer: str = ""
    explicit: bool = False
    synced_lyrics: str | None = None
    file_path: Path | None = None
    is_authentic_flac: bool | None = None
    quality_label: str = "—"


@dataclass
class AlbumInfo:
    artist: str
    album: str
    year: str
    genre: str
    release_date: str = ""
    label: str = ""
    copyright_text: str = ""
    upc: str = ""
    explicit: bool = False
    disc_total: int = 1
    source: str = "Manual"
    cover_bytes: bytes | None = None
    folder_path: Path | None = None
    tracks: list[TrackInfo] = field(default_factory=list)