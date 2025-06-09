import time
import pandas as pd
import asyncio
import random
import os
from datetime import datetime, timedelta
from io import BytesIO

from playwright.sync_api import sync_playwright

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# === KONFIGURASI BOT TELEGRAM ===
TOKEN = os.environ.get("BOT_TOKEN")

# === SCRAPE DENGAN PLAYWRIGHT ===
def scrape_predictions_by_date(target_date: str):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        page.goto("https://www.rowdie.co.uk/predictions/", timeout=60000)
        page.wait_for_selector(".match__date-formatted", timeout=15000)

        prev_count = -1
        while True:
            date_elements = page.query_selector_all(".match__date-formatted")
            current_count = sum(1 for el in date_elements if el.inner_text().strip() == target_date)
            if current_count == prev_count and current_count > 0:
                break
            prev_count = current_count
            try:
                load_more = page.query_selector(".anwp-fl-btn__load-more")
                if not load_more or not load_more.is_visible():
                    break
                load_more.click()
                page.wait_for_selector(".anwp-fl-spinner", state="hidden", timeout=15000)
            except:
                break

        data = []
        current_league = "Tanpa Liga"
        container = page.query_selector(".match-list--shortcode")
        if not container:
            browser.close()
            return []

        for child in container.query_selector_all(":scope > *"):
            class_name = child.get_attribute("class") or ""
            if "anwp-fl-block-header" in class_name:
                current_league = child.inner_text().strip()
            elif "anwp-fl-game" in class_name:
                try:
                    date_text = child.query_selector(".match__date-formatted").inner_text().strip()
                    if date_text != target_date:
                        continue
                    try:
                        time_text = child.query_selector(".match__time-formatted").inner_text().strip()
                    except:
                        continue
                    datetime_str = f"{date_text} {time_text}"
                    try:
                        match_datetime = datetime.strptime(datetime_str, "%d %B %Y %H:%M")
                    except:
                        continue
                    if match_datetime < datetime.now():
                        continue
                    home = child.query_selector(".match-slim__team-home-title").inner_text().strip()
                    away = child.query_selector(".match-slim__team-away-title").inner_text().strip()
                    pred = child.query_selector(".match-slim__prediction-value")
                    prediction = pred.inner_text().strip() if pred else "N/A"
                    link_el = child.query_selector(".anwp-link-cover")
                    hyperlink = f'=HYPERLINK("{link_el.get_attribute("href")}", "Lihat Prediksi")' if link_el else "N/A"
                    data.append({
                        "Liga": current_league,
                        "Tanggal": date_text,
                        "Waktu": time_text,
                        "Tim Kandang": home,
                        "Tim Tandang": away,
                        "Prediksi": prediction,
                        "Link": hyperlink
                    })
                except Exception as e:
                    print(f"⚠️ Gagal parsing: {e}")
                    continue
        browser.close()
        return data

# === SIMPAN KE 1 SHEET EXCEL ===
def save_to_single_sheet_excel(data, date_label) -> BytesIO:
    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        sheet_name = f"Prediksi_{date_label.replace(' ', '_')}"[:31]
        df.to_excel(writer, sheet_name=sheet_name, index=False)
        # styling (optional)
        ws = writer.sheets[sheet_name]
        for cell in ws[1]:
            cell.font = cell.font.copy(bold=True)
    output.seek(0)
    return output

# === KIRIM FILE EXCEL KE TELEGRAM ===
async def send_excel(chat_id, context: ContextTypes.DEFAULT_TYPE, date_label, data):
    if data:
        excel_file = save_to_single_sheet_excel(data, date_label)
        filename = f"prediksi_{date_label.lower().replace(' ', '_')}.xlsx"
        await context.bot.send_document(
            chat_id=chat_id,
            document=InputFile(excel_file, filename=filename),
            caption=f"📊 Prediksi pertandingan *{date_label}*"
        )
    else:
        await context.bot.send_message(chat_id=chat_id, text=f"⚠️ Tidak ada pertandingan ditemukan untuk *{date_label}*.")

# === PERINTAH /prediksi ===
async def start_prediction(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("📅 Hari Ini", callback_data="today"),
         InlineKeyboardButton("📅 Besok", callback_data="tomorrow")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text("Pilih tanggal prediksi:", reply_markup=reply_markup)

# === TANGANI PILIHAN ===
async def handle_prediction_choice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    now = datetime.now()
    if query.data == "today":
        target_date = now.strftime("%d %B %Y")
        label = "Hari Ini"
    elif query.data == "tomorrow":
        target_date = (now + timedelta(days=1)).strftime("%d %B %Y")
        label = "Besok"
    else:
        await query.edit_message_text("❌ Pilihan tidak dikenali.")
        return
    await query.edit_message_text(f"⚡𝐞𝐤𝐬𝐞𝐤𝐮𝐬𝐢 𝐛𝐨𝐬𝐤𝐮...")
    data = scrape_predictions_by_date(target_date)
    await send_excel(query.message.chat_id, context, label, data)

# === JALANKAN BOT ===
def main():
    app = Application.builder().token(TOKEN).build()
    app.add_handler(CommandHandler("prediksi", start_prediction))
    app.add_handler(CallbackQueryHandler(handle_prediction_choice))
    print("✅ Bot aktif")
    app.run_polling()

if __name__ == "__main__":
    main()
