#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════╗
║        🚀 TEZDA YUKLAYMAN BOT — PREMIUM EDITION v2.0        ║
║        Muallif  : @vsf911                                    ║
║        Versiya  : 2.0.                                             ║
╚══════════════════════════════════════════════════════════════╝

XUSUSIYATLAR:
  ✅ Parallel (bir vaqtda) video + audio yuklab olish
  ✅ Tanlash bilan ovora bo'lsangiz ham yuklab olinadi
  ✅ Instagram, TikTok, YouTube, Facebook, Snapchat, va boshqalar
  ✅ Shazam — qo'shiq nomi, ijrochi, matni
  ✅ Majburiy obuna tizimi
  ✅ Admin panel (broadcast, foydalanuvchilar, kanallar)
  ✅ Server keshi yo'q — fayllar darhol o'chiriladi
  ✅ Guruhlarda ham ishlaydi
  ✅ Render.com uchun web server
"""

# ─────────────────────────────────────────────────────────────
#  📦  IMPORT
# ─────────────────────────────────────────────────────────────
import os
import re
import time
import uuid
import asyncio
import logging
import sqlite3
import threading
from datetime import datetime
from functools import wraps
from http.server import BaseHTTPRequestHandler, HTTPServer

import yt_dlp
import telebot
from telebot import types

try:
    from shazamio import Shazam
    SHAZAM_OK = True
except ImportError:
    SHAZAM_OK = False

# ─────────────────────────────────────────────────────────────
#  📋  LOGGING
# ─────────────────────────────────────────────────────────────
logging.basicConfig(
    format='%(asctime)s [%(levelname)s] %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
#  ⚙️  SOZLAMALAR — bu yerni o'zgartiring
# ─────────────────────────────────────────────────────────────
BOT_TOKEN  = "8990234811:AAGjIFyNd3gKggua1qlUN_R0ZfkiRt_SFss"
ADMIN_IDS  = [8426582765]
BOT_NAME   = "@TezdaYuklaymanbot"
AUTHOR     = "@vsf911"
DB_FILE    = "tezda_bot.db"
TEMP_DIR   = "/tmp/tezda"
MAX_BYTES  = 49 * 1024 * 1024   # 49 MB  (Telegram limiti 50 MB)
TASK_TTL   = 300                 # 5 daqiqa — vazifani xotiradan o'chirish

os.makedirs(TEMP_DIR, exist_ok=True)

# ─────────────────────────────────────────────────────────────
#  🤖  BOT OBYEKTI
# ─────────────────────────────────────────────────────────────
bot = telebot.TeleBot(BOT_TOKEN, parse_mode='HTML', num_threads=10)
if SHAZAM_OK:
    shazam_engine = Shazam()

# Xotiradagi vazifalar: { task_id: { ... } }
tasks: dict = {}
# Admin holati: { uid: { state, ... } }
adm_state: dict = {}


# ═══════════════════════════════════════════════════════════════
#  🌐  RENDER.COM KEEP-ALIVE WEB SERVER
# ═══════════════════════════════════════════════════════════════
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        users, dls = db_stats()
        body = (
            "<html><body style='font-family:sans-serif;text-align:center;padding:40px'>"
            "<h1>🚀 TezdaYuklayman Bot</h1>"
            f"<p>Holat: <b style='color:green'>ISHLAYAPTI ✅</b></p>"
            f"<p>👥 Foydalanuvchilar: <b>{users}</b></p>"
            f"<p>📥 Jami yuklamalar: <b>{dls}</b></p>"
            f"<p>🕒 {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}</p>"
            "</body></html>"
        ).encode()
        self.send_response(200)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a): pass


def run_web_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    logger.info(f"🌐 Web-server port {port} da ishga tushdi")
    server.serve_forever()


# ═══════════════════════════════════════════════════════════════
#  🗄️  MA'LUMOTLAR BAZASI
# ═══════════════════════════════════════════════════════════════
def _conn():
    return sqlite3.connect(DB_FILE, check_same_thread=False)


def init_db():
    with _conn() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                uid       INTEGER PRIMARY KEY,
                username  TEXT    DEFAULT '',
                fullname  TEXT    DEFAULT '',
                joined    TEXT    DEFAULT (datetime('now')),
                last_seen TEXT    DEFAULT (datetime('now')),
                dl_count  INTEGER DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS channels (
                id       INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT    UNIQUE,
                title    TEXT    DEFAULT '',
                added_at TEXT    DEFAULT (datetime('now'))
            );
            CREATE TABLE IF NOT EXISTS broadcasts (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                sent       INTEGER DEFAULT 0,
                failed     INTEGER DEFAULT 0,
                created_at TEXT    DEFAULT (datetime('now'))
            );
        """)


def db_save_user(user):
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO users (uid, username, fullname) VALUES (?,?,?)",
            (user.id, user.username or '', user.first_name or '')
        )
        c.execute(
            "UPDATE users SET username=?, fullname=?, last_seen=datetime('now') WHERE uid=?",
            (user.username or '', user.first_name or '', user.id)
        )


def db_inc_dl(uid):
    with _conn() as c:
        c.execute("UPDATE users SET dl_count=dl_count+1 WHERE uid=?", (uid,))


