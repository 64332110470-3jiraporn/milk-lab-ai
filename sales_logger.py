import fcntl
import json
import os
from datetime import datetime
from pathlib import Path

import gspread
from dotenv import load_dotenv
from oauth2client.service_account import ServiceAccountCredentials
from telegram.ext import Updater, CommandHandler

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env", override=False)

# =========================
# CONFIG
# =========================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "7840750377:AAG0PFsKz08IcT_D8snaXmocsxLccrcfALU")
GOOGLE_CREDENTIAL_FILE = os.getenv("GOOGLE_CREDENTIAL_FILE", "credentials.json")
SHEET_ID = os.getenv("SHEET_ID", "1YRgQjPXUvhhm8rXO8TwZmjP9kNUmwsDktCwYdrPyNEs")
SHEET_NAME = os.getenv("SHEET_NAME", "Sales")
SHEET_WORKSHEET = os.getenv("SHEET_WORKSHEET", "Sheet1")

# =========================
# CONNECT GOOGLE SHEETS
# =========================
scope = [
    "https://spreadsheets.google.com/feeds",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
    "https://www.googleapis.com/auth/drive",
]

sheet = None
sheet_error = None


def get_service_account_email():
    try:
        with open(GOOGLE_CREDENTIAL_FILE, "r", encoding="utf-8") as handle:
            return json.load(handle).get("client_email", "service account")
    except Exception:
        return "service account"


def handle_sheet_error(update, action, error):
    detail = str(error)
    lowered = detail.lower()

    if "permission" in lowered or "forbidden" in lowered or "403" in lowered:
        message = (
            f"ไม่สามารถ{action}ได้ตอนนี้ เพราะ service account ไม่มีสิทธิ์แก้ไขสเปรดชีต\n"
            f"กรุณาแชร์สเปรดชีตให้กับอีเมล {get_service_account_email()}"
        )
    else:
        message = f"ไม่สามารถ{action}ได้ตอนนี้: {detail}"

    update.message.reply_text(message)


def connect_google_sheet():
    global sheet, sheet_error

    sheet = None
    sheet_error = None

    try:
        creds = ServiceAccountCredentials.from_json_keyfile_name(
            GOOGLE_CREDENTIAL_FILE, scope
        )
        client = gspread.authorize(creds)

        if SHEET_ID:
            spreadsheet = client.open_by_key(SHEET_ID)
            sheet = spreadsheet.worksheet(SHEET_WORKSHEET)
            print(f"Connected to Google Sheet via ID: {SHEET_ID} -> {SHEET_WORKSHEET}")
        else:
            spreadsheet = client.open(SHEET_NAME)
            sheet = spreadsheet.sheet1
            print(f"Connected to Google Sheet: {SHEET_NAME}")
    except Exception as exc:  # pragma: no cover - runtime guard
        sheet_error = str(exc)
        print(f"Warning: Could not connect to Google Sheets: {sheet_error}")


connect_google_sheet()


# =========================
# /start
# =========================
def start(update, context):
    message = (
        "ยินดีต้อนรับร้านนม\n\n"
        "ใช้คำสั่ง:\n"
        "/sale เมนู จำนวน ราคา\n"
        "ตัวอย่าง:\n"
        "/sale ลาเต้น้ำผึ้ง 5 65\n\n"
        "ดูยอดขายวันนี้:\n"
        "/today"
    )

    if sheet is None:
        message += "\n\n⚠️ ตอนนี้เชื่อม Google Sheets ไม่สำเร็จ จะบันทึกไม่ได้ในขณะนี้"

    update.message.reply_text(message)


# =========================
# /sale
# =========================
def sale(update, context):
    if sheet is None:
        update.message.reply_text(
            "ไม่สามารถบันทึกขายได้ตอนนี้ เพราะเชื่อม Google Sheets ไม่สำเร็จ\n"
            f"รายละเอียด: {sheet_error or 'ตรวจไฟล์ credentials.json และสิทธิ์ของสเปรดชีต'}"
        )
        return

    try:
        if len(context.args) < 3:
            update.message.reply_text(
                "ใช้ /sale เมนู จำนวน ราคา\nเช่น /sale ลาเต้น้ำผึ้ง 5 65"
            )
            return

        menu = " ".join(context.args[:-2])
        qty = int(context.args[-2])
        price = float(context.args[-1])
        total = qty * price

        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        sheet.append_row([now, menu, qty, int(price), int(total)])

        update.message.reply_text(
            f"บันทึกสำเร็จ\n"
            f"เมนู: {menu}\n"
            f"จำนวน: {qty}\n"
            f"ราคา: {int(price)} บาท\n"
            f"รวม: {int(total)} บาท"
        )

    except ValueError:
        update.message.reply_text("จำนวนและราคาต้องเป็นตัวเลข")
    except Exception as exc:
        handle_sheet_error(update, "บันทึกข้อมูล", exc)


# =========================
# /today
# =========================
def today(update, context):
    if sheet is None:
        update.message.reply_text(
            "ยังไม่สามารถดูยอดขายวันนี้ได้ เพราะเชื่อม Google Sheets ไม่สำเร็จ\n"
            f"รายละเอียด: {sheet_error or 'ตรวจไฟล์ credentials.json และสิทธิ์ของสเปรดชีต'}"
        )
        return

    try:
        records = sheet.get_all_records()

        today_date = datetime.now().strftime("%Y-%m-%d")

        total = 0
        count = 0

        for row in records:
            if str(row["Date"]).startswith(today_date):
                total += float(row["Total"])
                count += 1

        update.message.reply_text(
            f"สรุปยอดขายวันนี้\n"
            f"จำนวนรายการ: {count}\n"
            f"ยอดรวม: {int(total)} บาท"
        )
    except Exception as exc:
        handle_sheet_error(update, "ดูยอดขาย", exc)


# =========================
# MAIN
# =========================
def main():
    lock_path = Path(__file__).resolve().parent / ".sales_logger.lock"
    lock_file = open(lock_path, "w", encoding="utf-8")

    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print("Another sales logger instance is already running. Exiting.")
        lock_file.close()
        return

    updater = Updater(TELEGRAM_TOKEN, use_context=True)

    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("sale", sale))
    dp.add_handler(CommandHandler("today", today))

    updater.start_polling()

    print("Milk Sales Bot Started...")

    try:
        updater.idle()
    finally:
        lock_file.close()
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass


if __name__ == "__main__":
    main()

