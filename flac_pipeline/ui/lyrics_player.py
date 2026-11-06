from pathlib import Path
import numpy as np
import soundfile as sf
from PySide6.QtCore import (
    Qt, QUrl, Signal, QTimer, QVariantAnimation, QPropertyAnimation,
    QEasingCurve, QRectF, QPointF
)
from PySide6.QtGui import (
    QPainter, QColor, QFont, QPen, QPolygonF
)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton,
    QLabel, QSlider, QPlainTextEdit, QFrame, QListWidget,
    QListWidgetItem, QStackedWidget, QDialog
)
from models.album import TrackInfo
from services.cache_manager import app_cache
from services.lyrics_api import parse_lrc_lines, get_first_vocal_timestamp_ms, shift_lyrics_offset


def extract_fast_waveform(flac_path: Path, num_bars: int = 104) -> list[float]:
    cached = app_cache.get_file_cache(flac_path)
    if cached and cached.get("waveform") and len(cached["waveform"]) == num_bars:
        return cached["waveform"]

    try:
        info = sf.info(str(flac_path))
        total_frames = info.frames
        if total_frames <= 0:
            return [0.3] * num_bars

        step = max(1, total_frames // num_bars)
        read_len = min(4096, step)
        peaks: list[float] = []

        with sf.SoundFile(str(flac_path)) as f:
            for i in range(num_bars):
                pos = min(total_frames - read_len - 1, i * step)
                if pos > 0:
                    f.seek(pos)
                chunk = f.read(read_len, dtype="float32", always_2d=True)
                if len(chunk) > 0:
                    peak = float(np.percentile(np.abs(chunk[:, 0]), 90))
                    peaks.append(peak)
                else:
                    peaks.append(0.08)

        max_p = max(peaks) if peaks else 1.0
        if max_p < 1e-5:
            result = [0.25] * num_bars
        else:
            result = [round(max(0.18, min(1.0, (p / max_p) ** 0.75)), 3) for p in peaks]

        app_cache.update_file_cache(flac_path, waveform=result)
        return result
    except Exception:
        try:
            data, _sr = sf.read(str(flac_path), dtype="float32", always_2d=True)
            mono = np.abs(data[:, 0])
            splits = np.array_split(mono, num_bars)
            raw = [float(np.mean(s)) if len(s) else 0.1 for s in splits]
            m = max(raw) or 1.0
            result = [round(max(0.18, min(1.0, (x / m) ** 0.7)), 3) for x in raw]
            app_cache.update_file_cache(flac_path, waveform=result)
            return result
        except Exception:
            return [0.3] * num_bars


class StudioWaveformSeekBar(QWidget):
    seek_requested = Signal(int)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(80)
        self.setMouseTracking(True)
        self.peaks: list[float] = [0.25] * 104
        self.position_ms: float = 0.0
        self.duration_ms: int = 1
        self._dragging: bool = False

    def set_waveform(self, peaks: list[float]) -> None:
        self.peaks = peaks if peaks else [0.25] * 104
        self.update()

    def set_position(self, pos_ms: float) -> None:
        if not self._dragging:
            self.position_ms = float(pos_ms)
            self.update()

    def set_duration(self, dur_ms: int) -> None:
        self.duration_ms = max(1, dur_ms)
        self.update()

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() <= 48:
            self._dragging = True
            self._seek_from_x(event.position().x())

    def mouseMoveEvent(self, event) -> None:
        if self._dragging:
            self._seek_from_x(event.position().x())
        else:
            if event.position().y() <= 48:
                self.setCursor(Qt.CursorShape.PointingHandCursor)
            else:
                self.setCursor(Qt.CursorShape.ArrowCursor)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._dragging:
            self._dragging = False
            self._seek_from_x(event.position().x())

    def _seek_from_x(self, x: float) -> None:
        pad = 10.0
        usable_w = max(1.0, self.width() - pad * 2)
        ratio = max(0.0, min(1.0, (x - pad) / usable_w))
        target_ms = int(ratio * self.duration_ms)
        self.position_ms = float(target_ms)
        self.seek_requested.emit(target_ms)
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        w = float(self.width())
        n = len(self.peaks)
        if n == 0:
            return

        pad_x = 10.0
        usable_w = max(1.0, w - pad_x * 2)
        wave_top = 4.0
        wave_height = 38.0

        progress_ratio = max(0.0, min(1.0, self.position_ms / max(1, self.duration_ms)))
        playhead_x = pad_x + progress_ratio * usable_w

        bar_step = usable_w / n
        bar_width = max(2.4, bar_step * 0.56)

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#2C2C35"))
        for i, amp in enumerate(self.peaks):
            x = pad_x + i * bar_step + (bar_step - bar_width) / 2.0
            bar_h = max(5.0, amp * wave_height)
            y = wave_top + (wave_height - bar_h) / 2.0
            painter.drawRoundedRect(QRectF(x, y, bar_width, bar_h), bar_width / 2, bar_width / 2)

        painter.save()
        painter.setClipRect(QRectF(0, 0, playhead_x, wave_top + wave_height + 2))
        painter.setBrush(QColor("#ECECF2"))
        for i, amp in enumerate(self.peaks):
            x = pad_x + i * bar_step + (bar_step - bar_width) / 2.0
            bar_h = max(5.0, amp * wave_height)
            y = wave_top + (wave_height - bar_h) / 2.0
            painter.drawRoundedRect(QRectF(x, y, bar_width, bar_h), bar_width / 2, bar_width / 2)
        painter.restore()

        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor("#FFFFFF"))
        painter.drawRoundedRect(QRectF(playhead_x - 1.5, wave_top, 3.0, wave_height), 1.5, 1.5)

        pill_y = 57.0
        self._draw_time_pill(painter, pad_x, pill_y, self._fmt_time(int(self.position_ms)))
        self._draw_time_pill(painter, w - pad_x - 56.0, pill_y, self._fmt_time(self.duration_ms))

    def _draw_time_pill(self, painter: QPainter, x: float, y: float, text: str) -> None:
        rect = QRectF(x, y, 56, 20)
        painter.setBrush(QColor("#0D0D11"))
        painter.setPen(QPen(QColor("#262630"), 1))
        painter.drawRoundedRect(rect, 10, 10)
        painter.setPen(QColor("#D8D8E2"))
        painter.setFont(QFont("Segoe UI", 8, QFont.Weight.Bold))
        painter.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)

    @staticmethod
    def _fmt_time(ms: int) -> str:
        mins, rem = divmod(max(0, ms), 60000)
        secs = rem // 1000
        return f"{mins}:{secs:02d}"


