# -*- coding: utf-8 -*-
import os
import sys
import time
import uuid
import threading
import unicodedata
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

try:
    import paramiko
except ImportError:
    paramiko = None
    print("[ΠΡΟΕΙΔΟΠΟΙΗΣΗ] Λείπει το 'paramiko'. Τρέξε: pip install paramiko")

try:
    import requests
except ImportError:
    requests = None
    print("[ΠΡΟΕΙΔΟΠΟΙΗΣΗ] Λείπει το 'requests'. Τρέξε: pip install requests")

from speech2text import recognize_audio

# ---------- ΡΥΘΜΙΣΕΙΣ ----------
NAO_IP       = os.environ.get("NAO_IP",       "192.168.0.165")
NAO_USER     = os.environ.get("NAO_USER",     "nao")
NAO_PASSWORD = os.environ.get("NAO_PASSWORD", "nao")
NAO_KEY      = Path(os.environ.get("NAO_KEY", Path.home() / ".ssh" / "nao_key"))

SERVER_URL = os.environ.get("SERVER_URL", "http://127.0.0.1:5000/chat")
RESET_URL  = os.environ.get("RESET_URL",  "http://127.0.0.1:5000/reset")
STATUS_URL = os.environ.get("STATUS_URL", "http://127.0.0.1:5000/api/set_state")

PROJECT_DIR = Path(__file__).resolve().parent
AUDIO_DIR   = PROJECT_DIR / "audio"
LOCAL_WAV   = AUDIO_DIR / "audio.wav"
HELPER_LOCAL = PROJECT_DIR / "nao_helper.py"

NAO_HELPER     = "/home/nao/nao_helper.py"
NAO_WAV        = "/home/nao/audio.wav"
NAO_TEXT       = "/home/nao/say.txt"
NAO_PYTHONPATH = "/opt/aldebaran/lib/python2.7/site-packages"

WAKE_RECORD_SECONDS = float(os.environ.get("WAKE_RECORD_SECONDS", 2.2))
CONV_RECORD_SECONDS = float(os.environ.get("CONV_RECORD_SECONDS", 4.5))
MAX_CONSECUTIVE_SILENCE = 3

ACTIVATION_KEYWORDS   = ["καλημερα", "ναο", "γεια σου", "ελα", "ακουσε με"]
DEACTIVATION_KEYWORDS = ["αντιο", "τα λεμε", "στο καλο", "κλεισε", "σταματα", "αντιο σας"]


# ---------- ΒΟΗΘΗΤΙΚΕΣ ----------

def normalize(text):
    """Αφαιρεί τόνους και στίξη για σύγκριση λέξεων-κλειδιών."""
    if not text:
        return ""
    text = unicodedata.normalize("NFD", text.lower().strip())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    for punct in "!?,.;:\"'-_()":
        text = text.replace(punct, " ")
    return " ".join(text.split())


def contains_keyword(text, keywords):
    norm = normalize(text)
    return any(kw in norm for kw in keywords)


def notify_dashboard(state, emotion=None, session_id=None):
    """Ενημερώνει ασύγχρονα το Dashboard (non-blocking)."""
    if not requests:
        return

    def _worker():
        try:
            payload = {"state": state}
            if emotion:
                payload["emotion"] = emotion
            if session_id:
                payload["session_id"] = session_id
            requests.post(STATUS_URL, json=payload, timeout=0.8)
        except Exception:
            pass

    t = threading.Thread(target=_worker)
    t.daemon = True
    t.start()


# ---------- SSH / SFTP ----------

def connect():
    """Συνδέεται μέσω SSH στο NAO και ανεβάζει το nao_helper.py."""
    if paramiko is None:
        raise RuntimeError("Λείπει το 'paramiko'. Τρέξε: pip install paramiko")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    key_file = str(NAO_KEY) if NAO_KEY.exists() else None
    if not key_file:
        print("[NAO] SSH key δεν βρέθηκε, χρήση κωδικού...")

    ssh.connect(
        NAO_IP,
        username=NAO_USER,
        password=NAO_PASSWORD if not key_file else None,
        key_filename=key_file,
        timeout=10,
        look_for_keys=True,
        allow_agent=True,
    )
    sftp = ssh.open_sftp()
    sftp.put(str(HELPER_LOCAL), NAO_HELPER)
    print("[NAO] Συνδέθηκα στο NAO (%s) και ανέβασα το nao_helper.py." % NAO_IP)
    return ssh, sftp


