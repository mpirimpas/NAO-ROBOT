# -*- coding: utf-8 -*-
# Τρέχει ΜΕΣΑ στο NAO (Python 2.7). Ανεβαίνει αυτόματα από το nao.py.
import sys
import io
import os
import time
import threading
from naoqi import ALProxy

IP, PORT = "127.0.0.1", 9559

# ---------- ΧΡΩΜΑΤΑ LED & ΣΥΝΑΙΣΘΗΜΑΤΑ ----------
LED_COLORS = {
    "standby":    (0.05, 0.05, 0.2),
    "listening":  (0.0,  1.0,  1.0),
    "thinking":   (1.0,  0.8,  0.0),
    "wake":       (0.0,  1.0,  0.0),
    "happy":      (0.1,  1.0,  0.1),
    "excited":    (1.0,  0.2,  0.8),
    "curious":    (0.2,  0.8,  1.0),
    "empathetic": (0.4,  0.2,  0.9),
    "sad":        (0.0,  0.1,  0.8),
    "serious":    (1.0,  0.4,  0.0),
    "neutral":    (0.8,  0.8,  0.9),
}

# ---------- EMOTION → ANIMATION ----------
EMOTION_BEHAVIORS = {
    "happy":      "animations/Stand/Emotions/Positive/Happy_4",
    "excited":    "animations/Stand/Emotions/Positive/Excited_1",
    "curious":    "animations/Stand/Emotions/Neutral/Thinking_1",
    "empathetic": "animations/Stand/Emotions/Neutral/Embarrassed_1",
    "sad":        "animations/Stand/Emotions/Negative/Sad_1",
    "serious":    "animations/Stand/Emotions/Neutral/Cautious_1",
    "neutral":    None,  # Καμία animation (εξοικονόμηση χρόνου)
}


# ---------- LEDS ----------

def set_leds(state):
    """Ρυθμίζει το χρώμα στα μάτια (FaceLeds) του NAO."""
    try:
        leds = ALProxy("ALLeds", IP, PORT)
        state = state.lower().strip()

        if state == "thinking":
            try:
                leds.rotateEyes(0xFFCC00, 0.8, 1.2)
                return
            except Exception:
                pass
        elif state == "wake":
            try:
                leds.fadeRGB("FaceLeds", 0.0, 1.0, 0.0, 0.1)
                time.sleep(0.1)
                leds.fadeRGB("FaceLeds", 1.0, 1.0, 1.0, 0.1)
                time.sleep(0.1)
            except Exception:
                pass

        rgb = LED_COLORS.get(state, LED_COLORS["neutral"])
        leds.fadeRGB("FaceLeds", rgb[0], rgb[1], rgb[2], 0.2)
    except Exception as e:
        print("Προειδοποίηση LED: %s" % e)


# ---------- FACE TRACKING ----------

def track_face(enable):
    """Ενεργοποιεί/Απενεργοποιεί την παρακολούθηση προσώπου.

    Όταν enable=True:  NAO ψάχνει ενεργά πρόσωπα και στρέφει το κεφάλι του.
    Όταν enable=False: σταματάει το tracking και επιστρέφει ομαλά στο κέντρο.
    """
    enable = str(enable).lower() in ("1", "true", "start", "on")

    # Stiffness κεφαλιού ώστε να μπορεί να κινηθεί
    try:
        ALProxy("ALMotion", IP, PORT).setStiffnesses("Head", 1.0)
    except Exception:
        pass

    # ── Προσπάθεια με ALTracker (NAOqi 2.x — προτεινόμενο) ──────────────────
    try:
        tracker = ALProxy("ALTracker", IP, PORT)
        if enable:
            tracker.registerTarget("Face", 0.12)   # 0.12m = τυπικό ανθρώπινο πρόσωπο
            tracker.setMode("Head")                 # Κινεί μόνο κεφάλι, όχι σώμα
            tracker.track("Face")
            print("[FaceTrack] ALTracker ON — παρακολούθηση προσώπου.")
        else:
            try:
                tracker.stopTracker()
            except Exception:
                pass
            try:
                tracker.unregisterTarget("Face")
            except Exception:
                pass
            center_head()
            print("[FaceTrack] ALTracker OFF — κεφάλι στο κέντρο.")
        return True
    except Exception:
        pass

    # ── Fallback: ALFaceTracker (Legacy NAOqi) ───────────────────────────────
    try:
        face_tracker = ALProxy("ALFaceTracker", IP, PORT)
        if enable:
            face_tracker.startTracker()
            print("[FaceTrack] ALFaceTracker ON.")
        else:
            face_tracker.stopTracker()
            center_head()
            print("[FaceTrack] ALFaceTracker OFF.")
        return True
    except Exception as e:
        print("[FaceTrack] Μη διαθέσιμο: %s" % e)
        return False


