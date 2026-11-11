# -*- coding: utf-8 -*-
"""
start.py – Κεντρικό σημείο εκκίνησης του NAO-Gemini συστήματος.

Ελέγχει τις προϋποθέσεις, ξεκινάει τον Flask server στο background
και μετά εκκινεί το nao.py (κύριος βρόχος).

Χρήση:
    python3 start.py
"""

import os
import sys
import time
import subprocess
import socket
from pathlib import Path

# ── Χρώματα για terminal output ───────────────────────────────────────────────
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

def ok(msg):   print(GREEN  + "  ✔  " + RESET + msg)
def warn(msg): print(YELLOW + "  ⚠  " + RESET + msg)
def err(msg):  print(RED    + "  ✘  " + RESET + msg)
def info(msg): print(CYAN   + "  ➜  " + RESET + msg)

BASE_DIR = Path(__file__).resolve().parent


# ── 1. ΕΛΕΓΧΟΣ .env & API KEY ─────────────────────────────────────────────────

def check_env():
    env_file = BASE_DIR / ".env"
    if not env_file.exists():
        warn(".env δεν βρέθηκε. Δημιουργία από .env.example...")
        example = BASE_DIR / ".env.example"
        if example.exists():
            import shutil
            shutil.copy(example, env_file)
            warn("Δημιουργήθηκε .env — συμπλήρωσε GEMINI_API_KEY και NAO_IP!")
        else:
            err(".env.example δεν βρέθηκε. Δες το README.")
            sys.exit(1)

    try:
        from dotenv import load_dotenv
        load_dotenv(env_file, override=True)
    except ImportError:
        pass

    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key or api_key == "your_actual_gemini_api_key_here":
        err("GEMINI_API_KEY δεν έχει οριστεί στο .env!")
        err("Άνοιξε το αρχείο .env και βάλε το Gemini API key σου.")
        sys.exit(1)
    ok("GEMINI_API_KEY βρέθηκε.")

    nao_ip = os.environ.get("NAO_IP", "192.168.0.165")
    ok("NAO_IP = %s" % nao_ip)
    return nao_ip


# ── 2. ΕΛΕΓΧΟΣ ΒΙΒΛΙΟΘΗΚΩΝ ────────────────────────────────────────────────────

def check_dependencies():
    missing = []
    packages = {
        "flask":               "flask",
        "requests":            "requests",
        "paramiko":            "paramiko",
        "speech_recognition":  "SpeechRecognition",
        "dotenv":              "python-dotenv",
    }
    # Τουλάχιστον ένα από τα δύο Gemini SDK
    has_genai = False
    try:
        from google import genai  # noqa: F401
        has_genai = True
    except ImportError:
        pass
    if not has_genai:
        try:
            import google.generativeai  # noqa: F401
            has_genai = True
        except ImportError:
            pass

    for module, pkg in packages.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(pkg)

    if not has_genai:
        missing.append("google-genai")

    if missing:
        err("Λείπουν βιβλιοθήκες: %s" % ", ".join(missing))
        err("Τρέξε:  pip install %s" % " ".join(missing))
        sys.exit(1)
    ok("Όλες οι βιβλιοθήκες υπάρχουν.")


# ── 3. ΕΛΕΓΧΟΣ ΣΥΝΔΕΣΙΜΟΤΗΤΑΣ NAO ────────────────────────────────────────────

def check_nao_reachable(nao_ip):
    info("Έλεγχος σύνδεσης με το NAO (%s:22)..." % nao_ip)
    try:
        sock = socket.create_connection((nao_ip, 22), timeout=4)
        sock.close()
        ok("NAO είναι προσβάσιμο στο %s." % nao_ip)
    except (socket.timeout, ConnectionRefusedError, OSError):
        err("Δεν μπορώ να συνδεθώ με το NAO στο %s." % nao_ip)
        err("Βεβαιώσου ότι:")
        err("  • Το NAO είναι ενεργό και στο ίδιο δίκτυο")
        err("  • Η IP στο .env είναι σωστή (τρέχουσα: %s)" % nao_ip)
        sys.exit(1)


# ── 4. ΕΚΚΙΝΗΣΗ FLASK SERVER ───────────────────────────────────────────────────

def wait_for_server(port, timeout=15):
    """Αναμένει μέχρι ο Flask server να ανταποκριθεί."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            sock = socket.create_connection(("127.0.0.1", port), timeout=1)
            sock.close()
            return True
        except (ConnectionRefusedError, OSError):
            time.sleep(0.4)
    return False


def start_server():
    port = int(os.environ.get("PORT", 5000))
    info("Εκκίνηση Flask server (port %d)..." % port)
    proc = subprocess.Popen(
        [sys.executable, str(BASE_DIR / "server.py")],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    if wait_for_server(port):
        ok("Flask server έτοιμος → http://127.0.0.1:%d/dashboard" % port)
    else:
        err("Flask server δεν ξεκίνησε εγκαίρως. Τρέξε 'python3 server.py' χειροκίνητα για να δεις το σφάλμα.")
        proc.terminate()
        sys.exit(1)
    return proc


# ── 5. ΕΚΚΙΝΗΣΗ NAO.PY ────────────────────────────────────────────────────────

def start_nao():
    info("Εκκίνηση nao.py (κύριος βρόχος συνομιλίας)...\n")
    # Τρέχει στο foreground ώστε ο χρήστης να βλέπει τα logs
    try:
        subprocess.run([sys.executable, str(BASE_DIR / "nao.py")])
    except KeyboardInterrupt:
        pass


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    print()
    print(BOLD + CYAN + "=" * 55 + RESET)
    print(BOLD + CYAN + "   NAO + Gemini  |  Εκκίνηση Συστήματος" + RESET)
    print(BOLD + CYAN + "=" * 55 + RESET)
    print()

    nao_ip = check_env()
    check_dependencies()
    check_nao_reachable(nao_ip)

    print()
    server_proc = start_server()

    print()
    print(BOLD + "  Πες '" + GREEN + "καλημέρα" + RESET + BOLD + "' ή '" + GREEN + "ναο" + RESET + BOLD + "' για να ξεκινήσεις." + RESET)
    print(BOLD + "  Πες '" + RED    + "αντίο"    + RESET + BOLD + "' για να σταματήσεις τη συνομιλία." + RESET)
    print(BOLD + "  Ctrl+C για πλήρη τερματισμό." + RESET)
    print()

    try:
        start_nao()
    finally:
        info("Τερματισμός Flask server...")
        server_proc.terminate()
        server_proc.wait(timeout=5)
        ok("Σύστημα τερματίστηκε ομαλά.")


if __name__ == "__main__":
    main()