class SmoothLyricsBanner(QWidget):
    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedHeight(92)
        self.prev_text = ""
        self.curr_text = "Импортируй альбом и выбери трек"
        self.next_text = ""
        self.slide_progress: float = 1.0

        self.anim = QVariantAnimation(self)
        self.anim.setDuration(330)
        self.anim.setStartValue(0.0)
        self.anim.setEndValue(1.0)
        self.anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self.anim.valueChanged.connect(self._on_anim_frame)

    def _on_anim_frame(self, val: float) -> None:
        self.slide_progress = float(val)
        self.update()

    def set_lines(self, prev_line: str, curr_line: str, next_line: str, animate: bool = True) -> None:
        if curr_line == self.curr_text and prev_line == self.prev_text and next_line == self.next_text:
            return
        self.prev_text = prev_line
        self.curr_text = curr_line
        self.next_text = next_line

        if animate:
            self.anim.stop()
            self.slide_progress = 0.0
            self.anim.start()
        else:
            self.slide_progress = 1.0
            self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)

        w = self.width()
        h = self.height()

        bg_rect = QRectF(1, 1, w - 2, h - 2)
        painter.setBrush(QColor("#0D0D10"))
        painter.setPen(QPen(QColor("#222228"), 1))
        painter.drawRoundedRect(bg_rect, 14, 14)

        p = self.slide_progress
        slide_offset = (1.0 - p) * 24.0

        if self.prev_text:
            alpha_prev = int(60 + 110 * p)
            painter.setPen(QColor(138, 138, 148, alpha_prev))
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
            painter.drawText(QRectF(16, 8 + slide_offset * 0.6, w - 32, 22), Qt.AlignmentFlag.AlignCenter, self.prev_text)

        bright = int(145 + 110 * p)
        painter.setPen(QColor(bright, bright, min(255, bright + 5)))
        painter.setFont(QFont("Segoe UI", 13, QFont.Weight.Bold))
        painter.drawText(QRectF(16, 33 + slide_offset, w - 32, 26), Qt.AlignmentFlag.AlignCenter, self.curr_text)

        if self.next_text:
            alpha_next = int(155 * p)
            painter.setPen(QColor(125, 125, 135, alpha_next))
            painter.setFont(QFont("Segoe UI", 10, QFont.Weight.Normal))
            painter.drawText(QRectF(16, 62 + slide_offset * 1.1, w - 32, 22), Qt.AlignmentFlag.AlignCenter, self.next_text)