def run_on_nao(ssh, args):
    """Εκτελεί εντολή στο Python 2.7 περιβάλλον του NAO."""
    cmd = (
        "bash -lc 'PYTHONPATH=%s:$PYTHONPATH python %s %s'"
        % (NAO_PYTHONPATH, NAO_HELPER, args)
    )
    _, stdout, stderr = ssh.exec_command(cmd)
    code = stdout.channel.recv_exit_status()
    if code != 0:
        print("[NAO ERROR (%d)]: %s" % (code, stderr.read().decode("utf-8", "replace").strip()))
    return code == 0


# ---------- ΕΝΤΟΛΕΣ NAO ----------

def set_leds(ssh, state):
    run_on_nao(ssh, "leds %s" % state)


def set_face_tracking(ssh, enable=True):
    run_on_nao(ssh, "track_face %s" % ("1" if enable else "0"))


def say(ssh, sftp, text, emotion="neutral"):
    """Στέλνει κείμενο στο NAO για εκφώνηση με emotion animation."""
    if not text:
        return
    print("[NAO SAY] (%s): %s" % (emotion, text))
    with sftp.open(NAO_TEXT, "wb") as f:
        f.write(text.encode("utf-8"))
    run_on_nao(ssh, "say %s %s" % (NAO_TEXT, emotion))


def record(ssh, sftp, seconds):
    """Ηχογραφεί ήχο από το NAO και το κατεβάζει τοπικά."""
    AUDIO_DIR.mkdir(parents=True, exist_ok=True)
    if not run_on_nao(ssh, "record %s %s" % (NAO_WAV, seconds)):
        time.sleep(0.3)
        return False
    try:
        if LOCAL_WAV.exists():
            LOCAL_WAV.unlink()
        sftp.get(NAO_WAV, str(LOCAL_WAV))
    except Exception as e:
        print("[SFTP Error]: %s" % e)
        return False
    return LOCAL_WAV.exists() and LOCAL_WAV.stat().st_size > 100


# ---------- SERVER ----------

def ask_server(text, session_id):
    """Στέλνει κείμενο στον Flask server και λαμβάνει απάντηση + emotion."""
    if not requests:
        return "Δεν έχει εγκατασταθεί η βιβλιοθήκη requests.", "sad"
    try:
        r = requests.post(
            SERVER_URL,
            json={"text": text, "session_id": session_id},
            timeout=40
        )
        r.raise_for_status()
        data = r.json()
        reply   = data.get("response", "").strip() or "Δεν έλαβα απάντηση."
        emotion = data.get("emotion", "neutral")
        return reply, emotion
    except requests.exceptions.Timeout:
        return "Ο διακομιστής άργησε να απαντήσει. Μπορείς να ξαναδοκιμάσεις;", "sad"
    except requests.exceptions.RequestException as e:
        print("[SERVER ERROR]: %s" % e)
        return "Δεν μπορώ να συνδεθώ με τον διακομιστή αυτή τη στιγμή.", "sad"


def reset_server_session(session_id):
    try:
        requests.post(RESET_URL, json={"session_id": session_id}, timeout=5)
    except Exception:
        pass


# ---------- ΚΥΡΙΟ ΠΡΟΓΡΑΜΜΑ ----------