def db_stats():
    with _conn() as c:
        users = c.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        dls   = c.execute("SELECT COALESCE(SUM(dl_count),0) FROM users").fetchone()[0]
    return users, dls


def db_all_uids():
    with _conn() as c:
        return [r[0] for r in c.execute("SELECT uid FROM users").fetchall()]


def db_recent_users(n=30):
    with _conn() as c:
        return c.execute(
            "SELECT uid, username, fullname, dl_count, last_seen "
            "FROM users ORDER BY last_seen DESC LIMIT ?", (n,)
        ).fetchall()


def db_channels():
    with _conn() as c:
        return c.execute("SELECT username, title FROM channels").fetchall()


def db_add_channel(username, title=''):
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO channels (username, title) VALUES (?,?)",
            (username, title)
        )


def db_del_channel(username):
    with _conn() as c:
        c.execute("DELETE FROM channels WHERE username=?", (username,))


# ═══════════════════════════════════════════════════════════════
#  🔒  MAJBURIY OBUNA
# ═══════════════════════════════════════════════════════════════
def is_subscribed(uid: int) -> bool:
    channels = db_channels()
    if not channels:
        return True
    for ch, _ in channels:
        try:
            status = bot.get_chat_member(ch, uid).status
            if status in ('left', 'kicked', 'restricted'):
                return False
        except Exception:
            return False
    return True


def send_sub_wall(uid: int):
    channels = db_channels()
    kb = types.InlineKeyboardMarkup(row_width=1)
    text = "🔒 <b>Botdan foydalanish uchun quyidagi kanallarga obuna bo'ling:</b>\n\n"
    for ch, title in channels:
        clean = ch.lstrip('@')
        text += f"📢 {title or ch}\n"
        kb.add(types.InlineKeyboardButton(f"➕ {title or ch}", url=f"https://t.me/{clean}"))
    kb.add(types.InlineKeyboardButton("✅ Obunani tekshirish", callback_data="chk_sub"))
    try:
        bot.send_message(uid, text, reply_markup=kb)
    except Exception as e:
        logger.warning(f"send_sub_wall error: {e}")


def require_sub(fn):
    @wraps(fn)
    def wrapper(message, *a, **kw):
        uid = message.from_user.id
        if message.chat.type == 'private' and not is_subscribed(uid):
            send_sub_wall(uid)
            return
        return fn(message, *a, **kw)
    return wrapper


# ═══════════════════════════════════════════════════════════════
#  🛠  YORDAMCHI FUNKSIYALAR
# ═══════════════════════════════════════════════════════════════
URL_RE = re.compile(r'https?://[^\s]+')

def extract_url(text: str) -> str | None:
    m = URL_RE.search(text or '')
    return m.group(0) if m else None


PLATFORMS = {
    'youtube.com':   '🎬 YouTube',
    'youtu.be':      '🎬 YouTube',
    'instagram.com': '📸 Instagram',
    'tiktok.com':    '🎵 TikTok',
    'facebook.com':  '👥 Facebook',
    'fb.watch':      '👥 Facebook',
    'snapchat.com':  '👻 Snapchat',
    'likee.video':   '🎥 Likee',
    'pinterest.com': '📌 Pinterest',
    'threads.net':   '🧵 Threads',
    'twitter.com':   '🐦 Twitter/X',
    'x.com':         '🐦 Twitter/X',
    'vimeo.com':     '🎬 Vimeo',
    'dailymotion.com': '🎬 Dailymotion',
    'reddit.com':    '🔴 Reddit',
    'twitch.tv':     '💜 Twitch',
    'bilibili.com':  '📺 Bilibili',
}

def get_platform(url: str) -> str:
    low = url.lower()
    for domain, name in PLATFORMS.items():
        if domain in low:
            return name
    return '🌐 Video'


def clean(*paths):
    for p in paths:
        try:
            if p and os.path.exists(p):
                os.remove(p)
        except Exception:
            pass


def find_file(prefix: str) -> str | None:
    """TEMP_DIR ichida prefix bilan boshlanadigan faylni topadi."""
    try:
        for f in os.listdir(TEMP_DIR):
            if f.startswith(prefix):
                fp = os.path.join(TEMP_DIR, f)
                if os.path.isfile(fp) and os.path.getsize(fp) > 100:
                    return fp
    except Exception:
        pass
    return None


def cleanup_old_tasks():
    """Eskirgan vazifalar va fayllarni o'chiradi."""
    now = time.time()
    expired = [tid for tid, t in tasks.items() if now - t.get('created', now) > TASK_TTL]
    for tid in expired:
        for prefix in (f"vid_{tid}", f"aud_{tid}"):
            fp = find_file(prefix)
            if fp:
                clean(fp)
        tasks.pop(tid, None)


# ═══════════════════════════════════════════════════════════════
#  📥  YUKLOVCHI — PARALLEL DOWNLOAD ENGINE
# ═══════════════════════════════════════════════════════════════
def _ydl_run(url: str, opts: dict):
    with yt_dlp.YoutubeDL(opts) as ydl:
        return ydl.extract_info(url, download=True)


