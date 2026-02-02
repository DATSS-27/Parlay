import os
import json
import requests
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
)

from engine import factor_scores, final_decision
from formatter import telegram_formatter
from hdp_engine import hdp_suggestion

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")      
PORT = int(os.getenv("PORT", 8080))       

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
    1, 2, 3, 39, 61, 78, 88, 98, 113, 119, 140, 144, 253, 292, 307
}

HEADERS = {"x-apisports-key": API_KEY}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("BOT")

# ================= UTIL =================
def _today_str():
    return datetime.now(WITA).strftime("%Y-%m-%d")


def fixture_cache_path():
    return os.path.join(CACHE_DIR, f"fixtures_{_today_str()}.json")


def prediction_cache_path(fid: int):
    return os.path.join(CACHE_DIR, f"prediction_{fid}.json")

def safe_get(url, **kwargs):
    for _ in range(2):
        try:
            r = requests.get(url, **kwargs)
            r.raise_for_status()
            return r
        except Exception:
            continue
    raise


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
    r = safe_get(
        f"{API_URL}/fixtures",
        headers=HEADERS,
        params={"date": _today_str(), "status": "NS", "timezone": TIMEZONE},
        timeout=15
    )
    r.raise_for_status()
    return r.json()["response"]


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

# ================= HANDLERS =================
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    users = load_users()
    cid = str(update.effective_chat.id)
    user = update.effective_user

    if cid not in users:
        users[cid] = {
            "username": user.username,
            "first_seen": datetime.now(WITA).isoformat()
        }
        save_users(users)

        for admin in ADMIN_IDS:
            await context.bot.send_message(
                admin,
                f"👤 USER BARU\nID: `{cid}`\n@{user.username}",
                parse_mode="Markdown"
            )

    await update.message.reply_text(
        "🤖 Bot Prediksi Aktif\nGunakan /prediksi atau /rekomendasi"
    )


async def prediksi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:    
        auto_cleanup_cache()
            fixtures = get_fixtures()
            now = datetime.now(WITA)
    
        for f in fixtures:
            if datetime.fromisoformat(f["kickoff"]) < now:
                continue
    
            pred = get_prediction(f)
            if not pred:
                continue
    
            text = telegram_formatter(
                fixture=f,
                decision=final_decision(pred),
                home_scores=factor_scores(pred, "home"),
                away_scores=factor_scores(pred, "away")
            )
    
            await update.message.reply_text(text, parse_mode="Markdown")
    except Exception:
        logger.exception("Error saat prediksi")
        await update.message.reply_text(
            "⚠️ Terjadi error saat memproses prediksi. Coba lagi nanti."
        )

async def rekomendasi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        auto_cleanup_cache()
        fixtures = get_fixtures()
        now = datetime.now(WITA)
    
        lines = [
            "🧠 *REKOMENDASI HARI INI*",
            f"📅 {now.strftime('%d %B %Y')}",
            "━━━━━━━━━━━━━━━━━━━━"
        ]
    
        idx = 1
        for f in fixtures:
            if datetime.fromisoformat(f["kickoff"]) < now:
                continue
    
            pred = get_prediction(f)
            if not pred:
                continue
    
            d = final_decision(pred)
            hdp = hdp_suggestion(pred)
    
            lines.append(
                f"{idx}️⃣ *{f['home']} vs {f['away']}*\n"
                f"🎯 PICK: {d['pick']}\n"
                f"📈 Confidence: {d['confidence']}\n"
                f"⚖️ HDP: HOME {hdp['hdp_home']} | AWAY {hdp['hdp_away']}\n"
            )
            idx += 1
    
        await update.message.reply_text("\n".join(lines), parse_mode="Markdown")
    except Exception:
        logger.exception("Error saat prediksi")
        await update.message.reply_text(
            "⚠️ Terjadi error saat memproses prediksi. Coba lagi nanti."
        )
# ================= REGISTER =================
def register_handlers(app):
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("prediksi", prediksi))
    app.add_handler(CommandHandler("rekomendasi", rekomendasi))

# ================= ENTRY POINT (WEBHOOK) =================
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN belum diset")

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    register_handlers(app)

    logger.info("Bot running via webhook")

    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=WEBHOOK_URL,
    )


if __name__ == "__main__":
    main()




