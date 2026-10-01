import asyncio
import datetime
import io
import os
import time
import threading
import edge_tts
import pandas as pd
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file

load_dotenv()

app = Flask(__name__)

# ---------------------------------------------------------
# 1. ТОХИРГОО БОЛОН API ТҮЛХҮҮРҮҮД (.env-ээс авна)
# ---------------------------------------------------------
CHIMEGE_TOKEN = os.environ.get("CHIMEGE_TOKEN", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
GOOGLE_DOC_WEBHOOK_URL = os.environ.get("GOOGLE_DOC_WEBHOOK_URL", "")

SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQQqpigfilNtgTowUFvZS3zn6QwUX0eb3IHdQV-of1-j4BJVycqCUWMvo9u8N6AcEwAi3g7pjTjfP6p/pubhtml"
DATA_FILE = "school_data.txt"

SCHEDULE_DF = None
LAST_FETCH_TIME = None

teacher_cooldowns = {}
pending_greetings = []
COOLDOWN_SECONDS = 60

last_ble_ping = 0


# ---------------------------------------------------------
# 2. МЭДЭЭЛЭЛ БОЛОН САНАЛ ХҮСЭЛТИЙН ФУНКЦҮҮД
# ---------------------------------------------------------
def send_to_google_doc(feedback_text):
    if not GOOGLE_DOC_WEBHOOK_URL:
        return False
    try:
        payload = {"feedback": feedback_text}
        res = requests.post(GOOGLE_DOC_WEBHOOK_URL, json=payload, timeout=10)
        return res.status_code == 200
    except Exception as e:
        print(f"❌ Google Doc алдаа: {e}")
    return False


def clean_sheet_url(url):
    if "pubhtml" in url:
        return url.replace("pubhtml", "pub?output=csv")
    if "/pub?" in url and "output=csv" not in url:
        return url + "&output=csv"
    return url


def sync_schedule_data():
    global SCHEDULE_DF, LAST_FETCH_TIME
    now = datetime.datetime.now()

    if (
        SCHEDULE_DF is not None
        and LAST_FETCH_TIME
        and (now - LAST_FETCH_TIME).seconds < 900
    ):
        return SCHEDULE_DF

    target_url = clean_sheet_url(SHEET_CSV_URL)

    try:
        res = requests.get(target_url, timeout=10)
        res.encoding = "utf-8"
        if res.status_code == 200:
            df = pd.read_csv(io.StringIO(res.text))
            df.columns = df.columns.str.strip()
            SCHEDULE_DF = df
            LAST_FETCH_TIME = now
            return SCHEDULE_DF
    except Exception as e:
        print(f"❌ Google Sheet алдаа: {e}")

    return SCHEDULE_DF


def get_school_general_info():
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return content
    return "Сургуулийн ерөнхий мэдээлэл хараахан оруулаагүй байна."


def build_smart_context(user_question, current_day, current_time):
    df = sync_schedule_data()
    general_info = get_school_general_info()

    context_text = f"--- СУРГУУЛИЙН ЕРӨНХИЙ МЭДЭЭЛЭЛ БОЛОН ЖУРАМ ---\n{general_info}\n\n"
    context_text += f"--- ЦАГ ХУГАЦААНЫ МЭДЭЭЛЭЛ ---\nӨнөөдөр: {current_day} гараг | Одоогийн цаг: {current_time}\n\n"

    if df is not None and not df.empty:
        context_text += "--- ХИЧЭЭЛИЙН ХУВААРИЙН МЭДЭЭЛЭЛ ---\n"
        teacher_col = next((col for col in df.columns if "багш" in col.lower()), None)
        teacher_match = False

        if teacher_col:
            for teacher in df[teacher_col].dropna().unique():
                if str(teacher).lower().strip() in user_question.lower():
                    t_data = df[df[teacher_col] == teacher]
                    context_text += (
                        f"\n[{teacher} багшийн нийт хуваарь]:\n"
                        + t_data.to_string(index=False)
                        + "\n"
                    )
                    teacher_match = True

        if not teacher_match:
            context_text += (
                "\n[Сургуулийн нийт хичээлийн хуваарь]:\n"
                + df.to_string(index=False)
                + "\n"
            )
    else:
        context_text += "--- ХИЧЭЭЛИЙН ХУВААРИЙН МЭДЭЭЛЭЛ ---\nХичээлийн хуваарийн дата одоогоор татагдаагүй байна.\n"

    return context_text


# ---------------------------------------------------------
# 3. OPENROUTER AI ХЭСЭГ
# ---------------------------------------------------------
def generate_ai_response(user_question, context_text, current_day, current_time):
    if not OPENROUTER_API_KEY:
        return "Алдаа: OPENROUTER_API_KEY олдсонгүй. .env файлаа шалгана уу."

    system_instruction = f"""Чи бол сургуулийн мэдээллийн ухаалаг туслах AI.

ДОР ӨГСӨН МЭДЭЭЛЛИЙГ АШИГЛАЖ ХАРИУЛ:
{context_text}

СТРИКТ ДҮРЭМ:
1. Хэрэв хэрэглэгч санал, хүсэлт, гомдол хэлж байгаа бол: "Таны санал хүсэлтийг хүлээн авч сургуулийн захиргаанд хадгаллаа. Баярлалаа!" гэж хариул.
2. Багшийн байршил, хичээлийн хуваарь асуувал "ХИЧЭЭЛИЙН ХУВААРИЙН МЭДЭЭЛЭЛ" хэсгээс харна.
3. Сургуулийн журам, төлбөр, захиргаа, бусад асуултад "СУРГУУЛИЙН ЕРӨНХИЙ МЭДЭЭЛЭЛ" хэсгээс хариулна.
4. Хэрэв сайн уу, баяртай гэх мэт энгийн мэндчилгээ байвал найрсгаар товч хариулна.
5. Хариултыг дуу болон текстээр уншихад тохиромжтой, ЦЭВЭР 1-2 ӨГҮҮЛБЭРТ багтаан монгол хэлээр хариул.
6. Код, тусгай тэмдэгт, өөрийн бодолт хэвлэж болохгүй.
"""

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY.strip()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://ai-sambar.onrender.com",
        "X-Title": "School AI Assistant",
    }

    candidate_models = [
        "google/gemini-2.5-flash",
        "google/gemini-flash-1.5",
        "openrouter/auto",
    ]

    last_error = ""

    for model_name in candidate_models:
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": user_question},
            ],
        }

        try:
            res = requests.post(url, headers=headers, json=payload, timeout=15)
            if res.status_code == 200:
                data = res.json()
                return data["choices"][0]["message"]["content"].strip()
            else:
                last_error = f"[{res.status_code}] {res.text}"
        except Exception as e:
            last_error = str(e)
            continue

    return f"AI хариулт авахад алдаа гарлаа: {last_error}"