def predownload(task_id: str, url: str):
    """
    Foydalanuvchi formatni tanlaguncha orqa fonda VIDEO va AUDIOni
    bir vaqtda ikki alohida thread'da yuklab oladi.
    """
    vid_opts = {
        'format': (
            'bestvideo[height<=1080][ext=mp4]+bestaudio[ext=m4a]/'
            'best[height<=1080][ext=mp4]/best[ext=mp4]/best'
        ),
        'outtmpl':             os.path.join(TEMP_DIR, f'vid_{task_id}.%(ext)s'),
        'merge_output_format': 'mp4',
        'quiet':               True,
        'no_warnings':         True,
        'noplaylist':          True,
        'socket_timeout':      30,
    }
    aud_opts = {
        'format':    'bestaudio/best',
        'outtmpl':   os.path.join(TEMP_DIR, f'aud_{task_id}.%(ext)s'),
        'quiet':     True,
        'no_warnings': True,
        'noplaylist':  True,
        'socket_timeout': 30,
        'postprocessors': [{
            'key':             'FFmpegExtractAudio',
            'preferredcodec':  'mp3',
            'preferredquality': '320',
        }],
    }

    def dl_video():
        try:
            info = _ydl_run(url, vid_opts)
            tasks[task_id]['title']       = info.get('title', '')[:80]
            tasks[task_id]['duration']    = info.get('duration', 0)
            tasks[task_id]['vid_ready']   = True
        except Exception as e:
            tasks[task_id]['vid_err']   = str(e)
            tasks[task_id]['vid_ready'] = True
            logger.error(f"[{task_id}] video error: {e}")

    def dl_audio():
        try:
            _ydl_run(url, aud_opts)
            tasks[task_id]['aud_ready'] = True
        except Exception as e:
            tasks[task_id]['aud_err']   = str(e)
            tasks[task_id]['aud_ready'] = True
            logger.error(f"[{task_id}] audio error: {e}")

    threading.Thread(target=dl_video, daemon=True).start()
    threading.Thread(target=dl_audio, daemon=True).start()


# ═══════════════════════════════════════════════════════════════
#  📝  XABAR SHABLONLARI
# ═══════════════════════════════════════════════════════════════
WELCOME = (
    "🔥 Assalomu alaykum. {bot} ga Xush kelibsiz.\n"
    "Bot orqali quyidagilarni yuklab olishingiz mumkin:\n\n"
    "• Instagram — post va IGTV + audio bilan;\n"
    "• TikTok — suv belgisiz video + audio bilan;\n"
    "• YouTube — videolar va Shorts + audio bilan;\n"
    "• Snapchat — suv belgisiz video + audio bilan;\n"
    "• Likee — suv belgisiz video + audio bilan;\n"
    "• Pinterest — suv belgisiz video va rasmlar + audio bilan;\n"
    "• Threads — video va rasmlar + audio bilan;\n"
    "• Facebook, Twitter/X va ko'plab boshqalar!\n\n"
    "🎵 <b>Shazam funksiyasi:</b>\n"
    "Ovozli xabar, audio, video yoki video xabar yuboring\n\n"
    "🚀 Yuklab olish uchun havola yuboring!\n"
    "😎 Bot guruhlarda ham ishlaydi!"
)

HELP_TEXT = (
    "ℹ️ <b>Yordam va ko'rsatmalar</b>\n\n"
    "📥 <b>Video / Audio yuklab olish:</b>\n"
    "Havola yuboring → format tanlang → tayyor!\n\n"
    "🎵 <b>Shazam (qo'shiq aniqlash):</b>\n"
    "Ovozli xabar, audio, video yoki video xabar yuboring\n\n"
    "🌐 <b>Qo'llab-quvvatlanadigan saytlar:</b>\n"
    "YouTube, Instagram, TikTok, Facebook,\n"
    "Snapchat, Pinterest, Threads, Likee,\n"
    "Twitter/X, Vimeo, Reddit, Twitch va boshqalar\n\n"
    "⚡ <b>Texnik jihat:</b>\n"
    "• Maksimal fayl: 50 MB\n"
    "• Sifat: HD 1080p gacha\n"
    "• Audio: MP3 320 kbps\n\n"
    f"📞 <b>Qo'llab-quvvatlash:</b> {AUTHOR}"
)


# ═══════════════════════════════════════════════════════════════
#  🚀  KOMANDALAR
# ═══════════════════════════════════════════════════════════════
@bot.message_handler(commands=['start'])
def cmd_start(message):
    db_save_user(message.from_user)
    uid = message.from_user.id

    if message.chat.type != 'private':
        return

    if not is_subscribed(uid):
        send_sub_wall(uid)
        return

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("❓ Yordam",     callback_data="cb_help"),
        types.InlineKeyboardButton("📊 Statistika", callback_data="cb_stats")
    )
    kb.add(
        types.InlineKeyboardButton(
            "➕ Guruhga qo'shish",
            url="https://t.me/TezdaYuklaymanbot?startgroup=true"
        )
    )
    bot.send_message(
        uid, WELCOME.format(bot=BOT_NAME),
        reply_markup=kb, disable_web_page_preview=True
    )


