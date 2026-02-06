import os
import json
import requests
import logging
import asyncio
from datetime import datetime, timedelta, date
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from engine import factor_scores, final_decision, sync_confidence
from formatter import telegram_formatter_technical, telegram_formatter_full
from hdp_engine import hdp_suggestion, hdp_confidence

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")      
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise RuntimeError("API_KEY belum diset di environment")
    
ADMIN_IDS = {7952198349}

API_URL = "https://v3.football.api-sports.io"
TIMEZONE = "Asia/Makassar"
WITA = ZoneInfo(TIMEZONE)

CACHE_DIR = os.getenv("CACHE_DIR", "/app/cache")
os.makedirs(CACHE_DIR, exist_ok=True)

ALLOWED_LEAGUES = {
    1, 2, 3, 39, 61, 78, 88, 98, 113, 119, 135, 140, 144, 253, 292, 307
}
SUPPORTED_LEAGUES_TEXT = (
    "*Bot ini hanya menganalisa 15 liga / kejuaraan berikut:*\n\n"
    "World Cup\n"
    "🇪🇺 UEFA Champions League\n"
    "🇪🇺 UEFA Europa League\n"
    "🇬🇧 Premier League\n"
    "🇫🇷 Ligue 1\n"
    "🇮🇹 Serie A\n"
    "🇩🇪 Bundesliga\n"
    "🇳🇱 Eredivisie\n"
    "🇯🇵 J1 League\n"
    "🇸🇪 Allsvenskan\n"
    "🇩🇰 Superliga\n"
    "🇪🇸 La Liga\n"
    "🇧🇪 Jupiler Pro League\n"
    "🇺🇸 MLS\n"
    "🇰🇷 K League 1\n"
    "🇸🇦 Pro League\n\n"
    "⚠️ Liga lain tidak dianalisa."
)

HEADERS = {"x-apisports-key": API_KEY}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

logger = logging.getLogger("BOT")

# Matikan spam polling log
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)

MAX_MSG_LEN = 3800  # aman, di bawah limit telegram

async def send_long_message(update, text, parse_mode="Markdown"):
    chunk = ""
    for line in text.split("\n"):
        if len(chunk) + len(line) + 1 > MAX_MSG_LEN:
            await update.message.reply_text(chunk, parse_mode=parse_mode)
            chunk = line + "\n"
        else:
            chunk += line + "\n"

    if chunk.strip():
        await update.message.reply_text(chunk, parse_mode=parse_mode)

# ================= UTIL =================
def _today_str():
    return datetime.now(WITA).strftime("%Y-%m-%d")

def _date_str(offset_days: int = 0):
    return (datetime.now(WITA) + timedelta(days=offset_days)).strftime("%Y-%m-%d")

def fixture_cache_path():
    return os.path.join(CACHE_DIR, f"fixtures_{_today_str()}.json")

def prediction_cache_path(fid: int):
    return os.path.join(CACHE_DIR, f"prediction_{fid}.json")

def extract_confidence_percent(conf_str) -> int:
    try:
        return int(str(conf_str).split("(")[1].replace("%)", ""))
    except Exception:
        return 50
        
def safe_get(url, timeout=15, **kwargs):
    last_exc = None
    for _ in range(2):
        try:
            r = requests.get(url, timeout=timeout, **kwargs)
            r.raise_for_status()
            return r
        except Exception as e:
            last_exc = e
    raise last_exc

USERS_FILE = os.path.join(CACHE_DIR, "users.json")
# ================= CACHE CLEANUP =================
LAST_CLEANUP = None


def auto_cleanup_cache():
    global LAST_CLEANUP
    now = datetime.now(WITA)

    if LAST_CLEANUP and (now - LAST_CLEANUP).seconds < 3600:
        return

    LAST_CLEANUP = now

    for f in os.listdir(CACHE_DIR):
        path = os.path.join(CACHE_DIR, f)
        try:
            if f.startswith("fixtures_") and _today_str() not in f:
                os.remove(path)

            elif f.startswith("prediction_"):
                with open(path) as jf:
                    payload = json.load(jf)
                if now >= datetime.fromisoformat(payload["expires_at"]):
                    os.remove(path)
        except Exception:
            pass

# ================= USERS =================
def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    with open(USERS_FILE) as f:
        return json.load(f)


def save_users(data):
    with open(USERS_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ================= FIXTURE =================
def fetch_fixtures():
    fixtures = []

    for offset in (0, 1):  # hari ini & besok
        r = safe_get(
            f"{API_URL}/fixtures",
            headers=HEADERS,
            params={
                "date": _date_str(offset),
                "status": "NS",
                "timezone": TIMEZONE
            },
            timeout=15
        )
        r.raise_for_status()
        fixtures.extend(r.json()["response"])

    return fixtures


def get_fixtures():
    path = fixture_cache_path()
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)

    raw = fetch_fixtures()
    fixtures = []

    for f in raw:
        if f["league"]["id"] not in ALLOWED_LEAGUES:
            continue

        kickoff = datetime.fromisoformat(
            f["fixture"]["date"].replace("Z", "+00:00")
        ).astimezone(WITA)

        fixtures.append({
            "fixture_id": f["fixture"]["id"],
            "kickoff": kickoff.isoformat(),
            "league_name": f["league"]["name"],
            "home": f["teams"]["home"]["name"],
            "away": f["teams"]["away"]["name"],
        })

    fixtures.sort(key=lambda x: x["kickoff"])
    with open(path, "w") as f:
        json.dump(fixtures, f)

    return fixtures

