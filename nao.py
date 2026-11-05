# -*- coding: utf-8 -*-
import shutil
import subprocess
from pathlib import Path

import speech_recognition as sr

BASE = Path(__file__).resolve().parent / "audio"
WAV = BASE / "audio.wav"
CLEAN = BASE / "audio_clean.wav"
OUT = BASE / "activation.txt"


def clean_audio(src, dst):
    """Ενισχύει τη φωνή και κόβει το βουητό. Αν δεν υπάρχει ffmpeg, χρησιμοποιεί το αρχικό."""
    if shutil.which("ffmpeg") is None:
        return src
    result = subprocess.run(
        ["ffmpeg", "-y", "-i", str(src), "-ac", "1", "-ar", "16000",
         "-af", "highpass=f=120,dynaudnorm=f=150:g=15", str(dst)],
        capture_output=True,
    )
    return dst if result.returncode == 0 else src


recognizer = sr.Recognizer()

try:
    with sr.AudioFile(str(clean_audio(WAV, CLEAN))) as source:
        audio = recognizer.record(source)
    text = recognizer.recognize_google(audio, language="el-GR")
except sr.UnknownValueError:
    text = "δεν σε ακουσα καλα"
except Exception as e:
    print("Σφάλμα αναγνώρισης:", e)
    text = ""

OUT.write_text(text, encoding="utf-8")
print("Κείμενο:", text)