@bot.message_handler(commands=['help'])
def cmd_help(message):
    db_save_user(message.from_user)
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🏠 Bosh menyu", callback_data="cb_main"))
    bot.send_message(message.chat.id, HELP_TEXT, reply_markup=kb)


# ═══════════════════════════════════════════════════════════════
#  🔗  URL HANDLER — ASOSIY YUKLASH
# ═══════════════════════════════════════════════════════════════
@bot.message_handler(func=lambda m: bool(extract_url(m.text or '')))
@require_sub
def handle_url(message):
    db_save_user(message.from_user)
    cleanup_old_tasks()

    uid      = message.from_user.id
    url      = extract_url(message.text)
    platform = get_platform(url)

    task_id = uuid.uuid4().hex[:12]
    tasks[task_id] = {
        'url':       url,
        'uid':       uid,
        'platform':  platform,
        'created':   time.time(),
        'vid_ready': False,
        'aud_ready': False,
        'vid_err':   None,
        'aud_err':   None,
        'title':     '',
        'duration':  0,
    }

    # 🔥 Darhol orqa fonda yuklab olishni boshlash
    predownload(task_id, url)

    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("🎬 Video (HD)",   callback_data=f"dl:vid:{task_id}"),
        types.InlineKeyboardButton("🎵 Audio (MP3)",  callback_data=f"dl:aud:{task_id}")
    )
    kb.add(types.InlineKeyboardButton("❌ Bekor qilish", callback_data=f"dl:cancel:{task_id}"))

    bot.reply_to(
        message,
        f"⚡ <b>{platform}</b> havolasi topildi!\n\n"
        f"⬇️ <i>Siz tanlov qilayotgan paytda yuklab olinmoqda...</i>\n\n"
        f"Formatni tanlang:",
        reply_markup=kb
    )


@bot.callback_query_handler(func=lambda c: c.data.startswith("dl:"))
def cb_download(c):
    uid   = c.from_user.id
    parts = c.data.split(":")
    dtype = parts[1]      # "vid" | "aud" | "cancel"
    tid   = parts[2]

    # Bekor qilish
    if dtype == "cancel":
        tasks.pop(tid, None)
        try:
            bot.edit_message_text("❌ Bekor qilindi.", uid, c.message.message_id)
        except Exception: pass
        return

    if tid not in tasks:
        bot.answer_callback_query(c.id, "⏰ Vaqt tugadi! Qaytadan havola tashlang.", show_alert=True)
        return

    bot.answer_callback_query(c.id, "⏳ Tayyorlanmoqda...")
    task = tasks[tid]

    emoji = "🎬" if dtype == "vid" else "🎵"
    try:
        bot.edit_message_text(
            f"{emoji} Yuklanmoqda...\n"
            f"⚡ Iltimos kuting, deyarli tayyor!",
            uid, c.message.message_id
        )
    except Exception: pass

    def finalize():
        ready_key  = 'vid_ready' if dtype == 'vid' else 'aud_ready'
        err_key    = 'vid_err'   if dtype == 'vid' else 'aud_err'
        prefix     = ('vid_' if dtype == 'vid' else 'aud_') + tid

        # Maksimal 180 soniya kutamiz
        for _ in range(180):
            if task.get(ready_key):
                break
            time.sleep(1)

        # Xatolik tekshiruvi
        err = task.get(err_key)
        if err:
            try:
                bot.edit_message_text(
                    f"❌ <b>Yuklab olishda xatolik yuz berdi.</b>\n\n"
                    f"<code>{err[:250]}</code>\n\n"
                    f"💡 Sabab: yopiq profil, cheklangan kontent yoki\n"
                    f"    botda ushbu platforma qo'llab-quvvatlanmasligi.\n\n"
                    f"📞 Yordam: {AUTHOR}",
                    uid, c.message.message_id
                )
            except Exception: pass
            tasks.pop(tid, None)
            return

        # Faylni topish
        file_path = find_file(prefix)
        if not file_path:
            try:
                bot.edit_message_text(
                    "❌ Fayl topilmadi. Qaytadan urinib ko'ring.",
                    uid, c.message.message_id
                )
            except Exception: pass
            tasks.pop(tid, None)
            return

        file_size = os.path.getsize(file_path)

        # Hajm tekshiruvi
        if file_size > MAX_BYTES:
            size_mb = file_size / 1024 / 1024
            try:
                bot.edit_message_text(
                    f"⚠️ <b>Fayl hajmi juda katta!</b>\n\n"
                    f"📦 Hajm: <b>{size_mb:.1f} MB</b>\n"
                    f"🚫 Telegram limiti: 50 MB\n\n"
                    f"💡 Pastroq sifatli variant uchun qaytadan urinib ko'ring.\n"
                    f"📞 Yordam: {AUTHOR}",
                    uid, c.message.message_id
                )
            except Exception: pass
            clean(file_path)
            tasks.pop(tid, None)
            return

        title    = task.get('title', '') or ''
        platform = task.get('platform', '🌐')

        short_title = (title[:60] + '…') if len(title) > 60 else title
        caption = (
            f"{emoji} <b>{short_title}</b>\n"
            f"━━━━━━━━━━━━━━━━━━━\n"
            f"📥 <b>@TezdaYuklaymanbot</b> orqali yuklab olindi"
        )

        try:
            bot.edit_message_text("📤 Yuborilmoqda...", uid, c.message.message_id)

            with open(file_path, 'rb') as f:
                if dtype == 'vid':
                    bot.send_video(
                        c.message.chat.id, f,
                        caption=caption,
                        supports_streaming=True,
                        timeout=180
                    )
                else:
                    bot.send_audio(
                        c.message.chat.id, f,
                        caption=caption,
                        title=title or 'Audio',
                        timeout=180
                    )

            try:
                bot.delete_message(uid, c.message.message_id)
            except Exception: pass

            db_inc_dl(uid)
            logger.info(f"✅ Yuborildi: uid={uid} tip={dtype} fayl={os.path.basename(file_path)}")

        except Exception as e:
            logger.error(f"[send error] {e}")
            try:
                bot.edit_message_text(
                    f"❌ Yuborishda xatolik:\n<code>{str(e)[:200]}</code>\n\n"
                    f"📞 Yordam: {AUTHOR}",
                    uid, c.message.message_id
                )
            except Exception: pass
        finally:
            # 🗑️  SERVERDA KESH QO'LMASIN — DARHOL O'CHIRISH
            other_pref = ('aud_' if dtype == 'vid' else 'vid_') + tid
            other_file = find_file(other_pref)
            clean(file_path)
            if other_file:
                clean(other_file)
            tasks.pop(tid, None)

    threading.Thread(target=finalize, daemon=True).start()


