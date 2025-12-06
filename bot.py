import asyncio
import logging
import os
import time
import aiohttp
import re
from collections import defaultdict
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import FSInputFile, InlineKeyboardMarkup, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

load_dotenv()
BOT_TOKEN = os.getenv('BOT_TOKEN')
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не найден в .env!")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
dp = Dispatcher()

os.makedirs("downloads", exist_ok=True)

# Настройки и статистика
last_request = {}
user_settings = defaultdict(lambda: {"no_watermark": True})  # по умолчанию — без водяного знака
stats = {"total": 0, "video": 0, "photo": 0, "failed": 0}


# === Клавиатура ===
def get_main_keyboard(user_id: int) -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    no_wm = user_settings[user_id]["no_watermark"]

    if no_wm:
        kb.button(text="Без водяного знака", callback_data="wm_on")
    else:
        kb.button(text="С водяным знаком", callback_data="wm_off")

    kb.button(text="Помощь", callback_data="help")
    kb.button(text="Статистика", callback_data="stats")
    kb.button(text="Об авторе", callback_data="about")

    kb.adjust(1, 2, 1)  # красивая раскладка
    return kb.as_markup()


# === Прогресс-бар ===
async def smooth_progress(message: types.Message):
    bars = ["▱▱▱▱▱▱▱▱▱▱", "▰▱▱▱▱▱▱▱▱▱", "▰▰▱▱▱▱▱▱▱▱", "▰▰▰▱▱▱▱▱▱", 
            "▰▰▰▰▱▱▱▱▱▱", "▰▰▰▰▰▱▱▱▱▱", "▰▰▰▰▰▰▱▱▱▱", "▰▰▰▰▰▰▰▱▱▱",
            "▰▰▰▰▰▰▰▰▱▱", "▰▰▰▰▰▰▰▰▰▱", "▰▰▰▰▰▰▰▰▰▰"]

    texts = ["Получаю ссылку...", "Скачиваю в максимальном качестве...", "Обрабатываю...", "Готовлю к отправке..."]

    for text in texts:
        for bar in bars:
            try:
                await message.edit_text(f"<b>{text}</b>\n\n{bar} {int(bars.index(bar)/len(bars)*100)}%")
            except:
                pass
            await asyncio.sleep(0.2)


# === Универсальная функция скачивания ===
async def download_media(url: str, no_watermark: bool = True):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0 Safari/537.36"}

    async with aiohttp.ClientSession(headers=headers, timeout=aiohttp.ClientTimeout(total=90)) as session:
        # TikTok
        if "tiktok.com" in url or "vm.tiktok.com" in url:
            api = "https://tikwm.com/api/"
            params = {"url": url, "hd": "1" if no_watermark else "0"}
            async with session.get(api, params=params) as resp:
                data = await resp.json()

            if data.get("code") != 0:
                raise Exception("TikTok: видео не найдено или приватное")

            video_url = data["data"]["play"] if no_watermark else data["data"]["wmplay"]
            filename = f"downloads/tiktok_{int(time.time())}.mp4"
            async with session.get(video_url) as r:
                with open(filename, "wb") as f:
                    f.write(await r.read())
            return filename, "video"

        # YouTube & Shorts
        elif "youtube.com" in url or "youtu.be" in url:
            import yt_dlp
            ydl_opts = {
                'format': 'best[height<=1080]/best',
                'outtmpl': f'downloads/yt_{int(time.time())}.%(ext)s',
                'merge_output_format': 'mp4',
                'quiet': True,
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=True)
                filename = ydl.prepare_filename(info)
                if filename.endswith(".webm"):
                    os.rename(filename, filename.replace(".webm", ".mp4"))
                    filename = filename.replace(".webm", ".mp4")
                return filename, "video"

        # Instagram
        elif "instagram.com" in url:
            api_url = f"https://api.saveinsta.app/v1/download?url={url}"
            async with session.get(api_url) as resp:
                data = await resp.json()
            if not data.get("success"):
                raise Exception("Instagram: не удалось получить ссылку")
            media_url = data["data"][0]["url"]
            ext = "mp4" if "video" in data["data"][0]["type"] else media_url.split(".")[-1]
            filename = f"downloads/insta_{int(time.time())}.{ext}"
            async with session.get(media_url) as r:
                with open(filename, "wb") as f:
                    f.write(await r.read())
            return filename, "video" if ext == "mp4" else "photo"

        # Прямые ссылки и другие
        else:
            async with session.head(url) as head:
                ctype = head.headers.get("content-type", "")
            ext = "mp4" if "video" in ctype else "jpg"
            filename = f"downloads/direct_{int(time.time())}.{ext}"
            async with session.get(url) as r:
                with open(filename, "wb") as f:
                    async for chunk in r.content.iter_chunked(1024*1024):
                        f.write(chunk)
            return filename, "video" if ext == "mp4" else "photo"