class RoundTransportButton(QPushButton):
    def __init__(self, icon_kind: str, diameter: int = 44, parent: QWidget | None = None):
        super().__init__(parent)
        self.icon_kind = icon_kind
        self.setFixedSize(diameter, diameter)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._hovered = False
        self.is_active_mode = False

    def set_icon_kind(self, kind: str) -> None:
        self.icon_kind = kind
        self.update()

    def set_active_mode(self, active: bool) -> None:
        self.is_active_mode = active
        self.update()

    def enterEvent(self, event) -> None:
        self._hovered = True
        self.update()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._hovered = False
        self.update()
        super().leaveEvent(event)

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        d = self.width()
        if self.is_active_mode:
            bg = QColor("#282834")
            border = QColor("#E2E2EC")
        else:
            bg = QColor("#1C1C22") if self._hovered else QColor("#09090C")
            border = QColor("#3E3E4A") if self._hovered else QColor("#26262E")

        painter.setBrush(bg)
        painter.setPen(QPen(border, 1.5))
        painter.drawEllipse(QRectF(1.5, 1.5, d - 3, d - 3))

        fg_color = QColor("#FFFFFF") if self.is_active_mode else QColor("#F2F2F7")
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(fg_color)
        cx, cy = d / 2.0, d / 2.0

        if self.icon_kind == "play":
            poly = QPolygonF([
                QPointF(cx - 5, cy - 8),
                QPointF(cx - 5, cy + 8),
                QPointF(cx + 8, cy),
            ])
            painter.drawPolygon(poly)
        elif self.icon_kind == "pause":
            painter.drawRoundedRect(QRectF(cx - 7, cy - 8, 4.5, 16), 1.5, 1.5)
            painter.drawRoundedRect(QRectF(cx + 2.5, cy - 8, 4.5, 16), 1.5, 1.5)
        elif self.icon_kind == "prev":
            painter.drawRoundedRect(QRectF(cx - 8, cy - 6, 2.2, 12), 1, 1)
            poly = QPolygonF([
                QPointF(cx + 6, cy - 6),
                QPointF(cx + 6, cy + 6),
                QPointF(cx - 4, cy),
            ])
            painter.drawPolygon(poly)
        elif self.icon_kind == "next":
            painter.drawRoundedRect(QRectF(cx + 5.8, cy - 6, 2.2, 12), 1, 1)
            poly = QPolygonF([
                QPointF(cx - 6, cy - 6),
                QPointF(cx - 6, cy + 6),
                QPointF(cx + 4, cy),
            ])
            painter.drawPolygon(poly)
        elif self.icon_kind == "shuffle":
            pen = QPen(fg_color, 1.8)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            painter.setPen(pen)
            painter.drawLine(QPointF(cx - 7, cy - 4), QPointF(cx + 5, cy + 4))
            painter.drawLine(QPointF(cx - 7, cy + 4), QPointF(cx + 5, cy - 4))
            painter.drawLine(QPointF(cx + 3, cy - 6), QPointF(cx + 7, cy - 4))
            painter.drawLine(QPointF(cx + 3, cy - 2), QPointF(cx + 7, cy - 4))
            painter.drawLine(QPointF(cx + 3, cy + 2), QPointF(cx + 7, cy + 4))
            painter.drawLine(QPointF(cx + 3, cy + 6), QPointF(cx + 7, cy + 4))


