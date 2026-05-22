import os
import base64
import asyncio
import threading
from io import BytesIO
from concurrent.futures import ThreadPoolExecutor

import pandas as pd
import requests

from ddgs import DDGS

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ParseMode
from aiogram.types import (
    Message,
    CallbackQuery,
    BufferedInputFile,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage


BOT_TOKEN = os.getenv("BOT_TOKEN")
PROXY_API_KEY = os.getenv("PROXY_API_KEY")

if not BOT_TOKEN:
    raise Exception("BOT_TOKEN not found")

if not PROXY_API_KEY:
    raise Exception("PROXY_API_KEY not found")


bot = Bot(
    token=BOT_TOKEN,
    default=DefaultBotProperties(parse_mode=ParseMode.HTML)
)

dp = Dispatcher(storage=MemoryStorage())

executor = ThreadPoolExecutor(max_workers=10)

user_data = {}

MAX_RESULTS = 5

MARKETPLACES = [
    "ozon.ru",
    "wildberries.ru",
    "market.yandex.ru"
]


@dp.message(F.text == "/start")
async def start(message: Message):

    text = (
        f"Привет, {message.from_user.first_name}!\n"
        "Отправь мне картинку, и я найду похожие изображения\n"
    )

    await message.answer(text)


# GPT VISION
def detect_brand_sync(image_bytes: bytes):

    base64_image = base64.b64encode(image_bytes).decode("utf-8")

    headers = {
        "Authorization": f"Bearer {PROXY_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "gpt-4o-mini",
        "messages": [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": (
                            "Определи бренд на изображении.\n"
                            "Ответь ТОЛЬКО названием бренда.\n"
                            "Без пояснений."
                        )
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:image/jpeg;base64,{base64_image}"
                        }
                    }
                ]
            }
        ],
        "max_tokens": 20
    }

    response = requests.post(
        "https://api.proxyapi.ru/openai/v1/chat/completions",
        headers=headers,
        json=payload,
        timeout=30
    )

    response.raise_for_status()

    result = response.json()

    brand = result["choices"][0]["message"]["content"]

    brand = brand.strip().upper()

    return brand

async def detect_brand(image_bytes: bytes):

    loop = asyncio.get_event_loop()

    return await loop.run_in_executor(
        executor,
        detect_brand_sync,
        image_bytes
    )


# поиск
def search_brand_sync(brand: str):

    results = []

    SEARCH_PATTERNS = [

        # обычный поиск
        "{brand} site:{market}",

        # товары
        "{brand} купить site:{market}",

        # каталог
        "{brand} товар site:{market}",

        # карточки
        "{brand} product site:{market}",
    ]

    with DDGS() as ddgs:

        for market in MARKETPLACES:
         for pattern in SEARCH_PATTERNS:

                try:

                    query = pattern.format(
                        brand=brand,
                        market=market
                    )

                    search_results = ddgs.text(
                        query,
                        max_results=MAX_RESULTS
                    ) or []

                    for r in search_results:

                        url = r.get("href")

                        title = r.get("title", "")

                        body = r.get("body", "")

                        if not url:
                            continue

                        low = url.lower()

                        # фильтр мусора
                        if any(x in low for x in [
                            "login",
                            "signup",
                            "auth",
                            "help",
                            "support",
                            "catalog",
                            "search",
                            "feedback",
                            "terms"
                        ]):
                            continue

                        results.append({
                            "url": url,
                            "title": title,
                            "body": body,
                            "type": "market"
                        })

                except Exception as e:

                    print("SEARCH ERROR:", e)


    # УБИРАЕМ ДУБЛИ
    unique = []

    seen = set()

    for item in results:

        if item["url"] not in seen:

            seen.add(item["url"])

            unique.append(item)

            if len(unique) >= 50:
                return unique

    return unique


async def search_brand(brand: str):

    loop = asyncio.get_event_loop()

    return await loop.run_in_executor(
        executor,
        search_brand_sync,
        brand
    )


# KEYBOARD
def get_keyboard(page):

    keyboard = []

    nav = []

    if page > 0:
        nav.append(
            InlineKeyboardButton(
                text="⬅️ Назад",
                callback_data="prev"
            )
        )

    nav.append(
        InlineKeyboardButton(
            text="Вперёд ➡️",
            callback_data="next"
        )
    )

    keyboard.append(nav)

    keyboard.append([
        InlineKeyboardButton(
            text="Общие результаты",
            callback_data="general"
        ),
        InlineKeyboardButton(
            text="Маркетплейсы",
            callback_data="market"
        )
    ])

    keyboard.append([
        InlineKeyboardButton(
            text="Excel / CSV",
            callback_data="excel"
        )
    ])

    return InlineKeyboardMarkup(
        inline_keyboard=keyboard
    )


