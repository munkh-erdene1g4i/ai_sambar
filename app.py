import asyncio
import datetime
import io
import os
import edge_tts
import pandas as pd
import requests
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, send_file

# .env файлд байгаа орчны хувьсагчдыг уншиж санамжинд ачаална
load_dotenv()

app = Flask(__name__)

# ---------------------------------------------------------
# 1. ТОХИРГОО БОЛОН API ТҮЛХҮҮРҮҮД (.env-ээс авна)
# ---------------------------------------------------------
CHIMEGE_TOKEN = os.environ.get("CHIMEGE_TOKEN", "")
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")

# Google Sheet URL болон сургуулийн ерөнхий мэдээллийн файл
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQQqpigfilNtgTowUFvZS3zn6QwUX0eb3IHdQV-of1-j4BJVycqCUWMvo9u8N6AcEwAi3g7pjTjfP6p/pubhtml"
DATA_FILE = "school_data.txt"

# Санамжинд кэшлэх хувьсагчид
SCHEDULE_DF = None
LAST_FETCH_TIME = None


# ---------------------------------------------------------
# 2. МЭДЭЭЛЭЛ БОЛОВСРУУЛАХ ФУНКЦҮҮД
# ---------------------------------------------------------
def clean_sheet_url(url):
    """pubhtml холбоосыг CSV татах форматын холбоос руу хөрвүүлнэ."""
    if "pubhtml" in url:
        return url.replace("pubhtml", "pub?output=csv")
    if "/pub?" in url and "output=csv" not in url:
        return url + "&output=csv"
    return url


def sync_schedule_data():
    """15 минут тутамд Google Sheet-ээс хуваарийг шинэчлэн татна."""
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
            print("✅ Хичээлийн хуваарь амжилттай татагдлаа.")
            return SCHEDULE_DF
        else:
            print(f"❌ Google Sheet холболтын алдаа: status {res.status_code}")
    except Exception as e:
        print(f"❌ Google Sheet татахад алдаа гарлаа: {e}")

    return SCHEDULE_DF


def get_school_general_info():
    """Сургуулийн ерөнхий мэдээллийг файлаас уншина."""
    if os.path.exists(DATA_FILE):
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            content = f.read().strip()
            if content:
                return content
    return "Сургуулийн ерөнхий мэдээлэл хараахан оруулаагүй байна."


def build_smart_context(user_question, current_day, current_time):
    """Хэрэглэгчийн асуултад тохирох контекст мэдээллийг бэлтгэнэ."""
    df = sync_schedule_data()
    general_info = get_school_general_info()

    context_text = f"--- СУРГУУЛИЙН ЕРӨНХИЙ МЭДЭЭЛЭЛ БОЛОН ЖУРАМ ---\n{general_info}\n\n"
    context_text += f"--- ЦАГ ХУГАЦААНЫ МЭДЭЭЛЭЛ ---\nӨнөөдөр: {current_day} гараг | Одоогийн цаг: {current_time}\n\n"

    if df is not None and not df.empty:
        context_text += "--- ХИЧЭЭЛИЙН ХУВААРИЙН МЭДЭЭЛЭЛ ---\n"

        teacher_col = next(
            (col for col in df.columns if "багш" in col.lower()), None
        )
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
def generate_ai_response(
    user_question, context_text, current_day, current_time
):
    """
    OpenRouter API-аар дамжуулан баталгаатай идэвхтэй AI загваруудаас хариулт авна.
    """
    if not OPENROUTER_API_KEY:
        return "Алдаа: OPENROUTER_API_KEY олдсонгүй. .env файлаа шалгана уу."

    masked_key = OPENROUTER_API_KEY[:12] + "..." + OPENROUTER_API_KEY[-4:]
    print(f"🔑 API Key: {masked_key}")

    system_instruction = f"""Чи бол сургуулийн мэдээллийн ухаалаг туслах AI.

ДОР ӨГСӨН МЭДЭЭЛЛИЙГ АШИГЛАЖ ХАРИУЛ:
{context_text}

СТРИКТ ДҮРЭМ:
1. Багшийн байршил, хичээлийн хуваарь асуувал "ХИЧЭЭЛИЙН ХУВААРИЙН МЭДЭЭЛЭЛ" хэсгээс харна.
2. Сургуулийн журам, төлбөр, захиргаа, бусад асуултад "СУРГУУЛИЙН ЕРӨНХИЙ МЭДЭЭЛЭЛ" хэсгээс хариулна.
3. Хэрэв сайн уу, баяртай гэх мэт энгийн мэндчилгээ байвал найрсгаар товч хариулна.
4. Хариултыг дуу болон текстээр уншихад тохиромжтой, ЦЭВЭР 1-2 ӨГҮҮЛБЭРТ багтаан монгол хэлээр хариул.
5. Код, тусгай тэмдэгт, өөрийн бодолт хэвлэж болохгүй.
"""

    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY.strip()}",
        "Content-Type": "application/json",
        "HTTP-Referer": "http://localhost:5000",
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
                print(f"✅ Амжилттай хариулт өгсөн загвар: {model_name}")
                return data["choices"][0]["message"]["content"].strip()
            else:
                print(
                    f"⚠️ {model_name} дээр алдаа гарлаа [{res.status_code}]: {res.text}"
                )
                last_error = f"[{res.status_code}] {res.text}"

        except Exception as e:
            last_error = str(e)
            continue

    return f"AI хариулт авахад алдаа гарлаа: {last_error}"


