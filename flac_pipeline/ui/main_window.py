import math
import random
import subprocess
from pathlib import Path
import numpy as np
import soundfile as sf
from PySide6.QtCore import Qt, QPoint, QRectF, QTimer, QUrl, QSize
from PySide6.QtGui import (
    QPixmap, QImage, QIcon, QDragEnterEvent, QDropEvent,
    QPainter, QColor, QPen, QFont, QGuiApplication, QAction
)
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
    QPushButton, QLabel, QFileDialog, QTableWidget, QTableWidgetItem,
    QHeaderView, QSplitter, QFrame, QFormLayout, QMessageBox, QComboBox,
    QDialog, QListWidget, QListWidgetItem, QCheckBox, QMenu
)
from config import STANDARD_GENRES_LIST, normalize_genre
from models.album import AlbumInfo, TrackInfo
from services.cache_manager import app_cache
from services.lyrics_api import search_lyrics_variants
from services.audio_tagger import write_track_tags, read_all_raw_flac_tags
from ui.lyrics_player import LyricsVerifierWidget
from ui.workers import (
    FolderScanWorker,
    CandidatesSearchWorker,
    CoverSearchWorker,
    ApplyCandidateWorker,
    LyricsOnlyWorker,
    TagWriteWorker,
)

STUDIO_DARK_THEME = """
QMainWindow, QDialog {
    background-color: #0A0A0D;
    color: #EAEAEF;
    font-family: 'Segoe UI', sans-serif;
}
QMenuBar {
    background-color: #101015;
    color: #D8D8E2;
    border-bottom: 1px solid #22222A;
    padding: 3px 8px;
    font-size: 12px;
    font-weight: 600;
}
QMenuBar::item {
    background: transparent;
    padding: 5px 12px;
    border-radius: 8px;
}
QMenuBar::item:selected {
    background-color: #24242E;
    color: #FFFFFF;
}
QFrame#SurfaceCard, QFrame#PlayerCard {
    background-color: #131317;
    border: 1px solid #222229;
    border-radius: 18px;
}
QFrame#LabeledInputCapsule {
    background-color: #0C0C0F;
    border: 1px solid #25252D;
    border-radius: 11px;
}
QLineEdit, QComboBox, QPlainTextEdit, QListWidget {
    background-color: #0C0C0F;
    color: #EAEAEF;
    border: 1px solid #25252D;
    border-radius: 10px;
    padding: 6px 10px;
    font-size: 13px;
}
QLineEdit#BorderlessInnerInput {
    background-color: transparent;
    border: none;
    padding: 4px 6px;
    font-size: 13px;
    font-weight: 600;
    color: #F0F0F6;
}
QLineEdit:focus, QComboBox:focus, QPlainTextEdit:focus {
    border: 1px solid #525260;
}
QTableWidget {
    background-color: #101014;
    alternate-background-color: #141419;
    color: #E2E2E8;
    border: 1px solid #222229;
    border-radius: 14px;
    gridline-color: #1C1C22;
    selection-background-color: #282832;
    selection-color: #FFFFFF;
    font-size: 13px;
}
QHeaderView::section {
    background-color: #16161C;
    color: #888894;
    font-weight: 600;
    padding: 8px;
    border: none;
    border-bottom: 1px solid #24242C;
}
QMenu {
    background-color: #141419;
    color: #EAEAEF;
    border: 1px solid #2E2E38;
    border-radius: 12px;
    padding: 6px;
}
QMenu::item {
    padding: 7px 22px;
    border-radius: 7px;
}
QMenu::item:disabled {
    color: #8A8A98;
    font-weight: bold;
}
QMenu::item:selected {
    background-color: #2A2A34;
    color: #FFFFFF;
}
QPushButton {
    background-color: #1D1D24;
    color: #E4E4EC;
    border: 1px solid #2D2D37;
    border-radius: 15px;
    padding: 7px 16px;
    font-weight: 600;
    font-size: 12px;
}
QPushButton:hover {
    background-color: #282832;
    border: 1px solid #3E3E4C;
}
QPushButton:pressed {
    background-color: #111115;
}
QPushButton#ActionCapsule {
    background-color: #262630;
    border: 1px solid #3C3C4A;
    color: #FFFFFF;
}
QPushButton#ActionCapsule:hover {
    background-color: #32323F;
}
QSlider::groove:horizontal {
    height: 4px;
    background: #24242C;
    border-radius: 2px;
}
QSlider::sub-page:horizontal {
    background: #B0B0BC;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #F0F0F5;
    width: 12px;
    height: 12px;
    margin: -4px 0;
    border-radius: 6px;
}
"""


