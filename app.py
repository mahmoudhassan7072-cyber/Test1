from flask import Flask, request, jsonify, send_from_directory, abort
from flask_cors import CORS
import os
import requests
 
# --- Paths / static ---
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")
 
# --- Flask app ---
app = Flask(__name__, static_folder=FRONTEND_DIR, static_url_path="")
CORS(app)
 
# --- ElevenLabs credentials ---
# Keep both to be compatible with your current env usage
ELEVEN_AGENT_ID = os.environ.get("ELEVENLABS_AGENT_ID")
ELEVEN_AGENT_KEY = os.environ.get("ELEVENLABS_AGENT_KEY") or os.environ.get("ELEVENLABS_API_KEY")
 
# (Optional) If you also want to use plain TTS later, you can rely on ELEVENLABS_API_KEY too:
ELEVEN_API_KEY = os.environ.get("ELEVENLABS_API_KEY") or ELEVEN_AGENT_KEY
 
 
# -------------------------
# Static + health
# -------------------------
 
@app.route("/")
def serve_frontend():
    return send_from_directory(FRONTEND_DIR, "index.html")
 
@app.route("/health")
def health():
    return jsonify({"status": "ok"}), 200
 
 
# -------------------------
# NEW: Signed URL endpoint for ElevenLabs Agents WebSocket
# -------------------------
# The browser calls this; server uses your API key to obtain a short‑lived signed WS URL.
# Then the browser connects with that URL (no API key exposed client‑side).
@app.get("/eleven/signed-url")
def get_signed_url():
    agent_id = request.args.get("agent_id") or ELEVEN_AGENT_ID
    if not agent_id:
        abort(400, "agent_id is required (query string or ELEVENLABS_AGENT_ID env)")
 
    if not ELEVEN_API_KEY:
        abort(500, "ELEVENLABS_API_KEY (or ELEVENLABS_AGENT_KEY) is not set on the server")
 
    try:
        r = requests.get(
            "https://api.elevenlabs.io/v1/convai/conversation/get-signed-url",
            params={"agent_id": agent_id},
            headers={"xi-api-key": ELEVEN_API_KEY},
            timeout=15,
        )
        r.raise_for_status()
    except requests.HTTPError as e:
        # Return ElevenLabs error response body for easier debugging
        return jsonify({"error": "elevenlabs_error", "status": r.status_code, "details": r.text}), r.status_code
    except Exception as e:
        return jsonify({"error": "server_error", "details": str(e)}), 500
 
    return jsonify(r.json())  # -> { "signed_url": "wss://api.elevenlabs.io/...&token=..." }
 
 
# -------------------------
# Your existing /alexis route (kept; minor hardening)
# -------------------------
@app.route("/alexis", methods=["POST"])
def alexis():
    if not ELEVEN_AGENT_ID or not ELEVEN_AGENT_KEY:
        return jsonify({"error": "Missing ElevenLabs credentials in environment variables"}), 500
 
    data = request.json or {}
    user_text = (data.get("text") or "").strip()
    if not user_text:
        return jsonify({"error": "No text provided"}), 400
 
    url = "https://api.elevenlabs.io/v1/convai/conversation"
    headers = {
        "xi-api-key": ELEVEN_AGENT_KEY,
        "Content-Type": "application/json",
    }
    payload = {
        "input": user_text,
        "agent_id": ELEVEN_AGENT_ID,
        "conversation_id": "default",
    }
 
    print("DEBUG: Sending request to ElevenLabs with text:", user_text)
    try:
        r = requests.post(url, headers=headers, json=payload, timeout=30)
    except Exception as e:
        return jsonify({"error": "request_exception", "details": str(e)}), 502
 
    print("DEBUG: ELEVENLABS RAW RESPONSE:", r.status_code, r.text)
    if not r.ok:
        return jsonify({
            "error": "ElevenLabs request failed",
            "status_code": r.status_code,
            "details": r.text
        }), 502
 
    # Try parse JSON safely
    try:
        response = r.json()
    except Exception:
        # Fallback if API returned non-JSON body
        return jsonify({"text": "", "audio": ""}), 200
 
    # Normalize response shape
    output = response.get("output", {}) if isinstance(response, dict) else {}
    if isinstance(output, list):
        output = output[0] if output else {}
 
    # Prefer 'output.text', fallback to top-level 'text'
    text = ""
    if isinstance(output, dict):
        text = output.get("text", "")
    if not text and isinstance(response, dict):
        text = response.get("text", "")
 
    # Try to locate audio (string/base64) in common fields
    audio = ""
    if isinstance(output, dict):
        audio = output.get("audio") or output.get("audio_base64") or ""
    if not audio and isinstance(response, dict):
        audio = response.get("audio") or response.get("audio_base64") or ""
 
    print("TEXT RETURNED:", text)
    print("AUDIO LENGTH:", len(audio) if isinstance(audio, str) else 0)
 
    return jsonify({"text": text, "audio": audio})
 
 
# -------------------------
# Fly-friendly server binding
# -------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