# === Команды и колбэки ===
@dp.message(CommandStart())
async def start(message: types.Message):
    await message.answer(
        "DownRexBot 2025 — лучший даунлоадер в Telegram!\n\n"
        "Скачиваю с:\n"
        "• TikTok (без водяного знака по умолчанию)\n"
        "• YouTube / Shorts\n"
        "• Instagram\n"
        "• Instagram Reels / Посты / Сторис\n"
        "• Pinterest\n"
        "• Любые прямые ссылки\n\n"
        "Просто отправь ссылку — я всё сделаю за секунды!",
        reply_markup=get_main_keyboard(message.from_user.id)
    )

@dp.callback_query(F.data == "wm_on")
async def wm_on(callback: CallbackQuery):
    user_settings[callback.from_user.id]["no_watermark"] = False
    await callback.answer("Водяной знак включён")
    await callback.message.edit_reply_markup(reply_markup=get_main_keyboard(callback.from_user.id))

@dp.callback_query(F.data == "wm_off")
async def wm_off(callback: CallbackQuery):
    user_settings[callback.from_user.id]["no_watermark"] = True
    await callback.answer("Водяной знак выключен")
    await callback.message.edit_reply_markup(reply_markup=get_main_keyboard(callback.from_user.id))

@dp.callback_query(F.data == "help")
async def help_cmd(callback: CallbackQuery):
    text = (
        "Как пользоваться:\n\n"
        "Просто пришли любую ссылку из:\n"
        "• TikTok\n"
        "• YouTube / YouTube Shorts\n"
        "• Instagram (Reels, посты, сторис)\n"
        "• Pinterest\n"
        "• Прямая ссылка на видео/фото\n\n"
        "Переключатель водяного знака работает только для TikTok"
    )
    await callback.message.edit_text(text, reply_markup=get_main_keyboard(callback.from_user.id))
    await callback.answer()

@dp.callback_query(F.data == "stats")
async def stats_cmd(callback: CallbackQuery):
    await callback.message.edit_text(
        f"Статистика DownRexBot:\n\n"
        f"Всего скачано: <b>{stats['total']}</b>\n"
        f"Видео: <b>{stats['video']}</b>\n"
        f"Фото: <b>{stats['photo']}</b>\n"
        f"Ошибок: <b>{stats['failed']}</b>\n\n"
        f"Работаю без остановки с любовью",
        reply_markup=get_main_keyboard(callback.from_user.id)
    )
    await callback.answer()

@dp.callback_query(F.data == "about")
async def about_cmd(callback: CallbackQuery):
    await callback.message.edit_text(
        "Об авторе\n\n"
        "Привет! Меня написал:\n"
        "@nextesyy\n\n"
        "Если бот тебе нравится — просто напиши мне, буду рад фидбеку!",
        reply_markup=get_main_keyboard(callback.from_user.id)
    )
    await callback.answer()


# === Основной обработчик ссылок ===
@dp.message()
async def handle_message(message: types.Message):
    user_id = message.from_user.id
    url = message.text.strip()

    # Rate-limit
    now = time.time()
    if user_id in last_request and now - last_request[user_id] < 3:
        await message.answer("Слишком быстро! Подожди 3 секунды")
        return
    last_request[user_id] = now

    if not url.startswith(("http://", "https://", "www.")):
        await message.answer("Это не похоже на ссылку...")
        return
    if url.startswith("www."):
        url = "https://" + url

    status = await message.answer("Запускаю турбо-режим...")

    try:
        await smooth_progress(status)

        file_path, media_type = await download_media(url, no_watermark=user_settings[user_id]["no_watermark"])

        size_mb = round(os.path.getsize(file_path) / 1048576, 2)
        domain = url.split("/")[2].replace("www.", "").split("?")[0].capitalize()

        caption = f"Источник: <b>{domain}</b>\nРазмер: <b>{size_mb} МБ</b>\nDownRexBot 2025"

        stats['total'] += 1
        stats[media_type] += 1

        await status.edit_text("Отправляю...")

        kb = get_main_keyboard(user_id)

        if media_type == "photo":
            await bot.send_photo(message.chat.id, FSInputFile(file_path), caption=caption, reply_markup=kb)
        else:
            await bot.send_video(message.chat.id, FSInputFile(file_path), caption=caption,
                                 supports_streaming=True, reply_markup=kb)

        os.remove(file_path)
        await status.delete()

        done = await message.answer("Готово за секунды!")
        await asyncio.sleep(3)
        await done.delete()

    except Exception as e:
        logger.error(f"Ошибка: {e}", exc_info=True)
        stats['failed'] += 1
        await status.edit_text("Не удалось скачать...\nПопробуй другую ссылку")
        await asyncio.sleep(8)
        await status.delete()


async def main():
    print("DownRexBot 2025 успешно запущен!")
    await dp.start_polling(bot)

if __name__ == '__main__':
    asyncio.run(main())