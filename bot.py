import os
import sys
import base64
import logging
import warnings
import yt_dlp
import aiohttp
import asyncio

warnings.filterwarnings("ignore", message=r".*TgCrypto is missing.*", category=UserWarning)
logging.basicConfig(level=logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("telegram").setLevel(logging.WARNING)
logging.getLogger("pyrogram.crypto.aes").setLevel(logging.ERROR)
asyncio.set_event_loop(asyncio.new_event_loop())

from pyrogram.client import Client as PyroClient
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Conflict
from telegram.ext import (
    ApplicationBuilder, MessageHandler, CommandHandler,
    CallbackQueryHandler, ContextTypes, filters
)
from dotenv import load_dotenv
load_dotenv()

# ─── Танзимот ─────────────────────────────────────────────────────────────────
TOKEN    = os.getenv("BOT_TOKEN")
API_ID   = os.getenv("API_ID")
API_HASH = os.getenv("API_HASH")

session_b64 = os.getenv("SESSION_B64")
if session_b64:
    with open("user_session.session", "wb") as f:
        f.write(base64.b64decode(session_b64))

SESSION   = os.getenv("SESSION") or "user_session"
DOWNLOADS = "downloads"
FFMPEG    = os.getenv("FFMPEG_PATH") or ("/usr/bin" if not sys.platform.startswith("win") else None)
COOKIES   = "cookies.txt" if os.path.exists("cookies.txt") else None

os.makedirs(DOWNLOADS, exist_ok=True)
logging.basicConfig(level=logging.INFO)

# ─── Pyrogram ─────────────────────────────────────────────────────────────────
pyro = PyroClient(SESSION, api_id=int(API_ID), api_hash=API_HASH)

# ─── Ёрдамчи функсияҳо ────────────────────────────────────────────────────────
def detect_platform(url: str) -> str | None:
    url = url.lower()
    if "instagram.com" in url or "instagr.am" in url:
        return "instagram"
    if "youtube.com" in url or "youtu.be" in url:
        return "youtube"
    if "tiktok.com" in url or "vm.tiktok.com" in url:
        return "tiktok"
    return None

PLATFORM_EMOJI = {
    "instagram": "📸 Instagram",
    "youtube":   "▶️ YouTube",
    "tiktok":    "🎵 TikTok",
}

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.tiktok.com/",
}

# ─── Скачати видео ────────────────────────────────────────────────────────────
async def download_video(url: str, quality: str) -> str | None:
    fmt_map = {
        "low":    "worstvideo[ext=mp4]+worstaudio/worst[ext=mp4]/worst",
        "medium": "bestvideo[height<=480][ext=mp4]+bestaudio/best[height<=480]/best",
        "high":   "bestvideo[ext=mp4]+bestaudio/best[ext=mp4]/best",
    }
    opts = {
        "outtmpl":                      f"{DOWNLOADS}/%(id)s.%(ext)s",
        "format":                       fmt_map.get(quality, fmt_map["high"]),
        "quiet":                        True,
        "noplaylist":                   True,
        "merge_output_format":          "mp4",
        "concurrent_fragment_downloads": 4,
        "http_headers":                 HEADERS,
    }
    if FFMPEG:
        opts["ffmpeg_location"] = FFMPEG
    if COOKIES:
        opts["cookiefile"] = COOKIES
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(info)
            if not os.path.exists(path):
                base = os.path.splitext(path)[0]
                for ext in ["mp4", "mkv", "webm"]:
                    candidate = f"{base}.{ext}"
                    if os.path.exists(candidate):
                        return candidate
                return None
            return path
    except Exception as e:
        logging.error(f"[VIDEO] {e}")
        return None

# ─── Скачати аудио ────────────────────────────────────────────────────────────
async def download_audio(url: str) -> tuple[str | None, dict]:
    """Аудиои воқеиро скачат мекунад ва маълумоти трекро бармегардонад."""
    opts = {
        "outtmpl":           f"{DOWNLOADS}/%(id)s.%(ext)s",
        "format":            "bestaudio/best",
        "quiet":             True,
        "noplaylist":        True,
        "merge_output_format": "mp4",
        "http_headers":      HEADERS,
    }
    if FFMPEG:
        opts["ffmpeg_location"] = FFMPEG
    meta = {}
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(url, download=True)
            path = ydl.prepare_filename(info)
            if not os.path.exists(path):
                base = os.path.splitext(path)[0]
                for ext in ["mp4", "m4a", "webm", "opus", "aac", "ogg", "mp3"]:
                    candidate = f"{base}.{ext}"
                    if os.path.exists(candidate):
                        path = candidate
                        break
            meta = {
                "title":    info.get("title", ""),
                "uploader": info.get("uploader") or info.get("channel", ""),
                "duration": info.get("duration", 0),
                "platform": detect_platform(url),
            }
            return path, meta
    except Exception as e:
        logging.error(f"[AUDIO] {e}")
        return None, {}