# SHOW RESULTS
async def show_results(
    chat_id,
    user_id,
    message_id=None
):

    data = user_data[user_id]

    results = data["results"]
    page = data["page"]
    filter_type = data["filter"]
    if filter_type == "market":
        results = [
            r for r in results
            if r["type"] == "market"
        ]

    per_page = 10

    total_pages = max(
        1,
        (len(results) + per_page - 1) // per_page
    )

    if page >= total_pages:
        page = total_pages - 1
        data["page"] = page

    start = page * per_page
    end = start + per_page

    page_results = results[start:end]

    brand = data["brand"]

    text = (
        f"<b>Бренд:</b> {brand}\n"
        f"<b>Страница:</b> {page + 1}/{total_pages}\n\n"
    )

    if not page_results:

        text += "Ничего не найдено"

    else:

        for i, item in enumerate(page_results, start=1):

            url = item["url"]

            text += (
                f"{start + i}. "
                f'<a href="{url}">Открыть ссылку</a>\n\n'
            )

    markup = get_keyboard(page)

    if message_id:

        await bot.edit_message_text(
            text=text,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=markup
        )

    else:

        await bot.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=markup
        )


# PHOTO
@dp.message(F.photo)
async def photo_handler(message: Message):

    wait_msg = await message.answer(
        "Анализирую изображение..."
    )

    try:

        photo = message.photo[-1]

        file = await bot.get_file(photo.file_id)

        downloaded = await bot.download_file(file.file_path)

        image_bytes = downloaded.read()


        # DETECT BRAND
        brand = await detect_brand(image_bytes)

        await wait_msg.edit_text(
            f"Бренд определен: <b>{brand}</b>\n"
            f"Ищу товары..."
        )

        # SEARCH
        results = await search_brand(brand)

        user_data[message.from_user.id] = {
            "brand": brand,
            "results": results,
            "page": 0,
            "filter": "all"
        }

        await show_results(
            chat_id=message.chat.id,
            user_id=message.from_user.id
        )

        await wait_msg.delete()

    except Exception as e:

        await wait_msg.edit_text(
            f"Ошибка:\n{str(e)}"
        )


# CALLBACKS
@dp.callback_query()
async def callbacks(call: CallbackQuery):

    user_id = call.from_user.id

    if user_id not in user_data:
        return

    data = user_data[user_id]

    # NEXT
    if call.data == "next":

        data["page"] += 1


    # PREV
    elif call.data == "prev":

        if data["page"] > 0:
            data["page"] -= 1


    # GENERAL
    elif call.data == "general":

        data["filter"] = "all"
        data["page"] = 0


    # MARKET
    elif call.data == "market":

        data["filter"] = "market"
        data["page"] = 0


    # CSV
    elif call.data == "excel":

        filter_type = data["filter"]

        if filter_type == "all":

            urls = [
                r["url"]
                for r in data["results"]
            ]

        else:

            urls = [
                r["url"]
                for r in data["results"]
                if r["type"] == filter_type
            ]

        df = pd.DataFrame({
            "Бренд": [data["brand"]] * len(urls),
            "Ссылка": urls
        })

        csv_buffer = BytesIO()
        df.to_csv(
            csv_buffer,
            index=False,
            encoding="utf-8-sig"
        )

        csv_buffer.seek(0)

        file = BufferedInputFile(
            csv_buffer.read(),
            filename=f"{data['brand']}.csv"
        )

        await bot.send_document(
            chat_id=call.message.chat.id,
            document=file,
            caption=f"CSV файл: {data['brand']}"
        )

        await call.answer(
            "CSV файл отправлен"
        )

        return

    await show_results(
        chat_id=call.message.chat.id,
        user_id=user_id,
        message_id=call.message.message_id
    )

    await call.answer()


# MAIN
async def main():

    print("BOT STARTED")

    await dp.start_polling(bot)
    
    from flask import Flask
    import threading

    app = Flask(__name__)

    @app.route("/")
    def home():
        return "Bot is running"

    def run_bot():
        asyncio.run(main())

if __name__ == "__main__":

    threading.Thread(target=run_bot).start()

    port = int(os.environ.get("PORT", 10000))

    app.run(
        host="0.0.0.0",
        port=port
    )