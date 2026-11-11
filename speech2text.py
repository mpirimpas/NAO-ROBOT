# -*- coding: utf-8 -*-
import os
import shutil
import subprocess
from pathlib import Path

try:
    import speech_recognition as sr
except ImportError:
    sr = None
    print("[ΠΡΟΕΙΔΟΠΟΙΗΣΗ] Λείπει το 'speech_recognition'. Τρέξε: pip install SpeechRecognition")

BASE        = Path(__file__).resolve().parent / "audio"
BASE.mkdir(parents=True, exist_ok=True)
DEFAULT_WAV = BASE / "audio.wav"


class SpeechEngine:
    """In-memory Speech Recognition Engine (χωρίς subprocess overhead)."""

    def __init__(self, language="el-GR"):
        self.language  = language
        self.has_ffmpeg = shutil.which("ffmpeg") is not None
        if sr is not None:
            self.recognizer = sr.Recognizer()
            self.recognizer.energy_threshold        = 300
            self.recognizer.dynamic_energy_threshold = True
        else:
            self.recognizer = None

    def _clean_audio(self, src, dst):
        """Καθαρίζει θόρυβο και κανονικοποιεί ήχο μέσω ffmpeg (αν υπάρχει)."""
        if not self.has_ffmpeg:
            return src
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-i", str(src),
                 "-ac", "1", "-ar", "16000",
                 "-af", "highpass=f=120,dynaudnorm=f=150:g=15",
                 str(dst)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            return dst if result.returncode == 0 else src
        except Exception:
            return src

    def recognize(self, wav_path):
        """Αναγνωρίζει φωνή από WAV αρχείο. Επιστρέφει (κείμενο, status)."""
        wav_path = Path(wav_path)
        if not wav_path.exists() or wav_path.stat().st_size < 200:
            return "[SILENCE]", "EMPTY_OR_MISSING"

        if self.recognizer is None:
            return "[ERROR]", "SPEECH_RECOGNITION_NOT_INSTALLED"

        clean_path = wav_path.parent / (wav_path.stem + "_clean.wav")
        processed  = self._clean_audio(wav_path, clean_path)

        try:
            with sr.AudioFile(str(processed)) as source:
                audio = self.recognizer.record(source)
            text = self.recognizer.recognize_google(audio, language=self.language)
            return text.strip(), "OK"
        except sr.UnknownValueError:
            return "[NOT_RECOGNIZED]", "UNKNOWN_VALUE"
        except sr.RequestError as e:
            return "[ERROR_NETWORK]", "REQUEST_ERROR: %s" % e
        except Exception as e:
            return "[ERROR]", "GENERAL_ERROR: %s" % e


# Singleton instance
engine = SpeechEngine()


def recognize_audio(wav_path=DEFAULT_WAV):
    """Βοηθητική συνάρτηση: επιστρέφει μόνο το κείμενο."""
    text, _ = engine.recognize(wav_path)
    return text


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "audio" / "activation.txt"
    text, status = engine.recognize(DEFAULT_WAV)
    out.write_text(text, encoding="utf-8")
    print("Αναγνώριση (%s): %s" % (status, text))