# ═══════════════════════════════════════════════════════════════
#  🎵  SHAZAM — QO'SHIQ ANIQLASH
# ═══════════════════════════════════════════════════════════════
@bot.message_handler(content_types=['audio', 'voice', 'video', 'video_note'])
@require_sub
def handle_media_shazam(message):
    db_save_user(message.from_user)
    uid = message.from_user.id

    if not SHAZAM_OK:
        bot.reply_to(message, "❌ Shazam moduli o'rnatilmagan.\nPip: <code>pip install shazamio</code>")
        return

    status_msg = bot.reply_to(message, "🔍 <i>Qo'shiq qidirilmoqda...</i>")

    ct = message.content_type
    if ct == 'audio':      file_id = message.audio.file_id
    elif ct == 'voice':    file_id = message.voice.file_id
    elif ct == 'video':    file_id = message.video.file_id
    else:                  file_id = message.video_note.file_id

    def process():
        tmp = os.path.join(TEMP_DIR, f"shazam_{uid}_{int(time.time())}.tmp")
        try:
            fi   = bot.get_file(file_id)
            data = bot.download_file(fi.file_path)
            with open(tmp, 'wb') as f:
                f.write(data)

            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            out  = loop.run_until_complete(shazam_engine.recognize(tmp))
            loop.close()

            if 'track' in out:
                track  = out['track']
                title  = track.get('title', 'Noma\'lum')
                artist = track.get('subtitle', 'Noma\'lum')
                genre  = track.get('genres', {}).get('primary', '')
                img    = track.get('images', {}).get('coverart', '')

                # Qo'shiq matni (dastlabki 10 satr)
                lyrics_lines = []
                for section in track.get('sections', []):
                    if section.get('type') == 'LYRICS':
                        lyrics_lines = section.get('text', [])[:10]
                        break

                result = (
                    f"🎵 <b>Qo'shiq topildi!</b>\n\n"
                    f"🎤 <b>Ijrochi:</b> {artist}\n"
                    f"🎵 <b>Nomi:</b>    {title}\n"
                )
                if genre:
                    result += f"🎸 <b>Janr:</b>    {genre}\n"
                if lyrics_lines:
                    result += (
                        "\n📝 <b>Qo'shiq matni (bir qismi):</b>\n"
                        + "<i>" + "\n".join(lyrics_lines) + "</i>"
                    )

                yt_q = (f"{artist} {title}").replace(' ', '+')
                kb = types.InlineKeyboardMarkup(row_width=1)
                kb.add(
                    types.InlineKeyboardButton(
                        "▶️ YouTube Music'da topish",
                        url=f"https://music.youtube.com/search?q={yt_q}"
                    ),
                    types.InlineKeyboardButton(
                        "🔍 Spotifyda qidirish",
                        url=f"https://open.spotify.com/search/{yt_q}"
                    )
                )
                bot.edit_message_text(
                    result, uid, status_msg.message_id, reply_markup=kb
                )
            else:
                bot.edit_message_text(
                    "❌ Qo'shiq aniqlanmadi.\n\n"
                    "💡 Sifatliroq audio yuboring yoki shovqinsiz joyda yozib ko'ring.",
                    uid, status_msg.message_id
                )

        except Exception as e:
            logger.error(f"Shazam error: {e}")
            try:
                bot.edit_message_text("❌ Qidirishda xatolik yuz berdi.", uid, status_msg.message_id)
            except Exception: pass
        finally:
            clean(tmp)

    threading.Thread(target=process, daemon=True).start()


