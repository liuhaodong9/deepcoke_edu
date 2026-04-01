from __future__ import annotations
from dataclasses import dataclass
import numpy as np
import torch

@dataclass
class VadEvent:
    event: str  # "speech_start" | "speech_end"
    time_s: float

class SileroVAD:
    """Streaming Silero VAD wrapper based on VADIterator.

    Requirements:
      - Prefer: `pip install silero-vad`
      - Fallback: torch.hub download (may require internet)
    """

    def __init__(self, sample_rate: int = 16000, threshold: float = 0.5):
        self.sample_rate = sample_rate
        self.threshold = threshold
        self._vad_iterator = None
        self._load()

    def _load(self):
        try:
            from silero_vad import load_silero_vad, VADIterator  # type: ignore
            model = load_silero_vad()
            self._vad_iterator = VADIterator(model, sampling_rate=self.sample_rate, threshold=self.threshold)
            return
        except Exception:
            pass

        # torch.hub fallback
        model, utils = torch.hub.load(
            repo_or_dir="snakers4/silero-vad",
            model="silero_vad",
            trust_repo=True,
        )
        (get_speech_timestamps,
         save_audio,
         read_audio,
         VADIterator,
         collect_chunks) = utils
        self._vad_iterator = VADIterator(model, sampling_rate=self.sample_rate, threshold=self.threshold)

    def reset(self):
        if self._vad_iterator is not None:
            self._vad_iterator.reset_states()

    def __call__(self, chunk_f32: np.ndarray) -> VadEvent | None:
        """Accept exactly 512 samples (32ms @ 16kHz) float32 in [-1,1]."""
        if chunk_f32.ndim != 1:
            chunk_f32 = chunk_f32.reshape(-1)
        if len(chunk_f32) != 512:
            # Silero requires fixed windows. Caller should enforce it.
            return None
        speech_dict = self._vad_iterator(chunk_f32, return_seconds=True)
        if not speech_dict:
            return None
        # Example: {'start': 0.96} or {'end': 2.24}
        if "start" in speech_dict:
            return VadEvent(event="speech_start", time_s=float(speech_dict["start"]))
        if "end" in speech_dict:
            return VadEvent(event="speech_end", time_s=float(speech_dict["end"]))
        return None
