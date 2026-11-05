# -*- coding: utf-8 -*-
# Τρέχει ΜΕΣΑ στο NAO (Python 2.7). Ανεβαίνει αυτόματα από το nao.py.
import sys
import io
import time
from naoqi import ALProxy

IP, PORT = "127.0.0.1", 9559


def say(text_path):
    text = io.open(text_path, "r", encoding="utf-8").read().strip()
    tts = ALProxy("ALTextToSpeech", IP, PORT)
    try:
        tts.setLanguage("Greek")
    except Exception as e:
        print("Προειδοποίηση γλώσσας: %s" % e)
    tts.say(text.encode("utf-8"))


def record(out_path, seconds):
    try:
        ALProxy("ALAutonomousLife", IP, PORT).setState("disabled")
    except Exception:
        pass
    rec = ALProxy("ALAudioRecorder", IP, PORT)
    try:
        rec.stopMicrophonesRecording()
    except Exception:
        pass
    # (0,0,1,0) = μόνο το μπροστινό μικρόφωνο, άρα mono wav
    rec.startMicrophonesRecording(out_path, "wav", 16000, (0, 0, 1, 0))
    time.sleep(float(seconds))
    rec.stopMicrophonesRecording()


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "say":
        say(sys.argv[2])
    elif cmd == "record":
        record(sys.argv[2], sys.argv[3])
    else:
        print("Άγνωστη εντολή: %s" % cmd)
        sys.exit(1)
