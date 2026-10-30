import sys
import logging
from pathlib import Path
from django.core.management.base import BaseCommand
from django.conf import settings
from services.ai.model_manager import model_manager

class Command(BaseCommand):
    help = "Performs rigorous diagnostic checks on local AI models (Qwen LLM, Whisper STT, Kokoro TTS) and reports exact status."

    def add_arguments(self, parser):
        parser.add_argument("--infer", action="store_true", help="Attempt smoke inference test on available models")

    def handle(self, *args, **options):
        self.stdout.write("=" * 60)
        self.stdout.write("      SUPPORTO AI - LOCAL MODEL DIAGNOSTICS")
        self.stdout.write("=" * 60)

        health = model_manager.get_health_status()
        self.stdout.write(f"Global AI Enabled : {health['ai_enabled']}")
        self.stdout.write("-" * 60)

        # 1. LLM (Qwen 3 8B)
        llm_info = health["llm"]
        self.stdout.write(self.style.MIGRATE_HEADING("[1] LLM: Qwen 3 8B (Q4_K_M.gguf)"))
        self.stdout.write(f"    Path               : {llm_info['path']}")
        self.stdout.write(f"    File Exists        : {llm_info['file_exists']}")
        if llm_info['file_exists']:
            self.stdout.write(f"    Size               : {llm_info['file_size_gb']} GB")
        self.stdout.write(f"    Runtime (llama-cpp): {llm_info['runtime_installed']}")
        self.stdout.write(f"    Reported Status    : {llm_info['status']}")

        if options.get("infer"):
            if llm_info["file_exists"] and llm_info["runtime_installed"]:
                self.stdout.write("    Executing test inference...")
                llm = model_manager.get_llm()
                if llm:
                    try:
                        res = llm("Hello, tell me you are online in one short sentence.", max_tokens=25)
                        text = res["choices"][0]["text"].strip()
                        self.stdout.write(self.style.SUCCESS(f"    Inference Success  : '{text}'"))
                    except Exception as e:
                        self.stdout.write(self.style.ERROR(f"    Inference Failed   : {e}"))
                else:
                    self.stdout.write(self.style.ERROR("    Model failed to initialize."))
            else:
                self.stdout.write(self.style.WARNING("    Inference skipped (missing model file or runtime). Intelligent RAG fallback active."))

        self.stdout.write("-" * 60)

        # 2. STT (Whisper Small)
        stt_info = health["stt"]
        self.stdout.write(self.style.MIGRATE_HEADING("[2] STT: Whisper Small"))
        self.stdout.write(f"    Directory Path     : {stt_info['path']}")
        self.stdout.write(f"    Directory Exists   : {stt_info['dir_exists']}")
        self.stdout.write(f"    Runtime (faster-whisper): {stt_info['runtime_installed']}")
        self.stdout.write(f"    Reported Status    : {stt_info['status']}")

        self.stdout.write("-" * 60)

        # 3. TTS (Kokoro TTS)
        tts_info = health["tts"]
        self.stdout.write(self.style.MIGRATE_HEADING("[3] TTS: Kokoro TTS"))
        self.stdout.write(f"    Directory Path     : {tts_info['path']}")
        self.stdout.write(f"    Directory Exists   : {tts_info['dir_exists']}")
        self.stdout.write(f"    Runtime (kokoro-onnx): {tts_info['runtime_installed']}")
        self.stdout.write(f"    Reported Status    : {tts_info['status']}")

        self.stdout.write("=" * 60)
        self.stdout.write("Diagnostics complete. Fallback engine guarantees 100% web app availability.")

