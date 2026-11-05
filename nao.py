import subprocess
import sys
import time
import unicodedata
from pathlib import Path

import paramiko
import requests

# ---------- Ρυθμίσεις ----------
NAO_IP = "192.168.0.165"
NAO_USER = "nao"
NAO_KEY = Path.home() / ".ssh" / "nao_key"

SERVER_URL = "http://127.0.0.1:5000/chat"

PROJECT_DIR = Path(__file__).resolve().parent
AUDIO_DIR = PROJECT_DIR / "audio"
LOCAL_WAV = AUDIO_DIR / "audio.wav"
ACTIVATION_TXT = AUDIO_DIR / "activation.txt"
SPEECH_SCRIPT = PROJECT_DIR / "speech2txt.py"
HELPER_LOCAL = PROJECT_DIR / "nao_helper.py"

NAO_HELPER = "/home/nao/nao_helper.py"
NAO_WAV = "/home/nao/audio.wav"
NAO_TEXT = "/home/nao/say.txt"
NAO_PYTHONPATH = "/opt/aldebaran/lib/python2.7/site-packages"

RECORD_SECONDS = 6

ACTIVATION_WORD = "καλημερα"
DEACTIVATION_WORD = "αντιο"
NOT_RECOGNIZED = "δεν σε ακουσα καλα"


def normalize(text):
    text = unicodedata.normalize("NFD", text.lower().strip())
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return " ".join(text.split())


# ---------- NAO μέσω SSH ----------

def connect():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        NAO_IP, username=NAO_USER,
        key_filename=str(NAO_KEY),
        timeout=10, look_for_keys=False, allow_agent=False,
    )
    with ssh.open_sftp() as sftp:
        sftp.put(str(HELPER_LOCAL), NAO_HELPER)
    return ssh


def run_on_nao(ssh, args):
    """Τρέχει το nao_helper.py στο NAO με φορτωμένο περιβάλλον."""
    cmd = (
        f"bash -lc 'PYTHONPATH={NAO_PYTHONPATH}:$PYTHONPATH "
        f"python {NAO_HELPER} {args}'"
    )
    _, stdout, stderr = ssh.exec_command(cmd)
    code = stdout.channel.recv_exit_status()
    if code != 0:
        print("Σφάλμα στο NAO:", stderr.read().decode("utf-8", "replace"))
    return code == 0


def say(ssh, text):
    print(f"NAO: {text}")
    with ssh.open_sftp() as sftp:
        with sftp.open(NAO_TEXT, "wb") as f:
            f.write(text.encode("utf-8"))
    run_on_nao(ssh, f"say {NAO_TEXT}")


def record(ssh):
    AUDIO_DIR.mkdir(exist_ok=True)
    print("Ηχογράφηση...")
    if not run_on_nao(ssh, f"record {NAO_WAV} {RECORD_SECONDS}"):
        time.sleep(2)
        return False
    with ssh.open_sftp() as sftp:
        sftp.get(NAO_WAV, str(LOCAL_WAV))
    return LOCAL_WAV.exists() and LOCAL_WAV.stat().st_size > 0


# ---------- Αναγνώριση ομιλίας ----------

def listen_text():
    ACTIVATION_TXT.unlink(missing_ok=True)
    try:
        subprocess.run(
            [sys.executable, str(SPEECH_SCRIPT)],
            check=True, cwd=str(PROJECT_DIR), timeout=60,
        )
        return normalize(ACTIVATION_TXT.read_text(encoding="utf-8-sig"))
    except Exception as exc:
        print("Σφάλμα αναγνώρισης:", exc)
        return ""


# ---------- Gemini μέσω server ----------

def ask_server(text):
    try:
        r = requests.post(SERVER_URL, json={"text": text}, timeout=60)
        r.raise_for_status()
        answer = r.json().get("response", "")
        return answer.strip() or "Δεν έλαβα απάντηση."
    except requests.exceptions.RequestException as exc:
        print("Σφάλμα server:", exc)
        return "Δεν μπορώ να συνδεθώ με τον διακομιστή."


# ---------- Κύριο πρόγραμμα ----------

def main():
    ssh = connect()
    print("Συνδέθηκα με το NAO.")
    print("Πες 'καλημέρα' για να ξεκινήσουμε, 'αντίο' για έξοδο.")

    try:
        while True:
            # Αναμονή λέξης ενεργοποίησης
            while True:
                if record(ssh) and ACTIVATION_WORD in listen_text():
                    break

            say(ssh, "Γεια σου!")

            # Συνομιλία
            while True:
                say(ssh, "Πώς μπορώ να σε βοηθήσω;")
                if not record(ssh):
                    continue

                sentence = listen_text()
                if not sentence:
                    say(ssh, "Δεν κατάλαβα. Δοκίμασε ξανά.")
                    continue
                if sentence == normalize(NOT_RECOGNIZED):
                    say(ssh, "Δεν σε άκουσα καλά.")
                    continue
                if DEACTIVATION_WORD in sentence:
                    say(ssh, "Τα λέμε!")
                    break

                print("Ερώτηση:", sentence)
                say(ssh, ask_server(sentence))

    except KeyboardInterrupt:
        print("\nΤερματισμός.")
    finally:
        ssh.close()


if __name__ == "__main__":
    main()
