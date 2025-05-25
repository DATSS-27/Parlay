import time
import pandas as pd
import asyncio
import random
import os
from datetime import datetime, timedelta
from io import BytesIO

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# === KONFIGURASI BOT TELEGRAM ===
#TOKEN = '8179740886:AAEda80_vCtLl_Mv0NP6NbPr162DpeYRtN0'
TOKEN = os.environ.get("BOT_TOKEN")

# === SETUP SELENIUM DRIVER ===
def setup_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(options=options)

# === SCRAPE DENGAN TANGGAL DAN LIGA ===
def scrape_predictions_by_date(target_date: str):
    driver = setup_driver()
    driver.get("https://www.rowdie.co.uk/predictions/")
    time.sleep(5)

    prev_match_count = 0

    while True:
        # Hitung jumlah pertandingan sesuai target_date sebelum load more
        date_elements = driver.find_elements(By.CLASS_NAME, "match__date-formatted")
        current_match_count = sum(
            1 for el in date_elements if el.text.strip() == target_date
        )

        if current_match_count == prev_match_count and current_match_count > 0:
            print("⛔ Tidak ada pertandingan baru untuk tanggal yang dipilih, berhenti.")
            break
        prev_match_count = current_match_count

        try:
            load_more_btn = driver.find_element(By.CLASS_NAME, "anwp-fl-btn__load-more")
            if not load_more_btn.is_displayed():
                print("✅ Tombol 'Load More' tidak ditampilkan lagi.")
                break
            driver.execute_script("arguments[0].click();", load_more_btn)

            # Tunggu spinner selesai
            try:
                WebDriverWait(driver, 10).until(
                    EC.invisibility_of_element_located((By.CLASS_NAME, "anwp-fl-spinner"))
                )
                print("🔁 Load more ditekan.")
            except:
                print("⚠️ Spinner tidak hilang setelah timeout.")
                break

        except:
            print("✅ Tidak ada tombol 'Load More' lagi.")
            break
        
    current_league = "Tanpa Liga"
    data = []
    
    try:
        container = driver.find_element(By.CLASS_NAME, "match-list--shortcode")
        children = container.find_elements(By.XPATH, "./*")
    except Exception as e:
        print(f"⚠️ Gagal menemukan container: {e}")
        driver.quit()
        return []
    

    for element in children:
        class_name = element.get_attribute("class") or ""

        if "anwp-fl-block-header" in class_name:
            current_league = element.text.strip() or "Tanpa Liga"

        elif "anwp-fl-game" in class_name:
            try:
                date_text = element.find_element(By.CLASS_NAME, "match__date-formatted").text.strip()
                if date_text != target_date:
                    continue

                try:
                    time_text = element.find_element(By.CLASS_NAME, "match__time-formatted").text.strip()
                except:
                    print("⚠️ Tidak ada waktu pertandingan, lewati.")
                    continue

                match_datetime_str = f"{date_text} {time_text}"
                try:
                    match_datetime = datetime.strptime(match_datetime_str, "%d %B %Y %H:%M")
                except ValueError:
                    print(f"⚠️ Format waktu tidak dikenali: {match_datetime_str}")
                    continue

                if match_datetime < datetime.now():
                    continue

                home_team = element.find_element(By.CLASS_NAME, "match-slim__team-home-title").text.strip()
                away_team = element.find_element(By.CLASS_NAME, "match-slim__team-away-title").text.strip()

                try:
                    prediction = element.find_element(By.CLASS_NAME, "match-slim__prediction-value").text.strip()
                except:
                    prediction = "N/A"

                try:
                    match_link = element.find_element(By.CLASS_NAME, "anwp-link-cover").get_attribute("href")
                    hyperlink = f'=HYPERLINK("{match_link}", "Lihat Prediksi")'
                except:
                    hyperlink = "N/A"

                data.append({
                    "Liga": current_league,
                    "Tanggal": date_text,
                    "Waktu": time_text,
                    "Tim Kandang": home_team,
                    "Tim Tandang": away_team,
                    "Prediksi": prediction,
                    "Link": hyperlink
                })

            except Exception as e:
                print(f"⚠️ Gagal parsing pertandingan: {e}")
                continue

    driver.quit()
    return data

# === SIMPAN KE 1 SHEET EXCEL ===
def save_to_single_sheet_excel(data, date_label) -> BytesIO:
    df = pd.DataFrame(data)
    output = BytesIO()

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        sheet_name = f"Prediksi_{date_label.replace(' ', '_')}"[:31]
        df.to_excel(writer, sheet_name=sheet_name, index=False)

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
        [
            InlineKeyboardButton("📅 Hari Ini", callback_data="today"),
            InlineKeyboardButton("📅 Besok", callback_data="tomorrow"),
        ]
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