# ─── Pyrogram — файлҳои калон ────────────────────────────────────────────────
async def send_large_video(chat_id: int, path: str):
    async with pyro:
        await pyro.send_video(chat_id, path)

async def send_large_audio(chat_id: int, path: str, title: str = "", performer: str = "", caption: str = ""):
    async with pyro:
        await pyro.send_audio(chat_id, path, title=title, performer=performer, caption=caption)

# ─── Форматкунии вақт ─────────────────────────────────────────────────────────
def fmt_duration(seconds: int) -> str:
    if not seconds:
        return ""
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    return f"{h}:{m:02}:{s:02}" if h else f"{m}:{s:02}"

# ─── Захираи корбар ───────────────────────────────────────────────────────────
user_store: dict = {}

# ═══════════════════════════════════════════════════════════════════════════════
#  ХАНДЛЕРҲО
# ═══════════════════════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "👋 *Хуш омадед!*\n\n"
        "Ман метавонам видео ва мусиқӣ аз:\n"
        "📸 *Instagram* • ▶️ *YouTube* • 🎵 *TikTok*\n\n"
        "──────────────────────\n"
        "📌 *Чӣ тавр истифода бурдан:*\n"
        "1️⃣ Силкаро ирсол кунед\n"
        "2️⃣ Видео ё мусиқиро интихоб кунед\n"
        "3️⃣ Барои видео сифат интихоб кунед\n"
        "4️⃣ Файлро қабул кунед ✅\n\n"
        "📦 *То 2GB* файл дастгирӣ мешавад!\n"
        "──────────────────────\n"
        "❓ Ёрдам: /help"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = (
        "📖 *Дастур*\n\n"
        "🔗 *Силкаҳои дастгирӣшаванда:*\n"
        "• instagram.com / instagr.am\n"
        "• youtube.com / youtu.be\n"
        "• tiktok.com / vm.tiktok.com\n\n"
        "🎬 *Видео:* 3 сифат — паст / миёна / баланд\n"
        "🎵 *Мусиқӣ:* MP4 (аудио ҳамчун видео)\n\n"
        "──────────────────────\n"
        "⚠️ *Огоҳӣ:* Баъзе видеоҳои хусусӣ\n"
        "скачат намешаванд.\n\n"
        "🤖 Аз /start оғоз кунед"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    url = update.message.text.strip()
    platform = detect_platform(url)

    if not platform:
        await update.message.reply_text(
            "⚠️ *Силка эътироф нашуд.*\n\n"
            "Лутфан силкаи дурусти:\n"
            "📸 Instagram • ▶️ YouTube • 🎵 TikTok\n"
            "ирсол кунед.",
            parse_mode="Markdown"
        )
        return

    uid = update.message.from_user.id
    user_store[uid] = {"url": url, "chat_id": update.message.chat_id, "platform": platform}

    platform_label = PLATFORM_EMOJI[platform]
    keyboard = [[
        InlineKeyboardButton("🎬 Видео", callback_data="type_video"),
        InlineKeyboardButton("🎵 Мусиқӣ", callback_data="type_audio"),
    ]]
    await update.message.reply_text(
        f"✅ *{platform_label}* силка қабул шуд.\n\nЧӣ мехоҳед?",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )


async def handle_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    uid   = query.from_user.id
    store = user_store.get(uid)

    if not store:
        await query.edit_message_text("⚠️ Силка ёфт нашуд. Лутфан дубора ирсол кунед.")
        return

    data     = query.data
    url      = store["url"]
    chat_id  = store["chat_id"]
    platform = store.get("platform", "")
    plabel   = PLATFORM_EMOJI.get(platform, "")

    # ── Видео → сифат ──────────────────────────────────────────────────────────
    if data == "type_video":
        user_store[uid]["type"] = "video"
        keyboard = [[
            InlineKeyboardButton("🔻 Паст (360p)",  callback_data="q_low"),
            InlineKeyboardButton("🔶 Миёна (480p)", callback_data="q_medium"),
            InlineKeyboardButton("🔺 Баланд (HD)",  callback_data="q_high"),
        ]]
        await query.edit_message_text(
            f"🎬 *Видео* — {plabel}\n\nСифатро интихоб кунед:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode="Markdown"
        )
        return

    # ── Мусиқӣ ─────────────────────────────────────────────────────────────────
    if data == "type_audio":
        await query.edit_message_text(
            f"⏳ *{plabel}* — мусиқӣ (видео) скачат мешавад...\n\n"
            "🔄 Лутфан интизор шавед.",
            parse_mode="Markdown"
        )

        path, meta = await download_audio(url)

        if not path or not os.path.exists(path):
            await query.edit_message_text(
                "❌ *Мусиқӣ скачат нашуд.*\n\n"
                "Сабабҳои эҳтимолӣ:\n"
                "• Видео хусусӣ аст\n"
                "• Силка нодуруст аст\n\n"
                "Силкаро санҷед ва дубора кӯшиш кунед.",
                parse_mode="Markdown"
            )
            user_store.pop(uid, None)
            return

        title     = meta.get("title", "")
        performer = meta.get("uploader", "")
        duration  = fmt_duration(meta.get("duration", 0))
        size_mb   = os.path.getsize(path) / (1024 * 1024)

        caption = f"🎵 *{title}*"
        if performer:
            caption += f"\n👤 {performer}"
        if duration:
            caption += f"\n⏱ {duration}"
        caption += f"\n\n📦 {size_mb:.1f} MB"

        await query.edit_message_text("📤 *Ирсол мешавад...*", parse_mode="Markdown")

        try:
            if size_mb > 50:
                await send_large_video(chat_id, path)
            else:
                with open(path, "rb") as f:
                    await query.message.reply_video(
                        video=f,
                        caption=caption,
                        parse_mode="Markdown"
                    )
            await query.delete_message()
        except Exception as e:
            logging.error(f"[SEND AUDIO AS VIDEO] {e}")
            await query.edit_message_text("❌ Ирсол нашуд. Дубора кӯшиш кунед.")
        finally:
            if os.path.exists(path):
                os.remove(path)
            user_store.pop(uid, None)
        return

    # ── Сифат → скачати видео ──────────────────────────────────────────────────
    if data.startswith("q_"):
        quality = data.replace("q_", "")
        q_label = {"low": "паст 🔻", "medium": "миёна 🔶", "high": "баланд 🔺"}.get(quality, "")

        await query.edit_message_text(
            f"⏳ *{plabel}* — видео ({q_label}) скачат мешавад...\n\n"
            "🔄 Лутфан интизор шавед.",
            parse_mode="Markdown"
        )

        path = await download_video(url, quality)

        if not path or not os.path.exists(path):
            await query.edit_message_text(
                "❌ *Видео скачат нашуд.*\n\n"
                "Сабабҳои эҳтимолӣ:\n"
                "• Видео хусусӣ аст\n"
                "• Ин сифат дастрас нест\n"
                "• Силка нодуруст аст\n\n"
                "Силкаро санҷед ё сифати дигар интихоб кунед.",
                parse_mode="Markdown"
            )
            user_store.pop(uid, None)
            return

        size_mb = os.path.getsize(path) / (1024 * 1024)
        await query.edit_message_text(
            f"📤 *Ирсол мешавад...*\n📦 {size_mb:.1f} MB",
            parse_mode="Markdown"
        )

        try:
            if size_mb > 50:
                await send_large_video(chat_id, path)
            else:
                with open(path, "rb") as f:
                    await query.message.reply_video(video=f)
            await query.delete_message()
        except Exception as e:
            logging.error(f"[SEND VIDEO] {e}")
            await query.edit_message_text("❌ Ирсол нашуд. Дубора кӯшиш кунед.")
        finally:
            if os.path.exists(path):
                os.remove(path)
            user_store.pop(uid, None)


# ═══════════════════════════════════════════════════════════════════════════════
def main():
    app = ApplicationBuilder().token(TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help",  help_cmd))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    app.add_handler(CallbackQueryHandler(handle_callback))
    print("✅ Бот кор мекунад — то 2GB дастгирӣ!")
    try:
        app.run_polling()
    except Conflict:
        logging.error("Conflict: another bot instance is already running. Stop the other process or webhook before starting this bot.")
    except Exception as e:
        logging.error("Bot stopped due to error: %s", e)


if __name__ == "__main__":
    main()