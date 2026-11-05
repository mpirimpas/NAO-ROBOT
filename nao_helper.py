# -*- coding: utf-8 -*-
# Τρέχει ΜΕΣΑ στο NAO (Python 2.7). Ανεβαίνει αυτόματα από το nao.py.
import sys
import io
import time
from naoqi import ALProxy

IP, PORT = "127.0.0.1", 9559

# Γωνίες σε ακτίνια, μέσα στα όρια των αρθρώσεων.
# Σειρά: LShoulderPitch, LShoulderRoll, LElbowYaw, LElbowRoll,
#        RShoulderPitch, RShoulderRoll, RElbowYaw, RElbowRoll, HeadYaw
NAMES = ["LShoulderPitch", "LShoulderRoll", "LElbowYaw", "LElbowRoll",
         "RShoulderPitch", "RShoulderRoll", "RElbowYaw", "RElbowRoll",
         "HeadYaw"]

# Απλός χορός
DANCE_A = [-0.5, 0.6, -1.0, -0.8, 1.5, -0.2, 1.0, 0.5, 0.4]
DANCE_B = [1.5, 0.2, -1.0, -0.5, -0.5, -0.6, 1.0, 0.8, -0.4]

# Floss: ίσια χέρια που ταλαντεύονται από πλευρά σε πλευρά,
# το ένα μπροστά και το άλλο πίσω από το σώμα
FLOSS_A = [0.9, -0.2, 0.0, -0.05, 2.0, -0.5, 0.0, 0.05, 0.0]
FLOSS_B = [2.0, 0.5, 0.0, -0.05, 0.9, 0.2, 0.0, 0.05, 0.0]
FLOSS_TIME = 0.3  # δευτερόλεπτα ανά ταλάντωση (μικρότερο = πιο γρήγορο)


# ---------- Φωνή ----------

def say(text_path):
    text = io.open(text_path, "r", encoding="utf-8").read().strip()
    tts = ALProxy("ALTextToSpeech", IP, PORT)
    try:
        tts.setLanguage("Greek")
    except Exception as e:
        print("Προειδοποίηση γλώσσας: %s" % e)
    tts.say(text.encode("utf-8"))


# ---------- Ηχογράφηση ----------

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


# ---------- Κίνηση ----------

def dance_setup():
    motion = ALProxy("ALMotion", IP, PORT)
    posture = ALProxy("ALRobotPosture", IP, PORT)
    try:
        ALProxy("ALAutonomousLife", IP, PORT).setState("disabled")
    except Exception:
        pass
    motion.wakeUp()
    posture.goToPosture("Stand", 0.6)
    return motion, posture


def move_step(motion, style, steps):
    if style == "floss":
        motion.angleInterpolation(NAMES, FLOSS_A, FLOSS_TIME, True)
        motion.angleInterpolation(NAMES, FLOSS_B, FLOSS_TIME, True)
        return
    motion.angleInterpolation(NAMES, DANCE_A, 0.5, True)
    if steps:
        motion.moveTo(0.0, 0.05, 0.0)    # μικρό βήμα αριστερά
    motion.angleInterpolation(NAMES, DANCE_B, 0.5, True)
    if steps:
        motion.moveTo(0.0, -0.05, 0.0)   # μικρό βήμα δεξιά


def touched(memory):
    try:
        return memory.getData("FrontTactilTouched") == 1.0
    except Exception:
        return False


def dance(seconds, steps, style):
    motion, posture = dance_setup()
    memory = ALProxy("ALMemory", IP, PORT)
    end = time.time() + float(seconds)
    while time.time() < end:
        if touched(memory):
            break
        move_step(motion, style, steps)
    posture.goToPosture("Stand", 0.6)


# ---------- Τραγούδι ----------

def start_audio(path):
    try:
        ALProxy("ALAudioDevice", IP, PORT).setOutputVolume(80)
    except Exception as e:
        print("Προειδοποίηση έντασης: %s" % e)
    player = ALProxy("ALAudioPlayer", IP, PORT)
    task = player.post.playFile(path)
    time.sleep(1)  # να προλάβει να ξεκινήσει
    return player, task


def play(path):
    """Παίζει το τραγούδι. Άγγιγμα στο μπροστινό αισθητήριο = στοπ."""
    player, task = start_audio(path)
    memory = ALProxy("ALMemory", IP, PORT)
    while player.isRunning(task):
        if touched(memory):
            player.stopAll()
            break
        time.sleep(0.2)


def play_and_dance(path, steps, style):
    """Παίζει το τραγούδι και κινείται μέχρι να τελειώσει ή να αγγίξεις το κεφάλι."""
    motion, posture = dance_setup()
    player, task = start_audio(path)
    memory = ALProxy("ALMemory", IP, PORT)
    while player.isRunning(task):
        if touched(memory):
            player.stopAll()
            break
        move_step(motion, style, steps)
    posture.goToPosture("Stand", 0.6)


def stop():
    try:
        ALProxy("ALAudioPlayer", IP, PORT).stopAll()
    except Exception:
        pass
    try:
        ALProxy("ALMotion", IP, PORT).killAll()
    except Exception:
        pass


if __name__ == "__main__":
    cmd = sys.argv[1]
    steps = len(sys.argv) > 3 and sys.argv[-1] == "steps"
    if cmd == "say":
        say(sys.argv[2])
    elif cmd == "record":
        record(sys.argv[2], sys.argv[3])
    elif cmd == "play":
        play(sys.argv[2])
    elif cmd == "playdance":
        play_and_dance(sys.argv[2], steps, "dance")
    elif cmd == "playfloss":
        play_and_dance(sys.argv[2], steps, "floss")
    elif cmd == "dance":
        dance(sys.argv[2], steps, "dance")
    elif cmd == "floss":
        dance(sys.argv[2], steps, "floss")
    elif cmd == "stop":
        stop()
    else:
        print("Άγνωστη εντολή: %s" % cmd)
        sys.exit(1)
