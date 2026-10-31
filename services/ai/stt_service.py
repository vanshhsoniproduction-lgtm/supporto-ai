import os
import logging
from pathlib import Path
from services.ai.model_manager import model_manager

logger = logging.getLogger(__name__)

def patch_pyav():
    """
    Patches PyAV (av) to prevent:
    TypeError: open() got an unexpected keyword argument 'metadata_errors'
    in faster-whisper when using PyAV >= 14.
    """
    try:
        import av
        if hasattr(av, "open") and not getattr(av, "_supporto_patched", False):
            _orig_open = av.open
            def _patched_open(*args, **kwargs):
                kwargs.pop("metadata_errors", None)
                return _orig_open(*args, **kwargs)
            av.open = _patched_open
            av._supporto_patched = True
    except Exception:
        pass

patch_pyav()

class STTService:
    """Service for local Speech-to-Text transcription using Whisper Small."""

    @staticmethod
    def transcribe_audio(audio_path: str | Path, language: str = "en") -> dict:
        patch_pyav()
        audio_file = Path(audio_path)
        if not audio_file.exists() or audio_file.stat().st_size == 0:
            return {
                "success": False,
                "text": "",
                "error": "Audio file does not exist or is empty.",
            }

        stt_model = model_manager.get_stt()
        if not stt_model:
            return {
                "success": False,
                "text": "",
                "error": "Whisper STT model or faster-whisper runtime is not loaded.",
            }

        try:
            segments, info = stt_model.transcribe(
                str(audio_file),
                beam_size=5,
                language=language if language != "auto" else None,
                vad_filter=True,
            )
            transcription = " ".join([segment.text.strip() for segment in segments]).strip()
            return {
                "success": True,
                "text": transcription,
                "language": info.language,
                "duration": info.duration,
            }
        except Exception as e:
            logger.error(f"Error during audio transcription: {e}")
            return {
                "success": False,
                "text": "",
                "error": str(e),
            }

stt_service = STTService()
