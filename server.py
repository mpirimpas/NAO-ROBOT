# -*- coding: utf-8 -*-
import csv
import json
import os
import re
import time
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, render_template, send_file

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

app = Flask(__name__, template_folder="templates")

# ---------- LOGS ----------
BASE_DIR      = Path(__file__).resolve().parent
LOGS_DIR      = BASE_DIR / "logs"
LOGS_DIR.mkdir(parents=True, exist_ok=True)
CSV_LOG_FILE  = LOGS_DIR / "conversations.csv"
JSON_LOG_FILE = LOGS_DIR / "conversation_history.json"

if not CSV_LOG_FILE.exists():
    with open(CSV_LOG_FILE, mode="w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(["timestamp", "session_id", "user_text", "robot_response", "emotion", "latency_ms", "status"])

# ---------- ΜΝΗΜΗ ΣΥΝΟΜΙΛΙΩΝ ----------
active_sessions          = {}
MAX_SESSION_HISTORY_TURNS = 10

# ---------- LIVE STATE ----------
live_state = {
    "state":          "standby",
    "last_emotion":   "neutral",
    "last_latency_ms": 0,
    "last_update":    datetime.now().strftime("%H:%M:%S"),
    "session_id":     "default_session",
    "turn_count":     0,
}

# ---------- SYSTEM PROMPT ----------
ROBOT_SYSTEM_INSTRUCTION = (
    "Είσαι το κοινωνικό ανθρωποειδές ρομπότ NAO. Συνομιλείς προφορικά σε πραγματικό χρόνο με έναν άνθρωπο.\n"
    "Κανόνες:\n"
    "1. Απάντα στα Ελληνικά με φυσικό, φιλικό και εκφραστικό προφορικό λόγο.\n"
    "2. Η απάντησή σου θα διαβαστεί από TTS. ΜΗΝ χρησιμοποιείς Markdown (όχι αστερίσκους, λίστες, τίτλους, emojis). Μόνο καθαρό κείμενο.\n"
    "3. Κράτα τις απαντήσεις σύντομες (1-2 προτάσεις, max 3).\n"
    "4. Επέστρεψε αυστηρά JSON με δύο πεδία:\n"
    "   - 'response': το κείμενο που θα πει το ρομπότ.\n"
    "   - 'emotion': ΑΠΟΚΛΕΙΣΤΙΚΑ ένα από: ['happy','excited','curious','empathetic','sad','serious','neutral'].\n"
    "Παράδειγμα: {\"response\": \"Γεια σου! Χαίρομαι που σε βλέπω.\", \"emotion\": \"happy\"}"
)

VALID_EMOTIONS = {"happy", "excited", "curious", "empathetic", "sad", "serious", "neutral"}

# ---------- GEMINI SDK ----------
use_new_sdk = False
client      = None
model       = None


def init_gemini():
    """Αρχικοποίηση Gemini SDK (google-genai ή fallback σε google-generativeai)."""
    global client, model, use_new_sdk
    api_key = os.environ.get("GEMINI_API_KEY", "").strip()
    if not api_key:
        try:
            from dotenv import load_dotenv
            load_dotenv(override=True)
            api_key = os.environ.get("GEMINI_API_KEY", "").strip()
        except Exception:
            pass

    try:
        from google import genai
        client = genai.Client(api_key=api_key) if api_key else genai.Client()
        use_new_sdk = True
        print("[SERVER] google-genai SDK.")
        return
    except ImportError:
        pass

    try:
        import google.generativeai as legacy_genai
        if api_key:
            legacy_genai.configure(api_key=api_key)
        model = legacy_genai.GenerativeModel(
            model_name="gemini-2.0-flash",
            system_instruction=ROBOT_SYSTEM_INSTRUCTION,
            generation_config={"response_mime_type": "application/json"},
        )
        use_new_sdk = False
        print("[SERVER] google-generativeai SDK (legacy).")
    except ImportError:
        print("[SERVER] ΠΡΟΕΙΔΟΠΟΙΗΣΗ: Δεν βρέθηκε κανένα Gemini SDK.")


init_gemini()


# ---------- ΒΟΗΘΗΤΙΚΕΣ ----------

def clean_for_tts(text):
    """Αφαιρεί markdown σύμβολα που δεν πρέπει να προφέρει το TTS."""
    if not text:
        return ""
    text = re.sub(r'[*_#`~]', '', text)
    text = re.sub(r'^\s*[-+•]\s*', '', text, flags=re.MULTILINE)
    return re.sub(r'\s+', ' ', text).strip()


def parse_gemini_json(raw):
    """Αποκωδικοποιεί JSON απάντηση του Gemini → (response_text, emotion)."""
    if not raw:
        return "", "neutral"
    try:
        m = re.search(r'\{.*\}', raw, re.DOTALL)
        if m:
            data    = json.loads(m.group(0))
            text    = clean_for_tts(data.get("response", ""))
            emotion = data.get("emotion", "neutral").lower().strip()
            return text, emotion if emotion in VALID_EMOTIONS else "neutral"
    except Exception:
        pass
    return clean_for_tts(raw), "neutral"


def log_interaction(session_id, user_text, robot_response, emotion, latency_ms, status="SUCCESS"):
    """Καταγράφει αλληλεπίδραση σε CSV και JSON."""
    timestamp = datetime.now().isoformat()
    try:
        with open(CSV_LOG_FILE, mode="a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([timestamp, session_id, user_text, robot_response, emotion, round(latency_ms, 2), status])
    except Exception as e:
        print("[LOG CSV ERROR]: %s" % e)
    try:
        data = []
        if JSON_LOG_FILE.exists() and JSON_LOG_FILE.stat().st_size > 0:
            with open(JSON_LOG_FILE, "r", encoding="utf-8") as f:
                try:
                    data = json.load(f)
                except Exception:
                    data = []
        data.append({
            "timestamp":      timestamp,
            "session_id":     session_id,
            "user_text":      user_text,
            "robot_response": robot_response,
            "emotion":        emotion,
            "latency_ms":     round(latency_ms, 2),
            "status":         status,
        })
        with open(JSON_LOG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print("[LOG JSON ERROR]: %s" % e)


def _log_count():
    if JSON_LOG_FILE.exists() and JSON_LOG_FILE.stat().st_size > 0:
        try:
            with open(JSON_LOG_FILE, "r", encoding="utf-8") as f:
                d = json.load(f)
                return len(d) if isinstance(d, list) else 0
        except Exception:
            pass
    return 0


def _call_gemini(user_prompt, session_history):
    """Καλεί το Gemini API και επιστρέφει (reply_text, emotion)."""
    history_slice = session_history[-MAX_SESSION_HISTORY_TURNS:]
    while history_slice and history_slice[0].get("role") != "user":
        history_slice = history_slice[1:]

    if use_new_sdk and client is not None:
        from google.genai import types

        contents = []
        for item in history_slice:
            parts = item.get("parts", [])
            txt   = parts[0].get("text", "") if parts and isinstance(parts[0], dict) else str(parts[0]) if parts else ""
            if txt:
                contents.append(types.Content(role=item.get("role", "user"), parts=[types.Part.from_text(text=txt)]))
        contents.append(types.Content(role="user", parts=[types.Part.from_text(text=user_prompt)]))

        response = client.models.generate_content(
            model="gemini-2.0-flash",
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=ROBOT_SYSTEM_INSTRUCTION,
                response_mime_type="application/json",
                temperature=0.7,
                max_output_tokens=300,
            ),
        )
        return parse_gemini_json(response.text or "")

    if model is not None:
        legacy_history = []
        for item in history_slice:
            parts = item.get("parts", [])
            txt   = parts[0].get("text", "") if parts and isinstance(parts[0], dict) else str(parts[0]) if parts else ""
            if txt:
                legacy_history.append({"role": item.get("role", "user"), "parts": [txt]})
        chat_obj = model.start_chat(history=legacy_history)
        return parse_gemini_json(chat_obj.send_message(user_prompt).text or "")

    raise RuntimeError("Gemini SDK δεν έχει αρχικοποιηθεί.")


# ---------- ROUTES ----------

@app.route("/")
@app.route("/dashboard")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/live_status", methods=["GET"])
def get_live_status():
    history    = []
    session_id = live_state.get("session_id", "default_session")
    if JSON_LOG_FILE.exists() and JSON_LOG_FILE.stat().st_size > 0:
        try:
            with open(JSON_LOG_FILE, "r", encoding="utf-8") as f:
                all_logs = json.load(f)
            session_logs = [x for x in all_logs if x.get("session_id") == session_id]
            history      = [] if (session_id in active_sessions and not active_sessions[session_id]) else session_logs[-20:]
        except Exception:
            pass
    return jsonify({**live_state, "history": history})


@app.route("/api/set_state", methods=["POST"])
def set_state():
    data = request.get_json(force=True, silent=True) or {}
    if data.get("state"):
        live_state["state"] = data["state"]
    if "emotion" in data:
        live_state["last_emotion"] = data["emotion"]
    if "session_id" in data:
        live_state["session_id"] = data["session_id"]
    live_state["last_update"] = datetime.now().strftime("%H:%M:%S")
    return jsonify({"status": "OK", "current_state": live_state["state"]})


@app.route("/chat", methods=["POST"])
def chat():
    start_time = time.time()
    session_id = "unknown"
    user_prompt = ""
    try:
        data = request.get_json(force=True, silent=True)
        if not data or "text" not in data:
            return jsonify({"response": "Δεν έλαβα κάποιο μήνυμα.", "emotion": "curious", "status": "BAD_REQUEST"}), 400

        user_prompt = data["text"].strip()
        session_id  = data.get("session_id", "default_session")

        if not user_prompt:
            return jsonify({"response": "Το μήνυμα ήταν κενό.", "emotion": "neutral", "status": "EMPTY_MESSAGE"}), 400

        live_state.update({"state": "thinking", "session_id": session_id, "last_update": datetime.now().strftime("%H:%M:%S")})
        print("[NAO → SERVER] (%s): %s" % (session_id, user_prompt))

        if session_id not in active_sessions:
            active_sessions[session_id] = []

        if client is None and model is None:
            init_gemini()

        reply_text, emotion = _call_gemini(user_prompt, active_sessions[session_id])

        latency_ms = (time.time() - start_time) * 1000

        active_sessions[session_id].append({"role": "user",  "parts": [{"text": user_prompt}]})
        active_sessions[session_id].append({"role": "model", "parts": [{"text": reply_text}]})

        live_state.update({
            "state":          "speaking",
            "last_emotion":   emotion,
            "last_latency_ms": round(latency_ms),
            "turn_count":     live_state["turn_count"] + 1,
            "last_update":    datetime.now().strftime("%H:%M:%S"),
        })

        log_interaction(session_id, user_prompt, reply_text, emotion, latency_ms)
        print("[SERVER → NAO] [%s] (%dms): %s" % (emotion, round(latency_ms), reply_text))

        return jsonify({"response": reply_text, "emotion": emotion, "latency_ms": round(latency_ms), "status": "SUCCESS"})

    except Exception as e:
        latency_ms = (time.time() - start_time) * 1000
        print("[SERVER ERROR]: %s" % e)
        error_msg = "Συγγνώμη, δυσκολεύομαι να επεξεργαστώ την απάντηση αυτή τη στιγμή."
        log_interaction(session_id, user_prompt, error_msg, "sad", latency_ms, "EXCEPTION: %s" % e)
        live_state["state"] = "standby"
        return jsonify({"response": error_msg, "emotion": "sad", "latency_ms": round(latency_ms), "status": "SERVER_ERROR"}), 500


@app.route("/reset", methods=["POST"])
def reset_session():
    data       = request.get_json(force=True, silent=True) or {}
    session_id = data.get("session_id", "default_session")
    active_sessions[session_id] = []
    live_state.update({
        "state":          "standby",
        "turn_count":     0,
        "last_emotion":   "neutral",
        "last_latency_ms": 0,
        "last_update":    datetime.now().strftime("%H:%M:%S"),
    })
    print("[SERVER] Session '%s' εκκαθαρίστηκε." % session_id)
    return jsonify({"status": "RESET_OK", "session_id": session_id})


@app.route("/history", methods=["GET"])
def get_history():
    if JSON_LOG_FILE.exists():
        try:
            with open(JSON_LOG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            return jsonify({"count": len(data), "history": data[-50:]})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return jsonify({"count": 0, "history": []})


@app.route("/export/csv", methods=["GET"])
def export_csv():
    if CSV_LOG_FILE.exists():
        return send_file(CSV_LOG_FILE, as_attachment=True, download_name="conversations.csv")
    return jsonify({"error": "Το αρχείο CSV δεν υπάρχει ακόμα."}), 404


@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":            "ok",
        "sdk":               "google-genai" if (use_new_sdk and client) else ("google-generativeai" if model else "none"),
        "api_key_set":       bool(os.environ.get("GEMINI_API_KEY", "").strip()),
        "active_sessions":   list(active_sessions.keys()),
        "log_entries_count": _log_count(),
        "live_state":        live_state,
    })


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print("\n" + "=" * 55)
    print(" 🚀 Dashboard: http://localhost:%d/dashboard" % port)
    print("=" * 55 + "\n")
    app.run(host="0.0.0.0", port=port, debug=True)
