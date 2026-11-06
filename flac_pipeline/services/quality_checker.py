from pathlib import Path
import numpy as np
import soundfile as sf
from mutagen.flac import FLAC


def inspect_flac_quality(flac_path: str | Path) -> dict:
    path = Path(flac_path)
    audio = FLAC(path)
    sample_rate = audio.info.sample_rate
    bits = audio.info.bits_per_sample
    specs_str = f"{bits}-bit / {sample_rate / 1000:.1f} kHz"

    try:
        data, sr = sf.read(path, dtype="float32")
        if data.ndim > 1:
            data = data[:, 0]

        mid = len(data) // 2
        slice_data = data[max(0, mid - sr * 10) : min(len(data), mid + sr * 10)]

        n_fft = 4096
        num_blocks = len(slice_data) // n_fft
        if num_blocks < 2:
            return {"is_authentic": True, "specs": specs_str, "label": f"OK ({specs_str})"}

        blocks = slice_data[: num_blocks * n_fft].reshape((num_blocks, n_fft))
        window = np.hanning(n_fft)
        spectra = np.abs(np.fft.rfft(blocks * window, axis=1))
        avg_db = 20 * np.log10(np.mean(spectra, axis=0) + 1e-12)
        freqs = np.fft.rfftfreq(n_fft, d=1.0 / sr)

        band_mid = avg_db[(freqs >= 14000) & (freqs <= 16000)].mean()
        band_high = avg_db[(freqs >= 20500) & (freqs <= 21800)].mean()
        drop_db = float(band_mid - band_high)

        is_authentic = drop_db < 36.0
        status = f"TRUE ({specs_str})" if is_authentic else f"FAKE? ({specs_str})"
        return {"is_authentic": is_authentic, "specs": specs_str, "label": status}
    except Exception:
        return {"is_authentic": True, "specs": specs_str, "label": specs_str}