class FullLyricsDialog(QDialog):
    def __init__(self, parent_player: "LyricsVerifierWidget"):
        super().__init__(parent_player)
        self.parent_player = parent_player
        self.setWindowTitle("Полный синхронизированный текст")
        self.resize(640, 680)

        layout = QVBoxLayout(self)
        self.header_lbl = QLabel("Полный текст (двойной клик по строке — перемотка)")
        self.header_lbl.setStyleSheet("color: #D0D0D8; font-size: 14px; font-weight: bold; padding: 4px;")
        layout.addWidget(self.header_lbl)

        self.list_widget = QListWidget()
        self.list_widget.setWordWrap(True)
        self.list_widget.setSpacing(4)
        self.list_widget.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.list_widget.setStyleSheet(
            "QListWidget { background-color: #0B0B0E; border: 1px solid #24242C; border-radius: 14px; padding: 12px; }"
            "QListWidget::item { padding: 7px 10px; border-radius: 8px; }"
            "QListWidget::item:selected { background-color: transparent; }"
        )
        self.list_widget.itemDoubleClicked.connect(self._on_item_double_clicked)
        layout.addWidget(self.list_widget, 1)

        self.scroll_anim = QPropertyAnimation(self.list_widget.verticalScrollBar(), b"value", self)
        self.scroll_anim.setDuration(300)
        self.scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        btn_close = QPushButton("Закрыть")
        btn_close.clicked.connect(self.close)
        layout.addWidget(btn_close, alignment=Qt.AlignmentFlag.AlignRight)

        self.rebuild_list()

    def rebuild_list(self) -> None:
        self.list_widget.clear()
        track = self.parent_player.current_track
        if track:
            self.header_lbl.setText(f"{track.title} — Полный текст")

        for ts_ms, text in self.parent_player.parsed_lines:
            mins, rem = divmod(ts_ms, 60000)
            secs = rem // 1000
            item = QListWidgetItem(f"[{mins:02d}:{secs:02d}]   {text if text else '...'}")
            item.setData(Qt.ItemDataRole.UserRole, ts_ms)
            item.setForeground(QColor("#5E5E68"))
            self.list_widget.addItem(item)

    def highlight_index(self, active_idx: int) -> None:
        font_normal = QFont("Segoe UI", 12, QFont.Weight.Normal)
        font_active = QFont("Segoe UI", 14, QFont.Weight.Bold)

        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if i == active_idx:
                item.setForeground(QColor("#FFFFFF"))
                item.setBackground(QColor("#1E1E26"))
                item.setFont(font_active)
                rect = self.list_widget.visualItemRect(item)
                target = (
                    self.list_widget.verticalScrollBar().value()
                    + rect.center().y()
                    - self.list_widget.viewport().height() // 2
                )
                self.scroll_anim.stop()
                self.scroll_anim.setEndValue(max(0, target))
                self.scroll_anim.start()
            else:
                item.setForeground(QColor("#5E5E68"))
                item.setBackground(QColor(0, 0, 0, 0))
                item.setFont(font_normal)

    def _on_item_double_clicked(self, item: QListWidgetItem) -> None:
        ts_ms = item.data(Qt.ItemDataRole.UserRole)
        if ts_ms is not None:
            self.parent_player.player.setPosition(int(ts_ms))
            self.parent_player.player.play()