# ---------------------------------------------------------
# 4. FLASK ROUTE БОЛОН АУДИО МЭДЭЭЛЭЛ
# ---------------------------------------------------------
async def text_to_speech_edge(text, output_file):
    communicate = edge_tts.Communicate(text, "mn-MN-YesuiNeural")
    await communicate.save(output_file)


def generate_beacon_tts_async(greeting_text, audio_path, mac, now):
    """Beacon-ийн дууг арын фоноор үүсгэж сэрвэр гацахаас сэргийлнэ."""
    try:
        asyncio.run(text_to_speech_edge(greeting_text, audio_path))
        clean_mac = mac.replace(":", "")
        pending_greetings.append({
            "text": greeting_text,
            "audio_url": f"/static/greeting_{clean_mac}.mp3?t={int(now)}",
            "timestamp": now,
        })
        print(f"📢 [Beacon] Мэндчилгээ бэлэн боллоо: {greeting_text}")
    except Exception as e:
        print(f"❌ Beacon TTS алдаа: {e}")


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/school-data", methods=["GET", "POST"])
def manage_school_data():
    if request.method == "POST":
        data = request.json.get("data", "")
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            f.write(data)
        return jsonify({"status": "success", "message": "Мэдээлэл хадгалагдлаа!"})

    context = get_school_general_info()
    return jsonify({"data": context})


