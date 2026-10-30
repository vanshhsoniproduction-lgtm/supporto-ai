import uuid
import logging
from pathlib import Path
from django.conf import settings
from services.ai.model_manager import model_manager

logger = logging.getLogger(__name__)

class TTSService:
    """Service for local Text-to-Speech synthesis using Kokoro ONNX."""

    @staticmethod
    def generate_speech(text: str, voice: str = "af_sarah", speed: float = 1.0) -> dict:
        if not text or not text.strip():
            return {
                "success": False,
                "audio_url": "",
                "error": "Text is empty.",
            }

        tts_model = model_manager.get_tts()
        if not tts_model:
            return {
                "success": False,
                "audio_url": "",
                "error": "Kokoro TTS model or kokoro-onnx runtime is not loaded.",
            }

        try:
            import soundfile as sf
            clean_text = text.strip()[:1000] # Cap text length for browser response
            samples, sample_rate = tts_model.create(
                clean_text,
                voice=voice,
                speed=speed,
                lang="en-us"
            )

            filename = f"tts_{uuid.uuid4().hex[:12]}.wav"
            output_dir = Path(settings.MEDIA_ROOT) / "audio"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / filename

            sf.write(str(output_path), samples, sample_rate)

            return {
                "success": True,
                "audio_url": f"{settings.MEDIA_URL}audio/{filename}",
                "file_path": str(output_path),
                "duration_seconds": round(len(samples) / sample_rate, 2),
            }
        except Exception as e:
            logger.error(f"Error during TTS generation: {e}")
            return {
                "success": False,
                "audio_url": "",
                "error": str(e),
            }

tts_service = TTSService()