class LyricsVerifierWidget(QFrame):
    prev_track_requested = Signal()
    next_track_requested = Signal()
    random_track_requested = Signal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setObjectName("PlayerCard")
        self.current_track: TrackInfo | None = None
        self.parsed_lines: list[tuple[int, str]] = []
        self.active_line_idx: int = -1
        self.full_lyrics_dialog: FullLyricsDialog | None = None
        self.shuffle_enabled: bool = app_cache.get_shuffle()

        self.player = QMediaPlayer(self)
        self.audio_output = QAudioOutput(self)
        self.player.setAudioOutput(self.audio_output)

        saved_vol = app_cache.get_volume()
        self.audio_output.setVolume(saved_vol / 100.0)

        self.smooth_timer = QTimer(self)
        self.smooth_timer.setInterval(16)
        self.smooth_timer.timeout.connect(self._on_smooth_tick)

        self._build_ui(saved_vol)
        self.player.positionChanged.connect(self._on_position_changed)
        self.player.durationChanged.connect(self.waveform.set_duration)
        self.player.playbackStateChanged.connect(self._on_state_changed)
        self.player.mediaStatusChanged.connect(self._on_media_status_changed)

    def _build_ui(self, initial_vol: int) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(10)

        self.smooth_banner = SmoothLyricsBanner()
        layout.addWidget(self.smooth_banner)

        self.waveform = StudioWaveformSeekBar()
        self.waveform.seek_requested.connect(self.player.setPosition)
        layout.addWidget(self.waveform)

        ctrl_row = QHBoxLayout()
        ctrl_row.setSpacing(8)

        self.btn_prev = RoundTransportButton("prev", 38)
        self.btn_prev.setToolTip("Предыдущий трек")
        self.btn_prev.clicked.connect(self.prev_track_requested.emit)

        self.btn_play_pause = RoundTransportButton("play", 48)
        self.btn_play_pause.setToolTip("Воспроизведение / Пауза")
        self.btn_play_pause.clicked.connect(self.toggle_play)

        self.btn_next = RoundTransportButton("next", 38)
        self.btn_next.setToolTip("Следующий трек")
        self.btn_next.clicked.connect(self.next_track_requested.emit)

        self.btn_shuffle_mode = RoundTransportButton("shuffle", 38)
        self.btn_shuffle_mode.setToolTip("Режим перемешивания треков альбома (Shuffle)")
        self.btn_shuffle_mode.set_active_mode(self.shuffle_enabled)
        self.btn_shuffle_mode.clicked.connect(self.toggle_shuffle_mode)

        self.btn_random_now = QPushButton("Случайный трек")
        self.btn_random_now.setToolTip("Сразу включить случайный трек из альбома")
        self.btn_random_now.clicked.connect(self.random_track_requested.emit)

        self.btn_vocal = QPushButton("С вокала")
        self.btn_vocal.clicked.connect(self.play_from_vocal)

        self.btn_full_window = QPushButton("Полный текст")
        self.btn_full_window.clicked.connect(self.open_full_lyrics_window)

        self.btn_toggle_edit = QPushButton("Редактор LRC")
        self.btn_toggle_edit.setCheckable(True)
        self.btn_toggle_edit.toggled.connect(self._toggle_edit_mode)

        self.lbl_vol = QLabel(f"Громк. {initial_vol}%")
        self.lbl_vol.setStyleSheet("color: #787882; font-size: 11px; min-width: 62px;")
        self.vol_slider = QSlider(Qt.Orientation.Horizontal)
        self.vol_slider.setFixedWidth(80)
        self.vol_slider.setRange(0, 100)
        self.vol_slider.setValue(initial_vol)
        self.vol_slider.valueChanged.connect(self._on_volume_changed)

        btn_m500 = QPushButton("-500 мс")
        btn_m100 = QPushButton("-100 мс")
        btn_p100 = QPushButton("+100 мс")
        btn_p500 = QPushButton("+500 мс")
        btn_m500.clicked.connect(lambda: self.apply_offset(-500))
        btn_m100.clicked.connect(lambda: self.apply_offset(-100))
        btn_p100.clicked.connect(lambda: self.apply_offset(100))
        btn_p500.clicked.connect(lambda: self.apply_offset(500))

        ctrl_row.addWidget(self.btn_prev)
        ctrl_row.addWidget(self.btn_play_pause)
        ctrl_row.addWidget(self.btn_next)
        ctrl_row.addWidget(self.btn_shuffle_mode)
        ctrl_row.addSpacing(4)
        ctrl_row.addWidget(self.btn_random_now)
        ctrl_row.addWidget(self.btn_vocal)
        ctrl_row.addWidget(self.btn_full_window)
        ctrl_row.addWidget(self.btn_toggle_edit)
        ctrl_row.addSpacing(6)
        ctrl_row.addWidget(self.lbl_vol)
        ctrl_row.addWidget(self.vol_slider)
        ctrl_row.addStretch()
        lbl_shift = QLabel("Сдвиг:")
        lbl_shift.setStyleSheet("color: #787882; font-size: 12px;")
        ctrl_row.addWidget(lbl_shift)
        ctrl_row.addWidget(btn_m500)
        ctrl_row.addWidget(btn_m100)
        ctrl_row.addWidget(btn_p100)
        ctrl_row.addWidget(btn_p500)
        layout.addLayout(ctrl_row)

        self.stack = QStackedWidget()

        self.karaoke_list = QListWidget()
        self.karaoke_list.setVerticalScrollMode(QListWidget.ScrollMode.ScrollPerPixel)
        self.karaoke_list.setStyleSheet(
            "QListWidget { background-color: #0D0D10; border: 1px solid #222228; border-radius: 12px; padding: 6px; }"
            "QListWidget::item { padding: 5px 10px; border-radius: 6px; }"
            "QListWidget::item:selected { background-color: transparent; }"
        )
        self.karaoke_list.itemDoubleClicked.connect(self._on_karaoke_line_clicked)

        self.list_scroll_anim = QPropertyAnimation(self.karaoke_list.verticalScrollBar(), b"value", self)
        self.list_scroll_anim.setDuration(280)
        self.list_scroll_anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        self.lyrics_edit = QPlainTextEdit()
        self.lyrics_edit.setPlaceholderText("[00:12.40] Текст песни с таймкодами...")
        self.lyrics_edit.textChanged.connect(self._on_text_edited)

        self.stack.addWidget(self.karaoke_list)
        self.stack.addWidget(self.lyrics_edit)
        layout.addWidget(self.stack, 1)

    def _on_volume_changed(self, val: int) -> None:
        self.audio_output.setVolume(val / 100.0)
        self.lbl_vol.setText(f"Громк. {val}%")
        app_cache.set_volume(val)

    def toggle_shuffle_mode(self) -> None:
        self.shuffle_enabled = not self.shuffle_enabled
        self.btn_shuffle_mode.set_active_mode(self.shuffle_enabled)
        app_cache.set_shuffle(self.shuffle_enabled)

    def _on_smooth_tick(self) -> None:
        pos_ms = self.player.position()
        self.waveform.set_position(pos_ms)
        self._update_karaoke_for_position(pos_ms)

    def _toggle_edit_mode(self, checked: bool) -> None:
        self.stack.setCurrentIndex(1 if checked else 0)
        self.btn_toggle_edit.setText("Режим караоке" if checked else "Редактор LRC")

    def open_full_lyrics_window(self) -> None:
        if self.full_lyrics_dialog is None or not self.full_lyrics_dialog.isVisible():
            self.full_lyrics_dialog = FullLyricsDialog(self)
            self.full_lyrics_dialog.show()
            self.full_lyrics_dialog.highlight_index(self.active_line_idx)
        else:
            self.full_lyrics_dialog.raise_()
            self.full_lyrics_dialog.activateWindow()

    def load_track(self, track: TrackInfo, auto_play: bool = False) -> None:
        was_playing = (
            self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        ) or auto_play
        self.player.stop()
        self.current_track = track
        self.active_line_idx = -1

        self.lyrics_edit.blockSignals(True)
        self.lyrics_edit.setPlainText(track.synced_lyrics or "")
        self.lyrics_edit.blockSignals(False)
        self._rebuild_parsed_lines(track.synced_lyrics or "")

        if track.file_path and track.file_path.exists():
            self.player.setSource(QUrl.fromLocalFile(str(track.file_path)))
            self.waveform.set_duration(track.duration_sec * 1000)
            self.waveform.set_position(0)
            self.waveform.set_waveform(extract_fast_waveform(track.file_path))
            first_next = self.parsed_lines[0][1] if self.parsed_lines else "Синхронный текст не привязан"
            self.smooth_banner.set_lines("", track.title, first_next, animate=False)
            if was_playing:
                self.player.play()
        else:
            self.player.setSource(QUrl())
            self.smooth_banner.set_lines("", "Файл не найден", "", animate=False)

    def toggle_play(self) -> None:
        if not self.current_track or not self.current_track.file_path:
            return
        if self.player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.player.pause()
        else:
            self.player.play()

    def play_from_start(self) -> None:
        if not self.current_track or not self.current_track.file_path:
            return
        self.player.setPosition(0)
        self.player.play()

    def play_from_vocal(self) -> None:
        if not self.current_track or not self.current_track.file_path:
            return
        vocal_ms = get_first_vocal_timestamp_ms(self.current_track.synced_lyrics or "")
        self.player.setPosition(max(0, vocal_ms - 1000))
        self.player.play()

    def _on_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        is_playing = state == QMediaPlayer.PlaybackState.PlayingState
        self.btn_play_pause.set_icon_kind("pause" if is_playing else "play")
        if is_playing:
            self.smooth_timer.start()
        else:
            self.smooth_timer.stop()

    def _on_media_status_changed(self, status: QMediaPlayer.MediaStatus) -> None:
        if status == QMediaPlayer.MediaStatus.EndOfMedia:
            if self.shuffle_enabled:
                self.random_track_requested.emit()
            else:
                self.next_track_requested.emit()

    def apply_offset(self, offset_ms: int) -> None:
        if not self.current_track or not self.current_track.synced_lyrics:
            return
        shifted = shift_lyrics_offset(self.current_track.synced_lyrics, offset_ms)
        self.current_track.synced_lyrics = shifted
        if self.current_track.file_path:
            app_cache.update_file_cache(self.current_track.file_path, synced_lyrics=shifted)
            app_cache.save()
        self.lyrics_edit.setPlainText(shifted)

    def _on_text_edited(self) -> None:
        if self.current_track:
            text = self.lyrics_edit.toPlainText().strip()
            self.current_track.synced_lyrics = text if text else None
            self._rebuild_parsed_lines(text)

    def _rebuild_parsed_lines(self, raw_lrc: str) -> None:
        self.parsed_lines = parse_lrc_lines(raw_lrc)
        self.karaoke_list.clear()

        for ts_ms, text in self.parsed_lines:
            mins, rem = divmod(ts_ms, 60000)
            secs = rem // 1000
            csecs = (rem % 1000) // 10
            item = QListWidgetItem(f"[{mins:02d}:{secs:02d}.{csecs:02d}]   {text if text else '...'}")
            item.setData(Qt.ItemDataRole.UserRole, ts_ms)
            item.setForeground(QColor("#5E5E68"))
            self.karaoke_list.addItem(item)

        if self.full_lyrics_dialog and self.full_lyrics_dialog.isVisible():
            self.full_lyrics_dialog.rebuild_list()

    def _on_karaoke_line_clicked(self, item: QListWidgetItem) -> None:
        ts_ms = item.data(Qt.ItemDataRole.UserRole)
        if ts_ms is not None:
            self.player.setPosition(int(ts_ms))
            self.player.play()

    def _on_position_changed(self, pos_ms: int) -> None:
        self.waveform.set_position(pos_ms)
        self._update_karaoke_for_position(pos_ms)

    def _update_karaoke_for_position(self, pos_ms: int) -> None:
        if not self.parsed_lines:
            return

        curr_idx = -1
        for i, (ts_ms, _text) in enumerate(self.parsed_lines):
            if pos_ms >= ts_ms:
                curr_idx = i
            else:
                break

        if curr_idx == self.active_line_idx:
            return
        self.active_line_idx = curr_idx

        prev_str = self.parsed_lines[curr_idx - 1][1] if curr_idx > 0 else ""
        curr_str = (
            self.parsed_lines[curr_idx][1]
            if curr_idx >= 0
            else "(Инструментальное вступление)"
        )
        next_str = (
            self.parsed_lines[curr_idx + 1][1]
            if (curr_idx + 1) < len(self.parsed_lines)
            else ""
        )

        self.smooth_banner.set_lines(prev_str, curr_str or "...", next_str, animate=True)

        font_gray = QFont("Segoe UI", 10, QFont.Weight.Normal)
        font_active = QFont("Segoe UI", 11, QFont.Weight.Bold)

        for i in range(self.karaoke_list.count()):
            item = self.karaoke_list.item(i)
            if i == curr_idx:
                item.setForeground(QColor("#FFFFFF"))
                item.setBackground(QColor("#1E1E26"))
                item.setFont(font_active)
                rect = self.karaoke_list.visualItemRect(item)
                target_scroll = (
                    self.karaoke_list.verticalScrollBar().value()
                    + rect.center().y()
                    - self.karaoke_list.viewport().height() // 2
                )
                self.list_scroll_anim.stop()
                self.list_scroll_anim.setEndValue(max(0, target_scroll))
                self.list_scroll_anim.start()
            else:
                item.setForeground(QColor("#5E5E68"))
                item.setBackground(QColor(0, 0, 0, 0))
                item.setFont(font_gray)

        if self.full_lyrics_dialog and self.full_lyrics_dialog.isVisible():
            self.full_lyrics_dialog.highlight_index(curr_idx)