def main():
    try:
        ssh, sftp = connect()
    except Exception as e:
        print("[FATAL] Αδυναμία σύνδεσης με το NAO (%s): %s" % (NAO_IP, e))
        return

    print("=" * 60)
    print("   NAO & Gemini | Wake: %.1fs | Conv: %.1fs" % (WAKE_RECORD_SECONDS, CONV_RECORD_SECONDS))
    print("   Λέξεις αφύπνισης: %s" % ", ".join(ACTIVATION_KEYWORDS))
    print("=" * 60)

    session_id = "session_%s" % uuid.uuid4().hex[:8]

    try:
        while True:
            # ── ΦΑΣΗ 1: ΑΝΑΜΟΝΗ ΛΕΞΗΣ-ΚΛΕΙΔΙΟΥ ──────────────────────
            set_leds(ssh, "standby")
            set_face_tracking(ssh, False)
            notify_dashboard("standby", session_id=session_id)
            print("\n[ΑΝΑΜΟΝΗ] Περιμένω λέξη-κλειδί...")

            while True:
                if not record(ssh, sftp, WAKE_RECORD_SECONDS):
                    time.sleep(0.3)
                    continue
                recognized = recognize_audio(LOCAL_WAV)
                if recognized and recognized not in ("[SILENCE]", "[NOT_RECOGNIZED]", "[ERROR]", "[ERROR_NETWORK]"):
                    print("[Ανίχνευση]: '%s'" % recognized)
                    if contains_keyword(recognized, ACTIVATION_KEYWORDS):
                        print(">>> Λέξη-κλειδί αναγνωρίστηκε! <<<")
                        break

            # ── ΦΑΣΗ 2: ΣΥΝΟΜΙΛΙΑ ─────────────────────────────────────
            set_leds(ssh, "wake")
            set_face_tracking(ssh, True)
            session_id = "session_%s" % uuid.uuid4().hex[:8]
            notify_dashboard("speaking", emotion="happy", session_id=session_id)
            say(ssh, sftp, "Γεια σου! Σε βλέπω και σε ακούω. Πώς μπορώ να σε βοηθήσω;", emotion="happy")

            consecutive_silence = 0

            while True:
                set_leds(ssh, "listening")
                notify_dashboard("listening", session_id=session_id)
                print("\n[ΑΚΡΟΑΣΗ] Σε ακούω...")

                if not record(ssh, sftp, CONV_RECORD_SECONDS):
                    continue

                t_stt = time.time()
                user_input = recognize_audio(LOCAL_WAV)
                stt_ms = round((time.time() - t_stt) * 1000)

                if user_input in ("[SILENCE]", ""):
                    consecutive_silence += 1
                    if consecutive_silence >= MAX_CONSECUTIVE_SILENCE:
                        notify_dashboard("speaking", emotion="neutral", session_id=session_id)
                        say(ssh, sftp, "Φαίνεται πως δεν είσαι εκεί. Μπαίνω σε αναμονή.", emotion="neutral")
                        reset_server_session(session_id)
                        set_face_tracking(ssh, False)
                        notify_dashboard("standby", session_id=session_id)
                        break
                    notify_dashboard("speaking", emotion="curious", session_id=session_id)
                    say(ssh, sftp, "Δεν σε άκουσα, είσαι ακόμα εκεί;", emotion="curious")
                    continue

                consecutive_silence = 0

                if user_input == "[NOT_RECOGNIZED]":
                    notify_dashboard("speaking", emotion="curious", session_id=session_id)
                    say(ssh, sftp, "Δεν σε κατάλαβα καλά, μπορείς να το επαναλάβεις;", emotion="curious")
                    continue

                if user_input in ("[ERROR]", "[ERROR_NETWORK]"):
                    notify_dashboard("speaking", emotion="sad", session_id=session_id)
                    say(ssh, sftp, "Υπήρξε πρόβλημα στην αναγνώριση φωνής.", emotion="sad")
                    continue

                print("[ΧΡΗΣΤΗΣ (%dms)]: %s" % (stt_ms, user_input))

                if contains_keyword(user_input, DEACTIVATION_KEYWORDS):
                    notify_dashboard("speaking", emotion="happy", session_id=session_id)
                    say(ssh, sftp, "Χάρηκα που τα είπαμε! Τα λέμε σύντομα, αντίο!", emotion="happy")
                    reset_server_session(session_id)
                    set_face_tracking(ssh, False)
                    notify_dashboard("standby", session_id=session_id)
                    break

                set_leds(ssh, "thinking")
                notify_dashboard("thinking", session_id=session_id)
                print("[ΣΚΕΨΗ] Αποστολή στο Gemini...")

                response_text, emotion = ask_server(user_input, session_id)

                notify_dashboard("speaking", emotion=emotion, session_id=session_id)
                say(ssh, sftp, response_text, emotion=emotion)

    except KeyboardInterrupt:
        print("\n[ΤΕΡΜΑΤΙΣΜΟΣ] Έξοδος...")
        try:
            set_face_tracking(ssh, False)
            set_leds(ssh, "standby")
        except Exception:
            pass
    finally:
        try:
            sftp.close()
            ssh.close()
        except Exception:
            pass
        print("[NAO] Σύνδεση έκλεισε ομαλά.")


if __name__ == "__main__":
    main()
