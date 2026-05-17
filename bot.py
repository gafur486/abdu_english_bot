import os
import base64
import logging
import yt_dlp
import aiohttp
import mutagen.id3 as id3
from mutagen.mp3 import MP3
from pyrogram.client import Client as PyroClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    CallbackQueryHandler, ContextTypes, filters
)

from dotenv import load_dotenv
load_dotenv()

TOKEN = os.getenv("BOT_TOKEN")
API_ID = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")


# Session файлро аз base64 месозем
session_b64 = os.getenv("SESSION_B64")
if session_b64:
    with open("shazam_session.session", "wb") as f:
        f.write(base64.b64decode(session_b64))

SESSION = "shazam_session"

logging.basicConfig(level=logging.INFO)

DOWNLOADS = "downloads"
os.makedirs(DOWNLOADS, exist_ok=True)

FFMPEG = "C:\\ffmpeg\\bin"

user_store = {}

TIKTOK_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Referer": "https://www.tiktok.com/",
}

# Pyrogram client (барои файлҳои калон)
pyro = PyroClient(SESSION, api_id=int(API_ID), api_hash=API_HASH)


# ─── Санҷиши силка ────────────────────────────────────────────────────────────
def is_instagram(url: str) -> bool:
    return "instagram.com" in url or "instagr.am" in url

def is_youtube(url: str) -> bool:
    return "youtube.com" in url or "youtu.be" in url

def is_tiktok(url: str) -> bool:
    return "tiktok.com" in url or "vm.tiktok.com" in url

def is_supported(url: str) -> bool:
    return is_instagram(url) or is_youtube(url) or is_tiktok(url)


# ─── Скачати видео ────────────────────────────────────────────────────────────
async def download_video(url: str, quality: str) -> str | None:
    if quality == "low":
        fmt = "worstvideo[ext=mp4]+worstaudio/worst[ext=mp4]/worst"
    elif quality == "medium":
        fmt = "bestvideo[height<=480][ext=mp4]+bestaudio/best[height<=480]/best"
    else:
        fmt = "bestvideo[ext=mp4]+bestaudio/best[ext=mp4]/best"

    opts = {
        "outtmpl": f"{DOWNLOADS}/%(id)s.%(ext)s",
        "format": fmt,
        "quiet": True,
        "noplaylist": True,
        "ffmpeg_location": FFMPEG,
        "merge_output_format": "mp4",
        "concurrent_fragment_downloads": 4,
        "sleep_interval": 3,
        "max_sleep_interval": 6,
        "http_headers": TIKTOK_HEADERS if is_tiktok(url) else {},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(info)
            if not os.path.exists(path):
                base = os.path.splitext(path)[0]
                for ext in ["mp4", "mkv", "webm"]:
                    if os.path.exists(f"{base}.{ext}"):
                        return f"{base}.{ext}"
            return path
    except Exception as e:
        logging.error(f"Видео хато: {e}")
        return None


# ─── Скачати мусиқӣ ───────────────────────────────────────────────────────────
async def download_audio(url: str) -> str | None:
    opts = {
        "outtmpl": f"{DOWNLOADS}/%(id)s.%(ext)s",
        "format": "bestaudio/best",
        "quiet": True,
        "noplaylist": True,
        "ffmpeg_location": FFMPEG,
        "sleep_interval": 2,
        "http_headers": TIKTOK_HEADERS if is_tiktok(url) else {},
        "postprocessors": [{
            "key": "FFmpegExtractAudio",
            "preferredcodec": "mp3",
            "preferredquality": "192",
        }],
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            base = os.path.splitext(ydl.prepare_filename(info))[0]
            return base + ".mp3"
    except Exception as e:
        logging.error(f"Мусиқӣ хато: {e}")
        return None


# ─── Shazam ───────────────────────────────────────────────────────────────────
async def shazam_recognize(path: str) -> dict | None:
    try:
        shazam = Shazam()
        out = await shazam.recognize(path)
        if not out.get("matches"):
            return None
        track = out.get("track", {})
        title = track.get("title", "Номаълум")
        artist = track.get("subtitle", "Номаълум")
        images = track.get("images", {})
        cover_url = images.get("coverarthq") or images.get("coverart")
        return {"title": title, "artist": artist, "cover_url": cover_url}
    except Exception as e:
        logging.error(f"Shazam хато: {e}")
        return None


# ─── Обложка ──────────────────────────────────────────────────────────────────
async def add_cover_to_mp3(mp3_path: str, cover_url: str, title: str, artist: str):
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(cover_url) as resp:
                cover_data = await resp.read()
        audio = MP3(mp3_path, ID3=id3.ID3)
        try:
            audio.add_tags()
        except Exception:
            pass
        audio.tags["TIT2"] = id3.TIT2(encoding=3, text=title)
        audio.tags["TPE1"] = id3.TPE1(encoding=3, text=artist)
        audio.tags["APIC:"] = id3.APIC(
            encoding=3, mime="image/jpeg",
            type=3, desc="Cover", data=cover_data,
        )
        audio.save()
    except Exception as e:
        logging.error(f"Обложка хато: {e}")


# ─── Pyrogram бо файл фиристодан ─────────────────────────────────────────────
async def send_large_video(chat_id: int, path: str):
    async with pyro:
        await pyro.send_video(chat_id, path)

async def send_large_audio(chat_id: int, path: str, title: str = None, performer: str = None, caption: str = None):
    async with pyro:
        await pyro.send_audio(chat_id, path, title=title, performer=performer, caption=caption)


# ─── /start ───────────────────────────────────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Салом! 👋\n\n"
        "Силкаи Instagram, YouTube ё TikTok бифирист.\n\n"
        "🎬 Видео → сифат интихоб мекунӣ\n"
        "🎵 Мусиқӣ → MP3 + Shazam + обложка\n\n"
        "📦 То 2GB файл қабул мекунам!"
    )


# ─── /help ────────────────────────────────────────────────────────────────────
async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "ℹ️ Дастур:\n\n"
        "1️⃣ Силкаи Instagram, YouTube ё TikTok бифирист\n"
        "2️⃣ 🎬 Видео ё 🎵 Мусиқӣ интихоб кун\n"
        "3️⃣ Барои видео сифат интихоб кун\n"
        "4️⃣ Файлро қабул кун!\n\n"
        "📦 То 2GB файл дастгирӣ мешавад."
    )