# ═══════════════════════════════════════════════════════════════
#  👑  ADMIN PANEL
# ═══════════════════════════════════════════════════════════════
def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


def admin_keyboard() -> types.InlineKeyboardMarkup:
    kb = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("👥 Foydalanuvchilar", callback_data="adm:users"),
        types.InlineKeyboardButton("📊 Statistika",       callback_data="adm:stats")
    )
    kb.add(
        types.InlineKeyboardButton("📢 Reklama yuborish", callback_data="adm:broadcast"),
        types.InlineKeyboardButton("📺 Kanallar",         callback_data="adm:channels")
    )
    kb.add(
        types.InlineKeyboardButton("➕ Kanal qo'shish",   callback_data="adm:addch"),
        types.InlineKeyboardButton("➖ Kanal o'chirish",  callback_data="adm:delch")
    )
    return kb


def send_admin_panel(chat_id, message_id=None):
    users, dls = db_stats()
    channels   = db_channels()
    text = (
        f"👑 <b>ADMIN PANEL</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{users}</b>\n"
        f"📥 Jami yuklamalar:  <b>{dls}</b>\n"
        f"📺 Majburiy kanallar: <b>{len(channels)}</b>\n"
        f"⏱ {datetime.now().strftime('%d.%m.%Y  %H:%M:%S')}"
    )
    kb = admin_keyboard()
    try:
        if message_id:
            bot.edit_message_text(text, chat_id, message_id, reply_markup=kb)
        else:
            bot.send_message(chat_id, text, reply_markup=kb)
    except Exception:
        bot.send_message(chat_id, text, reply_markup=kb)


@bot.message_handler(commands=['admin', 'panel'])
def cmd_admin(message):
    if not is_admin(message.from_user.id):
        return
    send_admin_panel(message.chat.id)


@bot.message_handler(commands=['addchannel'])
def cmd_add_channel(message):
    if not is_admin(message.from_user.id): return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 2:
        bot.send_message(message.chat.id, "❌ Format: /addchannel @kanal_nomi [Sarlavha]")
        return
    ch    = parts[1] if parts[1].startswith('@') else '@' + parts[1]
    title = parts[2] if len(parts) > 2 else ch
    db_add_channel(ch, title)
    bot.send_message(message.chat.id, f"✅ Kanal qo'shildi: <b>{ch}</b> ({title})")


@bot.message_handler(commands=['delchannel'])
def cmd_del_channel(message):
    if not is_admin(message.from_user.id): return
    parts = message.text.split()
    if len(parts) < 2:
        bot.send_message(message.chat.id, "❌ Format: /delchannel @kanal_nomi")
        return
    ch = parts[1] if parts[1].startswith('@') else '@' + parts[1]
    db_del_channel(ch)
    bot.send_message(message.chat.id, f"✅ Kanal o'chirildi: <b>{ch}</b>")


@bot.message_handler(commands=['channels'])
def cmd_channels(message):
    if not is_admin(message.from_user.id): return
    channels = db_channels()
    if not channels:
        bot.send_message(message.chat.id, "📭 Hech qanday kanal yo'q.")
        return
    text = "📺 <b>Majburiy kanallar:</b>\n\n"
    for ch, title in channels:
        text += f"• <code>{ch}</code> — {title}\n"
    bot.send_message(message.chat.id, text)


@bot.message_handler(commands=['stats'])
def cmd_stats(message):
    if not is_admin(message.from_user.id): return
    users, dls = db_stats()
    channels   = db_channels()
    bot.send_message(
        message.chat.id,
        f"📊 <b>Bot Statistikasi</b>\n\n"
        f"👥 Foydalanuvchilar: <b>{users}</b>\n"
        f"📥 Jami yuklamalar: <b>{dls}</b>\n"
        f"📺 Kanallar: <b>{len(channels)}</b>"
    )


@bot.message_handler(commands=['users'])
def cmd_users(message):
    if not is_admin(message.from_user.id): return
    rows = db_recent_users(30)
    text = "👥 <b>So'nggi 30 foydalanuvchi:</b>\n\n"
    for uid, uname, fname, dl, last in rows:
        name = f"@{uname}" if uname else fname or "—"
        text += f"• {name} | <code>{uid}</code> | 📥{dl}\n"
    # 4096 belgi chegarasi
    bot.send_message(message.chat.id, text[:4090])


@bot.message_handler(commands=['broadcast'])
def cmd_broadcast(message):
    if not is_admin(message.from_user.id): return
    adm_state[message.from_user.id] = {'state': 'wait_broadcast'}
    bot.send_message(
        message.chat.id,
        "📣 <b>Reklama yuborish</b>\n\n"
        "Barchaga yuboriladigan xabarni yuboring:\n"
        "(Matn, rasm, video yoki istalgan tur)\n\n"
        "Bekor qilish: /cancel"
    )


@bot.message_handler(commands=['cancel'])
def cmd_cancel(message):
    uid = message.from_user.id
    if uid in adm_state:
        del adm_state[uid]
    bot.send_message(message.chat.id, "❌ Bekor qilindi.")