# ---------------------------------------------------------
# 4. FLASK ROUTE БОЛОН АУДИО МЭДЭЭЛЭЛ
# ---------------------------------------------------------
async def text_to_speech_edge(text, output_file):
    """Edge TTS ашиглан текстийг монгол дуу хоолой болгоно."""
    communicate = edge_tts.Communicate(text, "mn-MN-YesuiNeural")
    await communicate.save(output_file)


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/school-data", methods=["GET", "POST"])
def manage_school_data():
    if request.method == "POST":
        data = request.json.get("data", "")
        with open(DATA_FILE, "w", encoding="utf-8") as f:
            f.write(data)
        return jsonify({
            "status": "success",
            "message": "Ерөнхий мэдээлэл амжилттай хадгалагдлаа!",
        })

    context = get_school_general_info()
    return jsonify({"data": context})


@app.route("/api/process-voice", methods=["POST"])
def process_voice():
    question_text = ""

    if "audio" in request.files:
        audio_file = request.files["audio"]
        audio_data = audio_file.read()

        stt_url = "https://api.chimege.com/v1.2/transcribe"
        stt_headers = {
            "Token": CHIMEGE_TOKEN,
            "token": CHIMEGE_TOKEN,
            "Content-Type": "application/octet-stream",
            "Punctuate": "true",
        }

        try:
            stt_res = requests.post(
                stt_url, data=audio_data, headers=stt_headers, timeout=15
            )
            stt_res.encoding = "utf-8"
            try:
                res_json = stt_res.json()
                question_text = res_json.get("text", stt_res.text).strip()
            except Exception:
                question_text = stt_res.text.strip()
        except Exception as e:
            return (
                jsonify({"error": f"Chimege STT холболтын алдаа: {str(e)}"}),
                500,
            )

    elif request.json and "text" in request.json:
        question_text = request.json.get("text", "").strip()

    if not question_text:
        return (
            jsonify({
                "error": "Асуулт ойлгогдсонгүй. Товчоо дарж байгаад дахин асууна уу."
            }),
            400,
        )

    tz_mn = datetime.timezone(datetime.timedelta(hours=8))
    now = datetime.datetime.now(tz_mn)
    days_mn = ["Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба", "Ням"]
    current_day = days_mn[now.weekday()]
    current_time = now.strftime("%H:%M")

    context_text = build_smart_context(question_text, current_day, current_time)

    try:
        ai_answer = generate_ai_response(
            question_text, context_text, current_day, current_time
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500

    has_audio = False
    try:
        if os.path.exists("response.mp3"):
            os.remove("response.mp3")
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


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