# ─── Паём ─────────────────────────────────────────────────────────────────────
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if not is_supported(text):
        await update.message.reply_text("⚠️ Лутфан силкаи Instagram, YouTube ё TikTok бифирист.")
        return

    user_id = update.message.from_user.id
    user_store[user_id] = {"url": text, "chat_id": update.message.chat_id}

    keyboard = [[
        InlineKeyboardButton("🎬 Видео", callback_data="type_video"),
        InlineKeyboardButton("🎵 Мусиқӣ", callback_data="type_audio"),
    ]]
    await update.message.reply_text("Чӣ мехоҳӣ?", reply_markup=InlineKeyboardMarkup(keyboard))


# ─── Callback ─────────────────────────────────────────────────────────────────
async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    user_id = query.from_user.id
    store = user_store.get(user_id)

    if not store:
        await query.edit_message_text("⚠️ Силка ёфт нашуд. Дубора бифирист.")
        return

    data = query.data
    chat_id = store.get("chat_id")

    # ── Видео → сифат ─────────────────────────────────────────────────────────
    if data == "type_video":
        user_store[user_id]["type"] = "video"
        keyboard = [[
            InlineKeyboardButton("🔻 Паст (360p)", callback_data="q_low"),
            InlineKeyboardButton("🔶 Миёна (480p)", callback_data="q_medium"),
            InlineKeyboardButton("🔺 Баланд (1080p)", callback_data="q_high"),
        ]]
        await query.edit_message_text("Сифатро интихоб кун:", reply_markup=InlineKeyboardMarkup(keyboard))
        return

    # ── Мусиқӣ ────────────────────────────────────────────────────────────────
    if data == "type_audio":
        url = store["url"]
        await query.edit_message_text("⏳ Мусиқӣ скачат мешавад...")
        path = await download_audio(url)

        if not path or not os.path.exists(path):
            await query.edit_message_text("❌ Мусиқӣ скачат нашуд.")
            user_store.pop(user_id, None)
            return

        await query.edit_message_text("🎵 Shazam мешиносад...")
        info = await shazam_recognize(path)

        caption = ""
        title = None
        performer = None
        if info:
            title = info["title"]
            performer = info["artist"]
            caption = f"🎵 {title}\n👤 {performer}"
            if info.get("cover_url"):
                await add_cover_to_mp3(path, info["cover_url"], title, performer)

        size = os.path.getsize(path)
        await query.edit_message_text("📤 Мефиристам...")

        if size > 50 * 1024 * 1024:
            # Pyrogram бо файлҳои калон
            await send_large_audio(chat_id, path, title=title, performer=performer, caption=caption)
        else:
            with open(path, "rb") as f:
                await query.message.reply_audio(
                    audio=f,
                    caption=caption if caption else None,
                    title=title,
                    performer=performer,
                )
        await query.delete_message()
        os.remove(path)
        user_store.pop(user_id, None)
        return

    # ── Сифат → скачат ────────────────────────────────────────────────────────
    if data.startswith("q_"):
        quality = data.replace("q_", "")
        url = store.get("url")
        quality_text = {"low": "паст 🔻", "medium": "миёна 🔶", "high": "баланд 🔺"}.get(quality, "")
        await query.edit_message_text(f"⏳ Видео ({quality_text}) скачат мешавад...")

        path = await download_video(url, quality)

        if path and os.path.exists(path):
            size = os.path.getsize(path)
            await query.edit_message_text("📤 Мефиристам...")

            if size > 50 * 1024 * 1024:
                # Pyrogram бо файлҳои калон
                await send_large_video(chat_id, path)
            else:
                with open(path, "rb") as f:
                    await query.message.reply_video(video=f)

            await query.delete_message()
            os.remove(path)
        else:
            await query.edit_message_text("❌ Скачат нашуд. Силкаро санҷ.")

        user_store.pop(user_id, None)


# ─── Асосӣ ───────────────────────────────────────────────────────────────────
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    print("✅ Бот кор мекунад — то 2GB дастгирӣ!")
    app.run_polling()


if __name__ == "__main__":
    main()