# ─────────────────────────────────────────────────────────────
#  Admin inline callbacks
# ─────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data.startswith("adm:"))
def cb_admin(c):
    uid = c.from_user.id
    if not is_admin(uid):
        bot.answer_callback_query(c.id, "❌ Ruxsat yo'q!")
        return
    bot.answer_callback_query(c.id)

    action = c.data[4:]   # after "adm:"

    if action == "stats":
        users, dls = db_stats()
        channels = db_channels()
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("🔄 Yangilash", callback_data="adm:stats"))
        kb.add(types.InlineKeyboardButton("◀️ Orqaga",   callback_data="adm:back"))
        bot.edit_message_text(
            f"📊 <b>Bot Statistikasi</b>\n\n"
            f"👥 Foydalanuvchilar: <b>{users}</b>\n"
            f"📥 Jami yuklamalar: <b>{dls}</b>\n"
            f"📺 Kanallar: <b>{len(channels)}</b>\n"
            f"🕒 {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            uid, c.message.message_id, reply_markup=kb
        )

    elif action == "users":
        rows = db_recent_users(20)
        text = "👥 <b>So'nggi 20 foydalanuvchi:</b>\n\n"
        for u_uid, uname, fname, dl, last in rows:
            name = f"@{uname}" if uname else fname or "—"
            text += f"• {name} | <code>{u_uid}</code> | 📥{dl}\n"
        kb = types.InlineKeyboardMarkup()
        kb.add(types.InlineKeyboardButton("◀️ Orqaga", callback_data="adm:back"))
        bot.edit_message_text(text[:4090], uid, c.message.message_id, reply_markup=kb)

    elif action == "broadcast":
        adm_state[uid] = {'state': 'wait_broadcast', 'msg_id': c.message.message_id}
        bot.edit_message_text(
            "📣 <b>Reklama yuborish</b>\n\n"
            "Barchaga yuboriladigan xabarni yuboring:\n"
            "(Matn, rasm, video yoki istalgan tur)\n\n"
            "Bekor qilish: /cancel",
            uid, c.message.message_id
        )

    elif action == "channels":
        channels = db_channels()
        if not channels:
            text = "📭 Hech qanday faol kanal yo'q."
        else:
            text = "📺 <b>Majburiy kanallar:</b>\n\n"
            for ch, title in channels:
                text += f"• <code>{ch}</code> — {title}\n"
        kb = types.InlineKeyboardMarkup(row_width=1)
        kb.add(types.InlineKeyboardButton("◀️ Orqaga", callback_data="adm:back"))
        bot.edit_message_text(text, uid, c.message.message_id, reply_markup=kb)

    elif action == "addch":
        adm_state[uid] = {'state': 'wait_addch', 'msg_id': c.message.message_id}
        bot.edit_message_text(
            "➕ <b>Kanal qo'shish</b>\n\n"
            "Formatda yuboring:\n"
            "<code>@kanal_nomi Kanal Sarlavhasi</code>\n\n"
            "Misol:\n<code>@texnologiya_uz Texnologiya UZ</code>\n\n"
            "Bekor qilish: /cancel",
            uid, c.message.message_id
        )

    elif action == "delch":
        channels = db_channels()
        if not channels:
            bot.answer_callback_query(c.id, "Hech qanday kanal yo'q!", show_alert=True)
            return
        kb = types.InlineKeyboardMarkup(row_width=1)
        for ch, title in channels:
            kb.add(types.InlineKeyboardButton(
                f"❌ {title or ch}",
                callback_data=f"adm:confirm_del:{ch}"
            ))
        kb.add(types.InlineKeyboardButton("◀️ Orqaga", callback_data="adm:back"))
        bot.edit_message_text(
            "➖ <b>O'chiriladigan kanalni tanlang:</b>",
            uid, c.message.message_id, reply_markup=kb
        )

    elif action.startswith("confirm_del:"):
        ch = action.split(":", 1)[1]
        db_del_channel(ch)
        bot.answer_callback_query(c.id, f"✅ {ch} o'chirildi!", show_alert=True)
        send_admin_panel(uid, c.message.message_id)

    elif action == "back":
        send_admin_panel(uid, c.message.message_id)


# ─────────────────────────────────────────────────────────────
#  Public inline callbacks
# ─────────────────────────────────────────────────────────────
@bot.callback_query_handler(func=lambda c: c.data == "chk_sub")
def cb_chk_sub(c):
    uid = c.from_user.id
    if is_subscribed(uid):
        bot.answer_callback_query(c.id, "✅ Obuna tasdiqlandi!", show_alert=True)
        try:
            bot.delete_message(uid, c.message.message_id)
        except Exception: pass
        bot.send_message(uid, "🚀 Yuklab olish uchun havola yuboring!")
    else:
        bot.answer_callback_query(
            c.id, "❌ Hali barcha kanallarga obuna bo'lmadingiz!", show_alert=True
        )


@bot.callback_query_handler(func=lambda c: c.data == "cb_help")
def cb_help(c):
    kb = types.InlineKeyboardMarkup()
    kb.add(types.InlineKeyboardButton("🏠 Bosh menyu", callback_data="cb_main"))
    bot.edit_message_text(HELP_TEXT, c.from_user.id, c.message.message_id, reply_markup=kb)