class LabeledInputCapsule(QFrame):
    def __init__(self, tag_title: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("LabeledInputCapsule")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(10, 2, 8, 2)
        layout.setSpacing(8)

        self.badge = QLabel(tag_title)
        self.badge.setStyleSheet(
            "background-color: #1D1D25; color: #8E8E9C; font-size: 10px; "
            "font-weight: 800; padding: 3px 7px; border-radius: 6px; letter-spacing: 0.6px;"
        )
        self.line_edit = QLineEdit()
        self.line_edit.setObjectName("BorderlessInnerInput")

        layout.addWidget(self.badge)
        layout.addWidget(self.line_edit, 1)

    def text(self) -> str:
        return self.line_edit.text()

    def setText(self, val: str) -> None:
        self.line_edit.setText(val)


def inspect_cover_bytes(cover_bytes: bytes | None) -> dict:
    if not cover_bytes:
        return {"valid": False}
    img = QImage.fromData(cover_bytes)
    if img.isNull():
        return {"valid": False}

    w, h = img.width(), img.height()
    size_kb = len(cover_bytes) / 1024.0
    size_str = f"{size_kb / 1024:.2f} МБ" if size_kb >= 1024 else f"{size_kb:.1f} КБ"

    fmt = "JPEG"
    if cover_bytes.startswith(b"\x89PNG"):
        fmt = "PNG"
    elif cover_bytes.startswith(b"RIFF") and b"WEBP" in cover_bytes[:16]:
        fmt = "WEBP"

    gcd_val = math.gcd(w, h) or 1
    ratio_str = f"{w // gcd_val}:{h // gcd_val}"

    return {
        "valid": True,
        "width": w,
        "height": h,
        "size_bytes": len(cover_bytes),
        "size_str": size_str,
        "format": fmt,
        "depth": img.depth(),
        "ratio": ratio_str,
        "badge": f"{w}×{h} • {size_str} • {fmt}",
    }


class InteractiveCoverWidget(QLabel):
    def __init__(self, parent_window: "MainWindow"):
        super().__init__(parent_window)
        self.main_win = parent_window
        self.setFixedSize(235, 235)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setStyleSheet(
            "background-color: #0C0C0F; border: 1px solid #24242C; border-radius: 18px; color: #686874;"
        )
        self._raw_bytes: bytes | None = None
        self._scaled_clean: QPixmap | None = None
        self._info: dict = {"valid": False}
        self._hovered: bool = False

    def set_cover_data(self, cover_bytes: bytes | None) -> None:
        self._raw_bytes = cover_bytes
        self._info = inspect_cover_bytes(cover_bytes)
        if self._info.get("valid") and cover_bytes:
            pix = QPixmap()
            pix.loadFromData(cover_bytes)
            self._scaled_clean = pix.scaled(
                235, 235,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._render_state()
        else:
            self._scaled_clean = None
            self.setPixmap(QPixmap())
            self.setText("Нет обложки\n(ПКМ — выбор и инфо)")

    def enterEvent(self, event) -> None:
        self._hovered = True
        self._render_state()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self._render_state()
        super().leaveEvent(event)

    def _render_state(self) -> None:
        if not self._scaled_clean:
            return
        if not self._hovered:
            self.setPixmap(self._scaled_clean)
            return

        canvas = QPixmap(self._scaled_clean.size())
        canvas.fill(Qt.GlobalColor.transparent)
        painter = QPainter(canvas)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.drawPixmap(0, 0, self._scaled_clean)

        pill_rect = QRectF(8, canvas.height() - 28, canvas.width() - 16, 22)
        painter.setBrush(QColor(8, 8, 10, 225))
        painter.setPen(QPen(QColor("#3A3A46"), 1))
        painter.drawRoundedRect(pill_rect, 9, 9)
        painter.setPen(QColor("#F0F0F6"))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(pill_rect, Qt.AlignmentFlag.AlignCenter, self._info.get("badge", ""))
        painter.end()
        self.setPixmap(canvas)

    def mouseDoubleClickEvent(self, _event) -> None:
        self.main_win.zoom_cover_dialog()

    def contextMenuEvent(self, event) -> None:
        menu = QMenu(self)
        if self._info.get("valid"):
            hdr1 = menu.addAction(
                f"Обложка: {self._info['width']}×{self._info['height']} пикс. ({self._info['ratio']})"
            )
            hdr2 = menu.addAction(
                f"Размер: {self._info['size_str']} • Формат: {self._info['format']} ({self._info['depth']} бит)"
            )
            hdr1.setEnabled(False)
            hdr2.setEnabled(False)
            menu.addSeparator()

        act_top5_cov = menu.addAction("Выбрать обложку из базы (Топ-5)...")
        act_info = menu.addAction("Подробные свойства обложки...")
        act_zoom = menu.addAction("Открыть в полном размере (Зум)")
        menu.addSeparator()
        act_copy = menu.addAction("Скопировать картинку в буфер обмена")
        act_save = menu.addAction("Сохранить обложку на диск (cover.jpg)...")
        menu.addSeparator()
        act_load = menu.addAction("Загрузить свою картинку с ПК...")
        act_restore = menu.addAction("Вернуть исходную обложку из файла")

        chosen = menu.exec(event.globalPos())
        if chosen == act_top5_cov:
            self.main_win.start_cover_top5_search()
        elif chosen == act_info:
            self.main_win.show_cover_properties()
        elif chosen == act_zoom:
            self.main_win.zoom_cover_dialog()
        elif chosen == act_copy:
            self.main_win.copy_cover_to_clipboard()
        elif chosen == act_save:
            self.main_win.export_cover_to_disk()
        elif chosen == act_load:
            self.main_win.choose_custom_cover()
        elif chosen == act_restore:
            self.main_win.restore_original_cover()


class CoverCandidatesDialog(QDialog):
    def __init__(self, covers: list[dict], parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("Выбор обложки (Топ-5 подходящих вариантов)")
        self.resize(700, 480)
        self.covers = covers
        self.selected_cover_bytes: bytes | None = None

        layout = QVBoxLayout(self)
        title_lbl = QLabel("Выбери обложку (показаны точное разрешение, размер, формат и пропорции):")
        title_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #D8D8E2;")
        layout.addWidget(title_lbl)

        self.list_widget = QListWidget()
        self.list_widget.setIconSize(QSize(84, 84))
        self.list_widget.setSpacing(6)

        for idx, c in enumerate(covers, start=1):
            info = inspect_cover_bytes(c["cover_bytes"])
            pix = QPixmap()
            pix.loadFromData(c["cover_bytes"])
            icon = QIcon(
                pix.scaled(84, 84, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            )
            specs_line = (
                f"Разрешение: {info['width']}×{info['height']} пикс. ({info['ratio']})  •  "
                f"Размер: {info['size_str']}  •  Формат: {info['format']} ({info['depth']} бит)"
                if info.get("valid")
                else "Неизвестный формат"
            )
            text = (
                f"{idx}. [{c['score']}% — {c['provider']}]  {c['artist']} — {c['album']}\n"
                f"    {specs_line}"
            )
            item = QListWidgetItem(icon, text)
            self.list_widget.addItem(item)

        self.list_widget.setCurrentRow(0)
        self.list_widget.itemDoubleClicked.connect(self.accept_cover)
        layout.addWidget(self.list_widget, 1)

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("Применить выбранную обложку")
        btn_ok.setObjectName("ActionCapsule")
        btn_ok.clicked.connect(self.accept_cover)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

    def accept_cover(self) -> None:
        row = self.list_widget.currentRow()
        if 0 <= row < len(self.covers):
            self.selected_cover_bytes = self.covers[row]["cover_bytes"]
            self.accept()


class AllFlacTagsDialog(QDialog):
    def __init__(self, track: TrackInfo, album: AlbumInfo, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Все теги файла — {track.file_path.name if track.file_path else track.title}")
        self.resize(720, 540)

        layout = QVBoxLayout(self)
        if not track.file_path or not track.file_path.exists():
            layout.addWidget(QLabel("Локальный файл не найден."))
            return

        raw_data = read_all_raw_flac_tags(track.file_path)

        pics_info = " | ".join(raw_data["pictures"]) if raw_data["pictures"] else "Вшитых обложек нет"
        summary = QLabel(
            f"Файл: {raw_data['file_name']} ({raw_data['size_mb']})\n"
            f"Аудиопоток: {raw_data['stream']}\n"
            f"MD5: {raw_data['md5']}\n"
            f"Картинки в файле: {pics_info}\n"
            f"Текущие поля в программе: Артист='{album.artist}' • Альбом='{album.album}' • Год='{album.year}' • Жанр='{album.genre}'"
        )
        summary.setStyleSheet(
            "background-color: #131318; color: #C8C8D4; padding: 10px; "
            "border-radius: 10px; border: 1px solid #24242E; font-size: 12px;"
        )
        layout.addWidget(summary)

        lbl_tbl = QLabel(f"Все Vorbis-теги, записанные внутри файла ({len(raw_data['tags'])} шт.):")
        lbl_tbl.setStyleSheet("font-weight: bold; color: #E2E2EC; margin-top: 4px;")
        layout.addWidget(lbl_tbl)

        table = QTableWidget(len(raw_data["tags"]), 2)
        table.setAlternatingRowColors(True)
        table.setHorizontalHeaderLabels(["Поле тега (Ключ Vorbis)", "Значение внутри файла"])
        table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)

        for row_idx, (k, v) in enumerate(raw_data["tags"]):
            display_v = v if len(v) <= 180 else f"{v[:180]}... (всего {len(v)} симв.)"
            table.setItem(row_idx, 0, QTableWidgetItem(k))
            table.setItem(row_idx, 1, QTableWidgetItem(display_v))

        layout.addWidget(table, 1)

        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close, alignment=Qt.AlignmentFlag.AlignRight)


class SpectrumGraphDialog(QDialog):
    def __init__(self, track: TrackInfo, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Анализ частотного спектра — {track.title}")
        self.resize(680, 400)
        self.track = track
        self.freqs: np.ndarray = np.array([])
        self.db_vals: np.ndarray = np.array([])
        self._compute_spectrum()

        layout = QVBoxLayout(self)
        info_lbl = QLabel(
            f"Файл: {track.file_path.name if track.file_path else ''}  •  Вердикт: {track.quality_label}\n"
            "Пунктирная линия на 20.0 кГц — граница среза MP3 320 kbps."
        )
        info_lbl.setStyleSheet("color: #A0A0AC; font-size: 12px;")
        layout.addWidget(info_lbl)

        self.canvas = QWidget()
        self.canvas.setMinimumHeight(290)
        layout.addWidget(self.canvas, 1)

        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close, alignment=Qt.AlignmentFlag.AlignRight)

    def _compute_spectrum(self) -> None:
        if not self.track.file_path or not self.track.file_path.exists():
            return
        try:
            data, sr = sf.read(self.track.file_path, dtype="float32")
            if data.ndim > 1:
                data = data[:, 0]
            mid = len(data) // 2
            seg = data[max(0, mid - sr * 10) : min(len(data), mid + sr * 10)]
            n_fft = 2048
            blocks = len(seg) // n_fft
            if blocks < 1:
                return
            framed = seg[: blocks * n_fft].reshape((blocks, n_fft)) * np.hanning(n_fft)
            spec = np.abs(np.fft.rfft(framed, axis=1))
            self.db_vals = 20 * np.log10(np.mean(spec, axis=0) + 1e-12)
            self.freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr) / 1000.0
        except Exception:
            pass

    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        if len(self.freqs) == 0:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = self.canvas.geometry()
        painter.fillRect(rect, QColor("#0D0D11"))
        painter.setPen(QPen(QColor("#262630"), 1))
        painter.drawRect(rect)

        max_freq = float(self.freqs[-1])
        min_db, max_db = -100.0, 0.0

        if max_freq >= 20.0:
            x_20k = rect.left() + (20.0 / max_freq) * rect.width()
            painter.setPen(QPen(QColor("#686878"), 1, Qt.PenStyle.DashLine))
            painter.drawLine(int(x_20k), rect.top(), int(x_20k), rect.bottom())
            painter.drawText(int(x_20k) - 65, rect.top() + 18, "20 kHz (MP3)")

        painter.setPen(QPen(QColor("#E0E0EA"), 1.6))
        prev_pt = None
        step = max(1, len(self.freqs) // 250)
        for i in range(0, len(self.freqs), step):
            f = float(self.freqs[i])
            db = max(min_db, min(max_db, float(self.db_vals[i])))
            x = rect.left() + (f / max_freq) * rect.width()
            y = rect.bottom() - ((db - min_db) / (max_db - min_db)) * (rect.height() - 20)
            pt = QPoint(int(x), int(y))
            if prev_pt:
                painter.drawLine(prev_pt, pt)
            prev_pt = pt


class AlbumCandidateDialog(QDialog):
    def __init__(self, candidates: list[dict], has_local_cover: bool, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle("База релизов (Топ-5 подходящих вариантов)")
        self.resize(680, 420)
        self.candidates = candidates
        self.selected_candidate: dict | None = None
        self.keep_local_cover = False

        layout = QVBoxLayout(self)
        title_lbl = QLabel("Выбери подходящий релиз (на 1-м месте самый вероятный):")
        title_lbl.setStyleSheet("font-size: 13px; font-weight: bold; color: #D4D4DC;")
        layout.addWidget(title_lbl)

        self.list_widget = QListWidget()
        for idx, c in enumerate(candidates, start=1):
            year_str = f" • {c['year']}" if c.get("year") else ""
            genre_str = f" • Жанр: {c['genre']}" if c.get("genre") and c.get("genre") != "Unknown" else ""
            badge = "Лучшее совпадение" if idx == 1 else f"Вариант #{idx}"
            text = (
                f"{idx}. [{c['score']}% — {badge}]  {c['artist']} — {c['album']}\n"
                f"    Источник: {c['provider']} • Треков: {c['track_count']}{year_str}{genre_str}"
            )
            self.list_widget.addItem(QListWidgetItem(text))

        self.list_widget.setCurrentRow(0)
        self.list_widget.itemDoubleClicked.connect(self.accept_selection)
        layout.addWidget(self.list_widget)

        self.chk_keep_cover = QCheckBox("Оставить мою текущую обложку из файлов")
        self.chk_keep_cover.setChecked(False)
        self.chk_keep_cover.setEnabled(has_local_cover)
        layout.addWidget(self.chk_keep_cover)

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("Применить выбранный альбом")
        btn_ok.setObjectName("ActionCapsule")
        btn_ok.clicked.connect(self.accept_selection)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

    def accept_selection(self) -> None:
        row = self.list_widget.currentRow()
        if 0 <= row < len(self.candidates):
            self.selected_candidate = self.candidates[row]
            self.keep_local_cover = self.chk_keep_cover.isChecked()
            self.accept()


class TrackDetailsDialog(QDialog):
    def __init__(self, track: TrackInfo, default_artist: str, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Редактировать теги трека — {track.title}")
        self.resize(460, 300)
        self.track = track

        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(10)

        self.ed_title = QLineEdit(track.title)
        self.ed_artist = QLineEdit(track.track_artist or default_artist)
        self.ed_isrc = QLineEdit(track.isrc)
        self.ed_composer = QLineEdit(track.composer)
        self.chk_explicit = QCheckBox("Explicit Content [E]")
        self.chk_explicit.setChecked(track.explicit)

        form.addRow("Название трека:", self.ed_title)
        form.addRow("Артист трека (ARTIST):", self.ed_artist)
        form.addRow("Код записи (ISRC):", self.ed_isrc)
        form.addRow("Композитор / Продюсер:", self.ed_composer)
        form.addRow("", self.chk_explicit)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        btn_save = QPushButton("Сохранить")
        btn_save.setObjectName("ActionCapsule")
        btn_save.clicked.connect(self._save)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_save)
        layout.addLayout(btn_row)

    def _save(self) -> None:
        self.track.title = self.ed_title.text().strip()
        self.track.track_artist = self.ed_artist.text().strip()
        self.track.isrc = self.ed_isrc.text().strip()
        self.track.composer = self.ed_composer.text().strip()
        self.track.explicit = self.chk_explicit.isChecked()
        self.accept()


class ManualLyricsSearchDialog(QDialog):
    def __init__(self, artist: str, title: str, duration_sec: int, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(f"Поиск текста на LRCLIB — {title}")
        self.resize(660, 440)
        self.selected_lyrics: str | None = None
        self.duration_sec = duration_sec

        layout = QVBoxLayout(self)
        search_row = QHBoxLayout()
        self.query_input = QLineEdit(f"{artist} {title}")
        btn_find = QPushButton("Искать")
        btn_find.setObjectName("ActionCapsule")
        btn_find.clicked.connect(self.perform_search)
        search_row.addWidget(self.query_input, 1)
        search_row.addWidget(btn_find)
        layout.addLayout(search_row)

        self.list_widget = QListWidget()
        self.list_widget.itemDoubleClicked.connect(self.accept_variant)
        layout.addWidget(self.list_widget, 1)

        btn_row = QHBoxLayout()
        btn_cancel = QPushButton("Отмена")
        btn_cancel.clicked.connect(self.reject)
        btn_ok = QPushButton("Применить текст")
        btn_ok.setObjectName("ActionCapsule")
        btn_ok.clicked.connect(self.accept_variant)
        btn_row.addStretch()
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

        self.variants: list[dict] = []
        self.perform_search()

    def perform_search(self) -> None:
        self.list_widget.clear()
        q = self.query_input.text().strip()
        if not q:
            return
        self.variants = search_lyrics_variants(q)
        if not self.variants:
            self.list_widget.addItem("Ничего не найдено.")
            return

        for v in self.variants:
            mins, secs = divmod(v["duration"], 60)
            diff = v["duration"] - self.duration_sec
            diff_str = f" ({diff:+d} сек)" if self.duration_sec else ""
            badge = "SYNCED" if v["has_synced"] else "PLAIN"
            item_text = (
                f"[{badge}]  {v['artist']} — {v['title']}  ({mins}:{secs:02d}{diff_str})\n"
                f"    Альбом: {v['album']}"
            )
            self.list_widget.addItem(QListWidgetItem(item_text))
        self.list_widget.setCurrentRow(0)

    def accept_variant(self) -> None:
        row = self.list_widget.currentRow()
        if 0 <= row < len(self.variants):
            self.selected_lyrics = self.variants[row]["lyrics"]
            self.accept()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("FLAC Studio")
        self.resize(1380, 860)
        self.setAcceptDrops(True)
        self.setStyleSheet(STUDIO_DARK_THEME)

        self.current_folder: Path | None = None
        self.scanned_albums: list[AlbumInfo] = []
        self.album_info: AlbumInfo | None = None
        self.backup_local_cover: bytes | None = None

        self.scan_worker: FolderScanWorker | None = None
        self.cand_worker: CandidatesSearchWorker | None = None
        self.cover_worker: CoverSearchWorker | None = None
        self.apply_worker: ApplyCandidateWorker | None = None
        self.lyrics_worker: LyricsOnlyWorker | None = None
        self.save_worker: TagWriteWorker | None = None

        self._build_menu_bar()
        self._build_ui()

        QTimer.singleShot(150, self._auto_restore_last_session)

    def _build_menu_bar(self) -> None:
        menubar = self.menuBar()

        file_menu = menubar.addMenu("Файл")
        act_import = QAction("Импортировать папку", self)
        act_import.setShortcut("Ctrl+O")
        act_import.triggered.connect(self.select_folder)
        file_menu.addAction(act_import)

        self.recent_menu = file_menu.addMenu("Недавние папки")
        self._rebuild_recent_folders_menu()

        file_menu.addSeparator()
        act_save_all = QAction("Записать теги во все файлы", self)
        act_save_all.setShortcut("Ctrl+S")
        act_save_all.triggered.connect(self.save_all_tags)
        file_menu.addAction(act_save_all)

        act_export_cover = QAction("Сохранить обложку на диск...", self)
        act_export_cover.triggered.connect(self.export_cover_to_disk)
        file_menu.addAction(act_export_cover)

        file_menu.addSeparator()
        act_exit = QAction("Выход", self)
        act_exit.setShortcut("Ctrl+Q")
        act_exit.triggered.connect(self.close)
        file_menu.addAction(act_exit)

        rel_menu = menubar.addMenu("Релиз и Тексты")
        act_top5 = QAction("База релизов...", self)
        act_top5.setShortcut("Ctrl+F")
        act_top5.triggered.connect(self.start_candidates_search)
        rel_menu.addAction(act_top5)

        act_cov_top5 = QAction("Выбрать обложку (Топ-5)...", self)
        act_cov_top5.triggered.connect(self.start_cover_top5_search)
        rel_menu.addAction(act_cov_top5)

        act_lrc = QAction("Найти только Synced Lyrics для всех треков", self)
        act_lrc.setShortcut("Ctrl+L")
        act_lrc.triggered.connect(self.start_lyrics_only_fetch)
        rel_menu.addAction(act_lrc)

        player_menu = menubar.addMenu("Плеер")
        act_play_pause = QAction("Воспроизведение / Пауза", self)
        act_play_pause.triggered.connect(lambda: self.lyrics_player.toggle_play())
        player_menu.addAction(act_play_pause)

        act_random = QAction("Включить случайный трек альбома", self)
        act_random.setShortcut("Ctrl+R")
        act_random.triggered.connect(self.select_random_track)
        player_menu.addAction(act_random)

        act_vocal = QAction("Слушать с первой строчки вокала", self)
        act_vocal.triggered.connect(lambda: self.lyrics_player.play_from_vocal())
        player_menu.addAction(act_vocal)

        act_full_lrc = QAction("Открыть окно полного текста (Караоке)", self)
        act_full_lrc.triggered.connect(lambda: self.lyrics_player.open_full_lyrics_window())
        player_menu.addAction(act_full_lrc)

        settings_menu = menubar.addMenu("Кэш и Настройки")
        self.act_auto_load = QAction("Автоматически открывать последнюю папку при запуске", self, checkable=True)
        self.act_auto_load.setChecked(app_cache.get_setting("auto_load_last_folder", True))
        self.act_auto_load.toggled.connect(lambda v: app_cache.set_setting("auto_load_last_folder", v))
        settings_menu.addAction(self.act_auto_load)

        self.act_auto_fft = QAction("Автопроверка спектра FFT при импорте", self, checkable=True)
        self.act_auto_fft.setChecked(app_cache.get_setting("auto_check_spectrum", True))
        self.act_auto_fft.toggled.connect(lambda v: app_cache.set_setting("auto_check_spectrum", v))
        settings_menu.addAction(self.act_auto_fft)

        settings_menu.addSeparator()
        act_rescan = QAction("Пересканировать текущую папку заново (без кэша)", self)
        act_rescan.setShortcut("F5")
        act_rescan.triggered.connect(self.force_rescan_current_folder)
        settings_menu.addAction(act_rescan)

        act_clear_cache = QAction("Очистить весь кэш программы", self)
        act_clear_cache.triggered.connect(self.clear_program_cache)
        settings_menu.addAction(act_clear_cache)

    def _rebuild_recent_folders_menu(self) -> None:
        self.recent_menu.clear()
        recents = app_cache.get_recent_folders()
        if not recents:
            empty_act = QAction("Нет недавних папок", self)
            empty_act.setEnabled(False)
            self.recent_menu.addAction(empty_act)
            return

        for folder in recents:
            act = QAction(str(folder), self)
            act.triggered.connect(lambda _checked=False, f=folder: self._set_working_folder(f))
            self.recent_menu.addAction(act)

    def _auto_restore_last_session(self) -> None:
        if app_cache.get_setting("auto_load_last_folder", True):
            last_folder = app_cache.get_last_folder()
            if last_folder:
                self._set_working_folder(last_folder)

    def force_rescan_current_folder(self) -> None:
        if self.current_folder and self.current_folder.exists():
            self._set_working_folder(self.current_folder, force_rescan=True)

    def clear_program_cache(self) -> None:
        app_cache.clear_all_cache()
        self.status_label.setText("Кэш программы успешно очищен.")

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(14, 10, 14, 10)
        main_layout.setSpacing(12)

        top_card = QFrame()
        top_card.setObjectName("SurfaceCard")
        top_bar = QHBoxLayout(top_card)
        top_bar.setContentsMargins(14, 9, 14, 9)
        top_bar.setSpacing(10)

        rel_badge = QLabel("РЕЛИЗ")
        rel_badge.setStyleSheet(
            "background-color: #1D1D25; color: #8E8E9C; font-size: 10px; "
            "font-weight: 800; padding: 5px 8px; border-radius: 6px; letter-spacing: 0.6px;"
        )
        self.album_selector = QComboBox()
        self.album_selector.setMinimumWidth(230)
        self.album_selector.activated.connect(self.on_album_switched)

        self.artist_input = LabeledInputCapsule("АРТИСТ")
        self.album_input = LabeledInputCapsule("АЛЬБОМ")

        self.btn_search_album = QPushButton("База релизов")
        self.btn_search_album.setObjectName("ActionCapsule")
        self.btn_search_album.clicked.connect(self.start_candidates_search)

        self.btn_lyrics_only = QPushButton("Найти Lyrics")
        self.btn_lyrics_only.clicked.connect(self.start_lyrics_only_fetch)

        top_bar.addWidget(rel_badge)
        top_bar.addWidget(self.album_selector)
        top_bar.addWidget(self.artist_input, 1)
        top_bar.addWidget(self.album_input, 1)
        top_bar.addWidget(self.btn_search_album)
        top_bar.addWidget(self.btn_lyrics_only)
        main_layout.addWidget(top_card)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        album_card = QFrame()
        album_card.setObjectName("SurfaceCard")
        album_layout = QVBoxLayout(album_card)
        album_layout.setContentsMargins(14, 14, 14, 14)
        album_layout.setSpacing(10)

        self.cover_widget = InteractiveCoverWidget(self)
        album_layout.addWidget(self.cover_widget, alignment=Qt.AlignmentFlag.AlignCenter)

        cover_btns = QHBoxLayout()
        cover_btns.setSpacing(6)
        self.btn_top5_covers = QPushButton("Топ-5 обложек")
        self.btn_top5_covers.setObjectName("ActionCapsule")
        self.btn_top5_covers.clicked.connect(self.start_cover_top5_search)
        btn_custom_cover = QPushButton("Своя")
        btn_custom_cover.clicked.connect(self.choose_custom_cover)
        btn_restore_cover = QPushButton("Исходная")
        btn_restore_cover.clicked.connect(self.restore_original_cover)
        cover_btns.addWidget(self.btn_top5_covers)
        cover_btns.addWidget(btn_custom_cover)
        cover_btns.addWidget(btn_restore_cover)
        album_layout.addLayout(cover_btns)

        form = QFormLayout()
        form.setSpacing(8)
        self.edit_artist = QLineEdit()
        self.edit_album = QLineEdit()
        self.edit_year = QLineEdit()
        self.edit_release_date = QLineEdit()
        self.edit_release_date.setPlaceholderText("ГГГГ-ММ-ДД")
        self.edit_genre = QComboBox()
        self.edit_genre.setEditable(True)
        self.edit_genre.addItems(STANDARD_GENRES_LIST)
        self.edit_discs = QLineEdit()
        self.chk_explicit = QCheckBox("Explicit Release [E]")

        form.addRow("Артист:", self.edit_artist)
        form.addRow("Альбом:", self.edit_album)
        form.addRow("Год:", self.edit_year)
        form.addRow("Дата:", self.edit_release_date)
        form.addRow("Жанр:", self.edit_genre)
        form.addRow("Дисков:", self.edit_discs)
        form.addRow("", self.chk_explicit)
        album_layout.addLayout(form)

        self.btn_save_all = QPushButton("Записать теги во все .flac")
        self.btn_save_all.setObjectName("ActionCapsule")
        self.btn_save_all.setEnabled(False)
        self.btn_save_all.setMinimumHeight(40)
        self.btn_save_all.clicked.connect(self.save_all_tags)
        album_layout.addWidget(self.btn_save_all)
        album_layout.addStretch()

        splitter.addWidget(album_card)

        right_splitter = QSplitter(Qt.Orientation.Vertical)

        self.table = QTableWidget(0, 7)
        self.table.setAlternatingRowColors(True)
        self.table.setHorizontalHeaderLabels([
            "Диск", "№", "Название трека", "Длит.", "Файл на диске", "Спектр / Параметры", "Synced Lyrics"
        ])
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.cellClicked.connect(self.on_track_selected)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self.show_track_context_menu)
        right_splitter.addWidget(self.table)

        self.lyrics_player = LyricsVerifierWidget()
        self.lyrics_player.prev_track_requested.connect(self.select_prev_track)
        self.lyrics_player.next_track_requested.connect(self.select_next_track)
        self.lyrics_player.random_track_requested.connect(self.select_random_track)
        right_splitter.addWidget(self.lyrics_player)
        right_splitter.setSizes([350, 420])

        splitter.addWidget(right_splitter)
        splitter.setSizes([295, 1055])
        main_layout.addWidget(splitter, 1)

        self.status_label = QLabel("Готов к работе. Нажми ПКМ по треку или обложке для дополнительных инструментов.")
        self.status_label.setStyleSheet(
            "background-color: #141418; color: #90909C; padding: 6px 14px; "
            "border-radius: 11px; border: 1px solid #22222A; font-size: 12px;"
        )
        main_layout.addWidget(self.status_label)

    def select_prev_track(self) -> None:
        if not self.album_info or not self.album_info.tracks:
            return
        if self.lyrics_player.shuffle_enabled and len(self.album_info.tracks) > 1:
            self.select_random_track()
            return
        row = max(0, self.table.currentRow() - 1)
        self.table.selectRow(row)
        self.lyrics_player.load_track(self.album_info.tracks[row], auto_play=True)

    def select_next_track(self) -> None:
        if not self.album_info or not self.album_info.tracks:
            return
        if self.lyrics_player.shuffle_enabled and len(self.album_info.tracks) > 1:
            self.select_random_track()
            return
        row = self.table.currentRow() + 1
        if row < len(self.album_info.tracks):
            self.table.selectRow(row)
            self.lyrics_player.load_track(self.album_info.tracks[row], auto_play=True)

    def select_random_track(self) -> None:
        if not self.album_info or not self.album_info.tracks:
            return
        total = len(self.album_info.tracks)
        curr = self.table.currentRow()
        choices = [i for i in range(total) if i != curr] or [0]
        row = random.choice(choices)
        self.table.selectRow(row)
        self.lyrics_player.load_track(self.album_info.tracks[row], auto_play=True)

    def start_cover_top5_search(self) -> None:
        artist = self.artist_input.text().strip() or (self.album_info.artist if self.album_info else "")
        album = self.album_input.text().strip() or (self.album_info.album if self.album_info else "")
        if not artist or not album:
            QMessageBox.warning(self, "Внимание", "Укажи артиста и альбом для поиска обложек.")
            return

        self.btn_top5_covers.setEnabled(False)
        self.cover_worker = CoverSearchWorker(artist, album)
        self.cover_worker.status_Signal.connect(self.status_label.setText)
        self.cover_worker.finished_Signal.connect(self._on_covers_found)
        self.cover_worker.error_Signal.connect(self._on_worker_error)
        self.cover_worker.start()

    def _on_covers_found(self, covers: list[dict]) -> None:
        self.btn_top5_covers.setEnabled(True)
        if not covers:
            QMessageBox.information(self, "Обложки", "Не удалось найти обложки для этого релиза.")
            return

        dlg = CoverCandidatesDialog(covers, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_cover_bytes and self.album_info:
            self.album_info.cover_bytes = dlg.selected_cover_bytes
            self._update_cover_preview()
            info = inspect_cover_bytes(dlg.selected_cover_bytes)
            self.status_label.setText(f"Установлена новая обложка: {info.get('badge', '')}")

    def show_cover_properties(self) -> None:
        if not self.album_info or not self.album_info.cover_bytes:
            QMessageBox.information(self, "Обложка", "Обложка ещё не загружена.")
            return
        info = inspect_cover_bytes(self.album_info.cover_bytes)
        msg = (
            f"Разрешение:  {info['width']} × {info['height']} пикс.\n"
            f"Пропорции:   {info['ratio']}\n"
            f"Формат:      {info['format']}\n"
            f"Глубина:     {info['depth']} бит\n"
            f"Размер:      {info['size_str']} ({info['size_bytes']:,} байт)"
        )
        QMessageBox.information(self, "Данные обложки", msg)

    def zoom_cover_dialog(self) -> None:
        if not self.album_info or not self.album_info.cover_bytes:
            return
        info = inspect_cover_bytes(self.album_info.cover_bytes)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Просмотр обложки — {info.get('badge', '')}")
        dlg.resize(680, 700)
        lay = QVBoxLayout(dlg)
        lbl = QLabel()
        lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        pix = QPixmap()
        pix.loadFromData(self.album_info.cover_bytes)
        lbl.setPixmap(
            pix.scaled(640, 640, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )
        lay.addWidget(lbl)
        dlg.exec()

    def copy_cover_to_clipboard(self) -> None:
        if not self.album_info or not self.album_info.cover_bytes:
            return
        pix = QPixmap()
        pix.loadFromData(self.album_info.cover_bytes)
        QGuiApplication.clipboard().setPixmap(pix)
        self.status_label.setText("Обложка скопирована в буфер обмена (Ctrl+V).")

    def export_cover_to_disk(self) -> None:
        if not self.album_info or not self.album_info.cover_bytes:
            return
        default_dir = str(self.album_info.folder_path or Path("."))
        save_path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить обложку", str(Path(default_dir) / "cover.jpg"), "JPEG (*.jpg);;PNG (*.png)"
        )
        if save_path:
            Path(save_path).write_bytes(self.album_info.cover_bytes)
            self.status_label.setText(f"Обложка сохранена: {save_path}")

    def show_track_context_menu(self, pos: QPoint) -> None:
        row = self.table.rowAt(pos.y())
        if not self.album_info or not (0 <= row < len(self.album_info.tracks)):
            return

        self.table.selectRow(row)
        track = self.album_info.tracks[row]
        self.lyrics_player.load_track(track)

        menu = QMenu(self)
        act_all_tags = menu.addAction("Просмотреть ВСЕ теги файла (Артист, Год, Жанр, Поток)...")
        menu.addSeparator()
        act_play = menu.addAction("Воспроизвести с начала")
        act_vocal = menu.addAction("Воспроизвести с вокала")
        act_rand = menu.addAction("Включить случайный трек альбома")
        menu.addSeparator()
        act_search_lrc = menu.addAction("Выбрать другой вариант Lyrics на LRCLIB...")
        act_edit_tags = menu.addAction("Редактировать теги трека (ISRC, Фит, Композитор)...")
        act_spec_graph = menu.addAction("Показать график спектра частот (FFT)...")
        menu.addSeparator()
        act_save_one = menu.addAction("Записать теги только в этот файл")
        act_clear_lrc = menu.addAction("Очистить текст у этого трека")
        act_explorer = menu.addAction("Показать файл в Проводнике Windows")

        chosen = menu.exec(self.table.viewport().mapToGlobal(pos))
        if chosen == act_all_tags:
            self._sync_album_fields_from_ui()
            AllFlacTagsDialog(track, self.album_info, self).exec()
        elif chosen == act_play:
            self.lyrics_player.play_from_start()
        elif chosen == act_vocal:
            self.lyrics_player.play_from_vocal()
        elif chosen == act_rand:
            self.select_random_track()
        elif chosen == act_search_lrc:
            self._context_search_track_lyrics(row, track)
        elif chosen == act_edit_tags:
            self._context_edit_track_details(row, track)
        elif chosen == act_spec_graph:
            SpectrumGraphDialog(track, self).exec()
        elif chosen == act_save_one:
            self._context_save_single_track(row, track)
        elif chosen == act_clear_lrc:
            track.synced_lyrics = None
            self._populate_table()
            self.table.selectRow(row)
            self.lyrics_player.load_track(track)
        elif chosen == act_explorer and track.file_path and track.file_path.exists():
            subprocess.Popen(["explorer", "/select,", str(track.file_path.resolve())])

    def _context_search_track_lyrics(self, row: int, track: TrackInfo) -> None:
        artist = self.edit_artist.text().strip() or (self.album_info.artist if self.album_info else "")
        dlg = ManualLyricsSearchDialog(artist, track.title, track.duration_sec, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_lyrics:
            track.synced_lyrics = dlg.selected_lyrics
            if track.file_path:
                app_cache.update_file_cache(track.file_path, synced_lyrics=dlg.selected_lyrics)
                app_cache.save()
            self._populate_table()
            self.table.selectRow(row)
            self.lyrics_player.load_track(track)

    def _context_edit_track_details(self, row: int, track: TrackInfo) -> None:
        artist = self.edit_artist.text().strip() or (self.album_info.artist if self.album_info else "")
        dlg = TrackDetailsDialog(track, artist, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._populate_table()
            self.table.selectRow(row)

    def _context_save_single_track(self, row: int, track: TrackInfo) -> None:
        if not self.album_info:
            return
        self.lyrics_player.player.stop()
        self.lyrics_player.player.setSource(QUrl())
        self._sync_album_fields_from_ui()
        title_item = self.table.item(row, 2)
        if title_item:
            track.title = title_item.text().strip()
        write_track_tags(self.album_info, track)
        self._populate_table()
        self.table.selectRow(row)
        self.lyrics_player.load_track(track)
        self.status_label.setText(f"Сохранено: {track.file_path.name}")

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        urls = event.mimeData().urls()
        if urls:
            dropped_path = Path(urls[0].toLocalFile())
            folder = dropped_path if dropped_path.is_dir() else dropped_path.parent
            self._set_working_folder(folder)

    def select_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Импортировать папку")
        if folder:
            self._set_working_folder(Path(folder))

    def _set_working_folder(self, folder: Path, force_rescan: bool = False) -> None:
        self.current_folder = folder
        self.scan_worker = FolderScanWorker(folder, force_rescan=force_rescan)
        self.scan_worker.status_Signal.connect(self.status_label.setText)
        self.scan_worker.finished_Signal.connect(self._on_local_folder_scanned)
        self.scan_worker.error_Signal.connect(self._on_worker_error)
        self.scan_worker.start()

    def _on_local_folder_scanned(self, albums: list[AlbumInfo]) -> None:
        self._rebuild_recent_folders_menu()
        self.scanned_albums = albums
        self.album_selector.clear()
        for alb in albums:
            self.album_selector.addItem(f"{alb.artist} — {alb.album} ({len(alb.tracks)} тр.)")

        if albums:
            self.album_selector.setCurrentIndex(0)
            self.backup_local_cover = albums[0].cover_bytes
            self._display_album(albums[0])

    def on_album_switched(self, idx: int) -> None:
        if 0 <= idx < len(self.scanned_albums):
            self.backup_local_cover = self.scanned_albums[idx].cover_bytes
            self._display_album(self.scanned_albums[idx])

    def start_candidates_search(self) -> None:
        artist = self.artist_input.text().strip()
        album = self.album_input.text().strip()
        if not artist or not album:
            QMessageBox.warning(self, "Внимание", "Укажи исполнителя и название альбома.")
            return

        expected_tracks = len(self.album_info.tracks) if self.album_info else 0
        self.btn_search_album.setEnabled(False)
        self.cand_worker = CandidatesSearchWorker(artist, album, expected_tracks)
        self.cand_worker.status_Signal.connect(self.status_label.setText)
        self.cand_worker.finished_Signal.connect(self._on_candidates_found)
        self.cand_worker.error_Signal.connect(self._on_worker_error)
        self.cand_worker.start()

    def _on_candidates_found(self, candidates: list[dict]) -> None:
        self.btn_search_album.setEnabled(True)
        if not candidates:
            ans = QMessageBox.question(
                self,
                "Релиз не найден",
                "В базах не нашлось альбомов с таким названием.\nНайти только Synced Lyrics для текущих треков?",
            )
            if ans == QMessageBox.StandardButton.Yes:
                self.start_lyrics_only_fetch()
            return

        has_local_cover = bool(self.album_info and self.album_info.cover_bytes)
        dlg = AlbumCandidateDialog(candidates, has_local_cover, self)
        if dlg.exec() == QDialog.DialogCode.Accepted and dlg.selected_candidate:
            self.btn_search_album.setEnabled(False)
            self.apply_worker = ApplyCandidateWorker(
                dlg.selected_candidate, self.album_info, dlg.keep_local_cover
            )
            self.apply_worker.status_Signal.connect(self.status_label.setText)
            self.apply_worker.finished_Signal.connect(self._on_remote_metadata_loaded)
            self.apply_worker.error_Signal.connect(self._on_worker_error)
            self.apply_worker.start()

    def start_lyrics_only_fetch(self) -> None:
        if not self.album_info:
            return
        self._sync_album_fields_from_ui()
        self.btn_lyrics_only.setEnabled(False)
        self.lyrics_worker = LyricsOnlyWorker(self.album_info)
        self.lyrics_worker.status_Signal.connect(self.status_label.setText)
        self.lyrics_worker.finished_Signal.connect(self._on_lyrics_only_loaded)
        self.lyrics_worker.error_Signal.connect(self._on_worker_error)
        self.lyrics_worker.start()

    def _on_lyrics_only_loaded(self, updated_album: AlbumInfo, _count: int) -> None:
        self.btn_lyrics_only.setEnabled(True)
        self._display_album(updated_album)

    def _on_remote_metadata_loaded(self, updated_album: AlbumInfo) -> None:
        self.btn_search_album.setEnabled(True)
        idx = self.album_selector.currentIndex()
        if 0 <= idx < len(self.scanned_albums):
            self.scanned_albums[idx] = updated_album
        self._display_album(updated_album)

    def choose_custom_cover(self) -> None:
        if not self.album_info:
            return
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Выбери картинку обложки", "", "Изображения (*.jpg *.jpeg *.png *.webp)"
        )
        if file_path:
            self.album_info.cover_bytes = Path(file_path).read_bytes()
            self._update_cover_preview()

    def restore_original_cover(self) -> None:
        if self.album_info and self.backup_local_cover:
            self.album_info.cover_bytes = self.backup_local_cover
            self._update_cover_preview()
            self.status_label.setText("Возвращена исходная обложка из локального файла.")

    def _update_cover_preview(self) -> None:
        self.cover_widget.set_cover_data(self.album_info.cover_bytes if self.album_info else None)

    def _display_album(self, album_info: AlbumInfo) -> None:
        self.album_info = album_info
        self.artist_input.setText(album_info.artist)
        self.album_input.setText(album_info.album)

        self.edit_artist.setText(album_info.artist)
        self.edit_album.setText(album_info.album)
        self.edit_year.setText(album_info.year)
        self.edit_release_date.setText(album_info.release_date)
        self.edit_genre.setCurrentText(album_info.genre)
        self.edit_discs.setText(str(album_info.disc_total))
        self.chk_explicit.setChecked(album_info.explicit)

        self._update_cover_preview()
        self._populate_table()
        self.btn_save_all.setEnabled(True)

    def _populate_table(self) -> None:
        if not self.album_info:
            return
        tracks = self.album_info.tracks
        self.table.setRowCount(len(tracks))

        for row, t in enumerate(tracks):
            mins, secs = divmod(t.duration_sec, 60)
            file_name = t.file_path.name if t.file_path else "Нет файла"
            lyr_status = "Synced LRC" if t.synced_lyrics else "Нет текста"
            exp_badge = " [E]" if (t.explicit or self.album_info.explicit) else ""

            item_disc = QTableWidgetItem(f"{t.disc_number}/{t.disc_total}")
            item_num = QTableWidgetItem(f"{t.track_number:02d}")
            item_title = QTableWidgetItem(f"{t.title}")
            item_dur = QTableWidgetItem(f"{mins}:{secs:02d}")
            item_file = QTableWidgetItem(f"{file_name}{exp_badge}")
            item_qual = QTableWidgetItem(t.quality_label)
            item_lyr = QTableWidgetItem(lyr_status)

            for it in (item_disc, item_num, item_dur, item_qual, item_lyr):
                it.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

            self.table.setItem(row, 0, item_disc)
            self.table.setItem(row, 1, item_num)
            self.table.setItem(row, 2, item_title)
            self.table.setItem(row, 3, item_dur)
            self.table.setItem(row, 4, item_file)
            self.table.setItem(row, 5, item_qual)
            self.table.setItem(row, 6, item_lyr)

        if tracks:
            self.table.selectRow(0)
            self.lyrics_player.load_track(tracks[0])

    def on_track_selected(self, row: int, _col: int) -> None:
        if self.album_info and 0 <= row < len(self.album_info.tracks):
            self.lyrics_player.load_track(self.album_info.tracks[row])

    def _sync_album_fields_from_ui(self) -> None:
        if not self.album_info:
            return
        self.album_info.artist = self.edit_artist.text().strip()
        self.album_info.album = self.edit_album.text().strip()
        self.album_info.year = self.edit_year.text().strip()
        self.album_info.release_date = self.edit_release_date.text().strip()
        self.album_info.genre = normalize_genre(self.edit_genre.currentText().strip())
        self.album_info.explicit = self.chk_explicit.isChecked()

        for row, track in enumerate(self.album_info.tracks):
            title_item = self.table.item(row, 2)
            if title_item:
                track.title = title_item.text().strip()

    def save_all_tags(self) -> None:
        if not self.album_info:
            return
        self.lyrics_player.player.stop()
        self.lyrics_player.player.setSource(QUrl())

        self._sync_album_fields_from_ui()
        self.btn_save_all.setEnabled(False)
        self.save_worker = TagWriteWorker(self.album_info)
        self.save_worker.status_Signal.connect(self.status_label.setText)
        self.save_worker.finished_Signal.connect(self._on_tags_saved)
        self.save_worker.error_Signal.connect(self._on_worker_error)
        self.save_worker.start()

    def _on_tags_saved(self, count: int) -> None:
        self.btn_save_all.setEnabled(True)
        self._populate_table()
        if self.album_info and self.album_info.tracks:
            self.lyrics_player.load_track(self.album_info.tracks[0])
        self.status_label.setText(f"Готово: обновлено и переименовано файлов .flac — {count} шт.")
        QMessageBox.information(
            self, "Готово", f"Записаны все теги, обложка и Synced Lyrics в {count} файл(ов)!"
        )

    def _on_worker_error(self, message: str) -> None:
        self.btn_search_album.setEnabled(True)
        self.btn_top5_covers.setEnabled(True)
        self.btn_lyrics_only.setEnabled(True)
        self.btn_save_all.setEnabled(True)
        self.status_label.setText(message)
        QMessageBox.critical(self, "Ошибка", message)