def center_head():
    """Επιστρέφει ομαλά το κεφάλι στην κεντρική θέση (ουδέτερη στάση)."""
    try:
        motion = ALProxy("ALMotion", IP, PORT)
        # HeadYaw=0 (ευθεία), HeadPitch=0.1 (ελαφρά κάτω — φυσική στάση)
        motion.angleInterpolation(
            ["HeadYaw", "HeadPitch"],
            [0.0, 0.1],     # γωνίες σε radians
            [0.8, 0.8],     # διάρκεια σε seconds (ομαλή κίνηση)
            True            # absolute angles
        )
    except Exception as e:
        print("[FaceTrack] center_head σφάλμα: %s" % e)


# ---------- EMOTION ANIMATION ----------

def run_emotion_behavior(emotion):
    """Εκτελεί την αντίστοιχη animation του NAO βάσει emotion.
    Τρέχει σε thread με timeout 2.5s για να μην μπλοκάρει την ομιλία.
    """
    behavior = EMOTION_BEHAVIORS.get(emotion.lower().strip())
    if not behavior:
        return

    try:
        behavior_mgr = ALProxy("ALBehaviorManager", IP, PORT)

        if behavior not in behavior_mgr.getInstalledBehaviors():
            print("[GESTURE] Behavior '%s' δεν βρέθηκε, παράλειψη." % behavior)
            return

        done = threading.Event()

        def _run():
            try:
                behavior_mgr.runBehavior(behavior)
            except Exception as e:
                print("[GESTURE] Σφάλμα '%s': %s" % (behavior, e))
            finally:
                done.set()

        t = threading.Thread(target=_run)
        t.daemon = True
        t.start()
        done.wait(timeout=2.5)
        print("[GESTURE] %s" % behavior)

    except Exception as e:
        print("[GESTURE] ALBehaviorManager σφάλμα: %s" % e)


# ---------- ΟΜΙΛΙΑ ----------

def say(text_path, emotion="neutral"):
    """Διαβάζει κείμενο από αρχείο, ανάβει LEDs, παίζει emotion animation
    και μιλάει με φυσικές κινήσεις (ALAnimatedSpeech).
    """
    if not os.path.exists(text_path):
        return

    text = io.open(text_path, "r", encoding="utf-8").read().strip()
    if not text:
        return

    # 1. LEDs
    set_leds(emotion)

    # 2. Emotion animation (πριν ομιλία)
    run_emotion_behavior(emotion)

    # 3. Wake up κινητήρες
    try:
        ALProxy("ALMotion", IP, PORT).stiffnessWakeUp()
    except Exception as e:
        print("Προειδοποίηση Motion stiffness: %s" % e)

    # 4. Ομιλία με φυσικές κινήσεις
    encoded = text.encode("utf-8")
    spoken = False
    try:
        animated_speech = ALProxy("ALAnimatedSpeech", IP, PORT)
        animated_speech.say(encoded, {"bodyLanguageMode": "contextual"})
        spoken = True
    except Exception as e:
        print("AnimatedSpeech fallback: %s" % e)

    if not spoken:
        try:
            tts = ALProxy("ALTextToSpeech", IP, PORT)
            try:
                tts.setLanguage("Greek")
            except Exception:
                pass
            tts.say(encoded)
        except Exception as e:
            print("TTS σφάλμα: %s" % e)


# ---------- ΗΧΟΓΡΑΦΗΣΗ ----------

def record(out_path, seconds):
    """Ηχογραφεί ήχο από το μικρόφωνο του NAO (mono 16kHz)."""
    try:
        ALProxy("ALAutonomousLife", IP, PORT).setState("disabled")
    except Exception:
        pass

    try:
        rec = ALProxy("ALAudioRecorder", IP, PORT)
    except Exception as e:
        print("Σφάλμα ALAudioRecorder: %s" % e)
        return

    try:
        rec.stopMicrophonesRecording()
    except Exception:
        pass

    out_dir = os.path.dirname(out_path)
    if out_dir and not os.path.exists(out_dir):
        try:
            os.makedirs(out_dir)
        except Exception:
            pass

    rec.startMicrophonesRecording(out_path, "wav", 16000, (0, 0, 1, 0))
    time.sleep(float(seconds))
    rec.stopMicrophonesRecording()


# ---------- ENTRY POINT (CLI από nao.py) ----------

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Χρήση: python nao_helper.py [say <text_path> [emotion] | record <out_path> <seconds> | leds <state> | track_face <1/0>]")
        sys.exit(1)

    cmd = sys.argv[1]
    if cmd == "say" and len(sys.argv) >= 3:
        emotion = sys.argv[3] if len(sys.argv) >= 4 else "neutral"
        say(sys.argv[2], emotion)
    elif cmd == "record" and len(sys.argv) >= 4:
        record(sys.argv[2], sys.argv[3])
    elif cmd == "leds" and len(sys.argv) >= 3:
        set_leds(sys.argv[2])
    elif cmd == "track_face" and len(sys.argv) >= 3:
        track_face(sys.argv[2])
    else:
        print("Άγνωστη εντολή: %s" % sys.argv)
        sys.exit(1)