# ================= PREDICTION =================
def get_prediction(fixture):
    fid = fixture["fixture_id"]
    path = prediction_cache_path(fid)

    if os.path.exists(path):
        with open(path) as f:
            payload = json.load(f)
        if datetime.now(WITA) < datetime.fromisoformat(payload["expires_at"]):
            return payload["data"]
        os.remove(path)

    r = safe_get(
        f"{API_URL}/predictions",
        headers=HEADERS,
        params={"fixture": fid},
        timeout=15
    )
    r.raise_for_status()

    data = r.json()["response"]
    if not data:
        return None
    
    expires_at = (
        datetime.fromisoformat(fixture["kickoff"]) - timedelta(minutes=30)
    ).isoformat()
    
    with open(path, "w") as f:
        json.dump({
            "expires_at": expires_at,
            "data": data[0]
        }, f)

    return data[0]

def collect_predictions():
    auto_cleanup_cache()
    fixtures = get_fixtures()
    now = datetime.now(WITA)

    results = []

    for f in fixtures:
        if datetime.fromisoformat(f["kickoff"]) < now:
            continue

        pred = get_prediction(f)
        if not pred:
            continue

        results.append((f, pred))

    return results

def hdp_confidence_label(score: float):
    if score >= 75:
        return "🟢 Sangat Kuat"
    elif score >= 60:
        return "🟡 Cukup Aman"
    elif score >= 45:
        return "🟠 Spekulatif"
    else:
        return "🔴 Hindari"

# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    cid = str(update.effective_chat.id)
    user = update.effective_user

    if cid not in users:
        # simpan sementara, belum lengkap
        context.user_data["awaiting_nickname"] = True

        users[cid] = {
            "username": user.username,
            "first_seen": datetime.now(WITA).isoformat(),
            "nickname": None
        }
        save_users(users)

        await update.message.reply_text(
            "👋 Halo!\n*Sebelum mulai, boleh minta ente pe nama?*",
            parse_mode="Markdown"
        )
        return

    await update.message.reply_text(
        "🤖 Welcome kembali!\n"
        "Gunakan /prediksi atau /jadwal\n\n"
        + SUPPORTED_LEAGUES_TEXT,
        parse_mode="Markdown"
    )

async def nickname_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_nickname"):
        return

    nickname = update.message.text.strip()
    if len(nickname) > 10:
        await update.message.reply_text("Boleh dpe nama yang singkat jo 🙂")
        return

    users = load_users()
    cid = str(update.effective_chat.id)

    if cid in users:
        users[cid]["nickname"] = nickname
        save_users(users)

    context.user_data.pop("awaiting_nickname", None)

    await update.message.reply_text(
        f"✅ Sip, WELCOME *{nickname}* si penjudi!\n\n"
        "Gunakan /prediksi atau /jadwal\n\n"
        + SUPPORTED_LEAGUES_TEXT,
        parse_mode="Markdown"
    )

async def prediksi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        results = collect_predictions()

        if not results:
            await update.message.reply_text("❌ Tidak ada prediksi tersedia.")
            return

        for f, pred in results:
            decision = final_decision(pred)
            hdp = hdp_suggestion(pred)
            hdp_info = hdp_confidence(
                hdp_resp=hdp,
                home_xg=hdp.get("home_xg", 0),
                away_xg=hdp.get("away_xg", 0),
            )
        
            winner_conf = extract_confidence_percent(decision["confidence"])
            sync = sync_confidence(winner_conf, hdp_info["score"])
        
            text = telegram_formatter_full(
                fixture=f,
                home_scores=factor_scores(pred, "home"),
                away_scores=factor_scores(pred, "away"),
                decision=decision,
                hdp=hdp,
                hdp_info=hdp_info,
                sync=sync,
            )
        
            await update.message.reply_text(text, parse_mode="Markdown")
            await asyncio.sleep(0.35)  # anti flood


    except Exception:
        logger.exception("Error saat prediksi")
        await update.message.reply_text(
            "⚠️ Terjadi error saat memproses prediksi. Coba lagi nanti."
        )


async def jadwal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        auto_cleanup_cache()
        fixtures = get_fixtures()
        now = datetime.now(WITA)

        lines = [
            "📅 *JADWAL PERTANDINGAN*",
            "Hari ini & Besok",
            "━━━━━━━━━━━━━━━━━━━━"
        ]

        count = 0
        for f in fixtures:
            kickoff = datetime.fromisoformat(f["kickoff"])
            if kickoff < now:
                continue

            lines.append(
                f"⚽ *{f['home']} vs {f['away']}*\n"
                f"🏆 {f['league_name']} | ⏰ {kickoff.strftime('%d %b %H:%M')} WITA\n"
            )

            count += 1

        if count == 0:
            await update.message.reply_text(
                "❌ Tidak ada jadwal pertandingan."
            )
            return

        await send_long_message(
            update,
            "\n".join(lines),
            parse_mode="Markdown"
        )

    except Exception:
        logger.exception("Error saat mengambil jadwal")
        await update.message.reply_text(
            "⚠️ Terjadi error saat mengambil jadwal. Coba lagi nanti."
        )

# ================= REGISTER =================
def register_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("jadwal", jadwal))
    app.add_handler(CommandHandler("prediksi", prediksi))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, nickname_handler))


# ================= ENTRY POINT (WEBHOOK) =================
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN belum diset")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    register_handlers(app)

    logger.info("🤖 Bot running via polling (Railway safe mode)")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES,
        close_loop=False
    )


if __name__ == "__main__":
    main()



