@app.route("/api/process-voice", methods=["POST"])
def process_voice():
    question_text = ""

    if "audio" in request.files:
        audio_file = request.files["audio"]
        audio_data = audio_file.read()

        # Бага хэмжээтэй аудио ирсэн тохиолдолд
        if len(audio_data) < 1000:
            return jsonify({"error": "Аудио файл хэт богино байна. Товчлуурыг сайн дарж байгаад ярина уу!"}), 400

        stt_url = "https://api.chimege.com/v1.2/transcribe"
        stt_headers = {
            "Token": CHIMEGE_TOKEN,
            "token": CHIMEGE_TOKEN,
            "Content-Type": "application/octet-stream",
            "Punctuate": "true",
        }

        try:
            stt_res = requests.post(stt_url, data=audio_data, headers=stt_headers, timeout=15)
            stt_res.encoding = "utf-8"
            if stt_res.status_code == 200:
                try:
                    res_json = stt_res.json()
                    question_text = res_json.get("text", stt_res.text).strip()
                except Exception:
                    question_text = stt_res.text.strip()
            else:
                return jsonify({"error": f"Chimege STT алдаа [{stt_res.status_code}]: {stt_res.text}"}), 400
        except Exception as e:
            return jsonify({"error": f"Chimege STT холболтын алдаа: {str(e)}"}), 500

    elif request.json and "text" in request.json:
        question_text = request.json.get("text", "").strip()

    if not question_text:
        return jsonify({"error": "Асуулт тодорхой сонсогдсонгүй. Товчоо дарж байгаад ахин тод асууна уу."}), 400

    feedback_keywords = ["санал", "гомдол", "хүсэлт", "гомдолтой", "хүсэж байна", "шүүмж"]
    if any(keyword in question_text.lower() for keyword in feedback_keywords):
        send_to_google_doc(f"Хэрэглэгчийн санал/хүсэлт: \"{question_text}\"")

    tz_mn = datetime.timezone(datetime.timedelta(hours=8))
    now = datetime.datetime.now(tz_mn)
    days_mn = ["Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба", "Ням"]
    current_day = days_mn[now.weekday()]
    current_time = now.strftime("%H:%M")

    context_text = build_smart_context(question_text, current_day, current_time)

    try:
        ai_answer = generate_ai_response(question_text, context_text, current_day, current_time)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    has_audio = False
    try:
        if os.path.exists("response.mp3"):
            try:
                os.remove("response.mp3")
            except Exception:
                pass
        asyncio.run(text_to_speech_edge(ai_answer, "response.mp3"))
        has_audio = True
    except Exception as e:
        print(f"TTS Алдаа: {e}")

    return jsonify({
        "question": question_text,
        "answer": ai_answer,
        "audio_url": "/api/audio-response" if has_audio else None,
    })


@app.route("/api/audio-response")
def get_audio():
    if os.path.exists("response.mp3"):
        return send_file("response.mp3", mimetype="audio/mpeg")
    return jsonify({"error": "Аудио файл олдсонгүй"}), 404


# ---------------------------------------------------------
# 5. ESP32 BEACON & BLE ROUTES
# ---------------------------------------------------------
@app.route("/api/beacon-presence", methods=["POST"])
def handle_beacon():
    global last_ble_ping
    last_ble_ping = time.time()

    data = request.json or {}
    teacher_name = data.get("teacher", "Багш")
    mac = data.get("mac", "").lower()

    if not mac:
        return jsonify({"status": "ignored"}), 400

    now = time.time()
    last_seen = teacher_cooldowns.get(mac, 0)

    if now - last_seen > COOLDOWN_SECONDS:
        teacher_cooldowns[mac] = now
        greeting_text = f"{teacher_name} багш аа, тавтай морил!"

        os.makedirs("static", exist_ok=True)
        clean_mac = mac.replace(":", "")
        audio_filename = f"greeting_{clean_mac}.mp3"
        audio_path = os.path.join("static", audio_filename)

        threading.Thread(
            target=generate_beacon_tts_async,
            args=(greeting_text, audio_path, mac, now),
            daemon=True
        ).start()

        return jsonify({"status": "success", "message": greeting_text})

    return jsonify({"status": "ignored", "reason": "cooldown_active"})


@app.route("/api/ble-ping", methods=["POST"])
def ble_ping():
    global last_ble_ping
    last_ble_ping = time.time()
    return jsonify({"status": "pong"})


@app.route("/api/ble-status", methods=["GET"])
def get_ble_status():
    global last_ble_ping
    is_connected = (time.time() - last_ble_ping) < 25
    return jsonify({"connected": is_connected})


@app.route("/api/get-greeting", methods=["GET"])
def get_greeting():
    now = time.time()
    while pending_greetings and (now - pending_greetings[0].get("timestamp", now) > 30):
        pending_greetings.pop(0)

    if pending_greetings:
        greeting = pending_greetings.pop(0)
        return jsonify({
            "has_greeting": True,
            "text": greeting["text"],
            "audio_url": greeting["audio_url"],
        })
    return jsonify({"has_greeting": False})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, threaded=True)
