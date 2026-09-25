import asyncio
import datetime
import io
import os
import edge_tts
import google.generativeai as genai
import pandas as pd
import requests
from flask import Flask, jsonify, render_template, request, send_file

app = Flask(__name__)

# ---------------------------------------------------------
# ТОХИРГОО БОЛОН API ТҮЛХҮҮРҮҮД
# ---------------------------------------------------------
CHIMEGE_TOKEN = (
    "8daf6c65eb98bf17d6c92e9bcb933f2f12e347909a8bc4a3ff751177295cdf2a"
)
GEMINI_API_KEY = (
    "AQ.Ab8RN6J_YnmZEIiDUD2pjxKAazXSuS-j9QvOymUQigxIvBIDRA"  # <-- Энд өөрийн Gemini API түлхүүрээ оруулна
)

genai.configure(api_key=GEMINI_API_KEY)

# Google Sheet URL
SHEET_CSV_URL = "https://docs.google.com/spreadsheets/d/e/2PACX-1vQQqpigfilNtgTowUFvZS3zn6QwUX0eb3IHdQV-of1-j4BJVycqCUWMvo9u8N6AcEwAi3g7pjTjfP6p/pubhtml"
DATA_FILE = "school_data.txt"

# Кэшлэх хувьсагчид
SCHEDULE_DF = None
LAST_FETCH_TIME = None


def clean_sheet_url(url):
  """pubhtml холбоосыг автоматаар CSV татах pub?output=csv холбоос руу хөрвүүлнэ."""
  if "pubhtml" in url:
    return url.replace("pubhtml", "pub?output=csv")
  if "/pub?" in url and "output=csv" not in url:
    return url + "&output=csv"
  return url


def sync_schedule_data():
  """15 минут тутамд Google Sheet-ээс хуваарийг шинэчилж санамжинд авна."""
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
      print(f"❌ Холболтын алдаа status code: {res.status_code}")
  except Exception as e:
    print(f"❌ Google Sheet татахад алдаа гарлаа: {e}")

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


def generate_ai_response(
    user_question, context_text, current_day, current_time
):
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

  candidate_models = []
  try:
    for m in genai.list_models():
      if "generateContent" in m.supported_generation_methods:
        candidate_models.append(m.name)
  except Exception as e:
    print(f"Моделийн жагсаалт авахад алдаа: {e}")

  if not candidate_models:
    candidate_models = [
        "gemini-2.0-flash",
        "gemini-1.5-flash",
        "models/gemini-2.0-flash",
        "models/gemini-1.5-flash",
    ]

  last_error = ""

  for model_name in candidate_models:
    try:
      model = genai.GenerativeModel(
          model_name=model_name, system_instruction=system_instruction
      )
      response = model.generate_content(user_question)
      if response and response.text:
        clean_text = response.text.strip()
        lines = [
            line.strip() for line in clean_text.split("\n") if line.strip()
        ]
        return lines[-1] if lines else clean_text
    except Exception as e:
      last_error = str(e)
      continue

  return f"Хариулт авахад алдаа гарлаа: {last_error}"


async def text_to_speech_edge(text, output_file):
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
    # Аргументын дарааллыг зассан: (question_text, context_text, current_day, current_time)
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
  app.run(host="0.0.0.0", port=5000, debug=True)

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, ssl_context='adhoc')