@bot.callback_query_handler(func=lambda c: c.data == "cb_main")
def cb_main(c):
    uid = c.from_user.id
    kb  = types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        types.InlineKeyboardButton("❓ Yordam",     callback_data="cb_help"),
        types.InlineKeyboardButton("📊 Statistika", callback_data="cb_stats")
    )
    kb.add(
        types.InlineKeyboardButton(
            "➕ Guruhga qo'shish",
            url="https://t.me/TezdaYuklaymanbot?startgroup=true"
        )
    )
    try:
        bot.edit_message_text(
            WELCOME.format(bot=BOT_NAME), uid, c.message.message_id,
            reply_markup=kb, disable_web_page_preview=True
        )
    except Exception: pass


@bot.callback_query_handler(func=lambda c: c.data == "cb_stats")
def cb_stats(c):
    users, dls = db_stats()
    bot.answer_callback_query(
        c.id,
        f"📊 Bot statistikasi\n\n"
        f"👥 Foydalanuvchilar: {users}\n"
        f"📥 Jami yuklamalar: {dls}",
        show_alert=True
    )


# ═══════════════════════════════════════════════════════════════
#  📣  BARCHA MATN XABARLARI HANDLER (broadcast state + URL)
# ═══════════════════════════════════════════════════════════════
@bot.message_handler(
    content_types=['text', 'photo', 'video', 'document', 'animation', 'sticker']
)
def handle_all(message):
    uid = message.from_user.id
    db_save_user(message.from_user)

    # ── Admin broadcast holati ──
    if uid in adm_state:
        state_info = adm_state.pop(uid)

        # Reklama yuborish
        if state_info['state'] == 'wait_broadcast':
            users = db_all_uids()
            status = bot.send_message(
                uid, f"📣 Yuborilmoqda... Jami: <b>{len(users)}</b> ta foydalanuvchi."
            )

            def do_bc():
                sent, failed = 0, 0
                for target in users:
                    try:
                        ct = message.content_type
                        if ct == 'text':
                            bot.send_message(target, message.text or message.caption or '')
                        elif ct == 'photo':
                            bot.send_photo(target, message.photo[-1].file_id, caption=message.caption)
                        elif ct == 'video':
                            bot.send_video(target, message.video.file_id, caption=message.caption)
                        elif ct == 'document':
                            bot.send_document(target, message.document.file_id, caption=message.caption)
                        elif ct == 'animation':
                            bot.send_animation(target, message.animation.file_id, caption=message.caption)
                        elif ct == 'sticker':
                            bot.send_sticker(target, message.sticker.file_id)
                        sent += 1
                    except Exception:
                        failed += 1
                    time.sleep(0.04)

                bot.edit_message_text(
                    f"✅ <b>Tarqatish tugadi!</b>\n\n"
                    f"✅ Yuborildi: <b>{sent}</b>\n"
                    f"❌ Xatolik:   <b>{failed}</b>\n"
                    f"📊 Jami:      <b>{len(users)}</b>",
                    uid, status.message_id
                )

            threading.Thread(target=do_bc, daemon=True).start()
            return

        # Kanal qo'shish
        elif state_info['state'] == 'wait_addch':
            parts = (message.text or '').strip().split(maxsplit=1)
            if not parts:
                bot.send_message(uid, "❌ Noto'g'ri format.")
                return
            ch    = parts[0] if parts[0].startswith('@') else '@' + parts[0]
            title = parts[1] if len(parts) > 1 else ch
            db_add_channel(ch, title)
            bot.send_message(uid, f"✅ Kanal qo'shildi: <b>{ch}</b> ({title})")
            send_admin_panel(uid)
            return

    # ── URL tekshiruvi ──
    url = extract_url(message.text or '')
    if url:
        handle_url(message)
        return

    # ── Boshqa matnlar uchun hint ──
    if message.chat.type == 'private':
        bot.send_message(
            uid,
            "💡 Video havola yuboring yoki /help buyrug'ini bosing.",
        )
# ════════════════════════════════════════════════════════════

# ═══════════════════════════════════════════════════════════════
#  🚀  ISHGA TUSHIRISH
# ═══════════════════════════════════════════════════════════════
if __name__ == '__main__':
    logger.info("═" * 60)
    logger.info("🚀  TEZDA YUKLAYMAN BOT  v2.0 — ishga tushmoqda...")
    logger.info("═" * 60)

    init_db()
    logger.info("✅ Ma'lumotlar bazasi tayyor.")

    # Render.com uchun web server
    threading.Thread(target=run_web_server, daemon=True).start()

    logger.info(f"🤖 Bot: {BOT_NAME}")
    logger.info(f"👑 Admin ID: {ADMIN_IDS}")
    logger.info(f"📂 Temp papka: {TEMP_DIR}")
    logger.info("═" * 60)

    try:
        bot.infinity_polling(
            timeout=60,
            long_polling_timeout=60,
            logger_level=logging.WARNING,
            allowed_updates=['message', 'callback_query'],
        )
    except Exception as e:
        logger.critical(f"❌ Kritik xatolik: {e}")
        raise
