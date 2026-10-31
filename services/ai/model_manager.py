import os
import logging
from pathlib import Path
from django.conf import settings

logger = logging.getLogger(__name__)

class ModelManager:
    """
    Centralized singleton manager for local AI models (LLM, Whisper STT, Kokoro TTS).
    Features lazy-loading, memory conservation for 16 GB Apple Silicon Mac,
    and granular health reporting matching strict hackathon status states:
    - NOT CONFIGURED
    - FILE MISSING
    - RUNTIME MISSING
    - NOT INITIALIZED
    - INITIALIZING
    - ONLINE
    - INFERENCE FAILED
    - FALLBACK ACTIVE
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if getattr(self, "_initialized", False):
            return
        self._llm = None
        self._stt = None
        self._tts = None
        self._llm_status = None
        self._stt_status = None
        self._tts_status = None
        self._initialized = True

    @property
    def llm_path(self) -> Path:
        return Path(settings.MODEL_LLM_PATH)

    @property
    def stt_path(self) -> Path:
        return Path(settings.MODEL_STT_PATH)

    @property
    def tts_path(self) -> Path:
        return Path(settings.MODEL_TTS_PATH)

    def get_health_status(self) -> dict:
        """Inspects disk paths, dependencies, and loaded states without forcing initialization."""
        if not getattr(settings, "AI_ENABLED", True):
            return {
                "ai_enabled": False,
                "llm": {"name": "Qwen 3 8B (Q4_K_M)", "path": str(self.llm_path), "file_exists": False, "file_size_gb": 0, "runtime_installed": False, "loaded": False, "status": "NOT CONFIGURED"},
                "stt": {"name": "Whisper Small", "path": str(self.stt_path), "dir_exists": False, "runtime_installed": False, "loaded": False, "status": "NOT CONFIGURED"},
                "tts": {"name": "Kokoro TTS", "path": str(self.tts_path), "dir_exists": False, "runtime_installed": False, "loaded": False, "status": "NOT CONFIGURED"}
            }

        llm_exists = self.llm_path.exists() and self.llm_path.is_file()
        stt_exists = self.stt_path.exists() and self.stt_path.is_dir()
        tts_exists = self.tts_path.exists() and self.tts_path.is_dir()

        llama_cpp_installed = False
        try:
            import llama_cpp # noqa
            llama_cpp_installed = True
        except ImportError:
            pass

        whisper_installed = False
        try:
            import faster_whisper # noqa
            whisper_installed = True
        except ImportError:
            pass

        kokoro_installed = False
        try:
            import kokoro_onnx # noqa
            kokoro_installed = True
        except ImportError:
            pass

        # Determine LLM status
        if not llm_exists:
            llm_status = "FILE MISSING"
        elif not llama_cpp_installed:
            llm_status = "RUNTIME MISSING"
        elif self._llm is not None:
            llm_status = "ONLINE"
        else:
            llm_status = "NOT INITIALIZED"

        # Determine STT status
        if not stt_exists:
            stt_status = "FILE MISSING"
        elif not whisper_installed:
            stt_status = "RUNTIME MISSING"
        elif self._stt is not None:
            stt_status = "ONLINE"
        else:
            stt_status = "NOT INITIALIZED"

        # Determine TTS status
        if not tts_exists:
            tts_status = "FILE MISSING"
        elif not kokoro_installed:
            tts_status = "RUNTIME MISSING"
        elif self._tts is not None:
            tts_status = "ONLINE"
        else:
            tts_status = "NOT INITIALIZED"

        return {
            "ai_enabled": settings.AI_ENABLED,
            "llm": {
                "name": "Qwen 3 8B (Q4_K_M)",
                "path": str(self.llm_path),
                "file_exists": llm_exists,
                "file_size_gb": round(self.llm_path.stat().st_size / (1024**3), 2) if llm_exists else 0,
                "runtime_installed": llama_cpp_installed,
                "loaded": self._llm is not None,
                "status": llm_status,
                "fallback_mode": "FALLBACK ACTIVE" if llm_status != "ONLINE" else "DIRECT"
            },
            "stt": {
                "name": "Whisper Small",
                "path": str(self.stt_path),
                "dir_exists": stt_exists,
                "runtime_installed": whisper_installed,
                "loaded": self._stt is not None,
                "status": stt_status,
                "fallback_mode": "FALLBACK ACTIVE" if stt_status != "ONLINE" else "DIRECT"
            },
            "tts": {
                "name": "Kokoro TTS",
                "path": str(self.tts_path),
                "dir_exists": tts_exists,
                "runtime_installed": kokoro_installed,
                "loaded": self._tts is not None,
                "status": tts_status,
                "fallback_mode": "FALLBACK ACTIVE" if tts_status != "ONLINE" else "DIRECT"
            }
        }

    @property
    def llm_context_window(self) -> int:
        return getattr(settings, "LLM_CONTEXT_WINDOW", 4096)

    def get_llm(self):
        """Lazy loader for Qwen LLM using llama-cpp-python if available."""
        if not getattr(settings, "AI_ENABLED", True):
            return None
        if self._llm is not None:
            return self._llm

        if not self.llm_path.exists():
            logger.warning(f"LLM model file not found at {self.llm_path}")
            return None

        try:
            from llama_cpp import Llama
            cpu_threads = min(os.cpu_count() or 4, 8)
            n_ctx = self.llm_context_window
            logger.info(f"Loading Qwen LLM from {self.llm_path} (n_ctx={n_ctx}, n_batch=512, n_gpu_layers=-1, n_threads={cpu_threads})...")
            self._llm = Llama(
                model_path=str(self.llm_path),
                n_ctx=n_ctx,
                n_batch=512,
                n_gpu_layers=-1,  # Offloads layers to Apple Silicon Metal GPU or CUDA
                n_threads=cpu_threads,
                verbose=False
            )
            return self._llm
        except Exception as e:
            logger.warning(f"Could not load llama-cpp runtime: {e}")
            return None

    def reset_llm(self):
        """Safely clear KV cache and reset context state in llama-cpp."""
        if self._llm is not None:
            try:
                self._llm.reset()
            except Exception as e:
                logger.warning(f"Error resetting LLM KV cache: {e}. Purging model instance.")
                self.unload_models()

    def get_stt(self):
        """Lazy loader for Whisper Small using faster-whisper."""
        if not getattr(settings, "AI_ENABLED", True):
            return None
        if self._stt is not None:
            return self._stt

        if not self.stt_path.exists():
            logger.warning(f"Whisper STT path not found at {self.stt_path}")
            return None

        try:
            from faster_whisper import WhisperModel
            logger.info(f"Loading Whisper STT from {self.stt_path} (device=cpu, compute_type=int8)...")
            self._stt = WhisperModel(
                model_size_or_path=str(self.stt_path),
                device="cpu",
                compute_type="int8"
            )
            return self._stt
        except Exception as e:
            logger.warning(f"Could not load faster-whisper runtime: {e}")
            return None

    def get_tts(self):
        """Lazy loader for Kokoro ONNX."""
        if not getattr(settings, "AI_ENABLED", True):
            return None
        if self._tts is not None:
            return self._tts

        if not self.tts_path.exists():
            logger.warning(f"Kokoro TTS path not found at {self.tts_path}")
            return None

        try:
            from kokoro_onnx import Kokoro
            onnx_file = self.tts_path / "onnx" / "model.onnx"
            if not onnx_file.exists():
                onnx_file = self.tts_path / "onnx" / "kokoro-v0_19.onnx"
            voices_file = self.tts_path / "voices.bin"

            if not onnx_file.exists() or not voices_file.exists():
                logger.warning(f"Missing Kokoro onnx or voices: {onnx_file}, {voices_file}")
                return None

            logger.info(f"Loading Kokoro TTS from {onnx_file}...")
            self._tts = Kokoro(model_path=str(onnx_file), voices_path=str(voices_file))
            return self._tts
        except Exception as e:
            logger.warning(f"Could not load Kokoro ONNX: {e}")
            return None

    def unload_models(self):
        """Release models to free memory."""
        self._llm = None
        self._stt = None
        self._tts = None

# Global access
model_manager = ModelManager()
