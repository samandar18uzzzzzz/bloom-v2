import os
import asyncio
import logging
import json
from aiohttp import web
import aiohttp

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID  = os.environ.get("ADMIN_ID", "0")
PORT      = int(os.environ.get("PORT", "8080"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

async def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    async with aiohttp.ClientSession() as s:
        await s.post(f"{TG_API}/sendMessage", json=payload)

async def edit_markup(chat_id, message_id, reply_markup):
    payload = {"chat_id": chat_id, "message_id": message_id, "reply_markup": json.dumps(reply_markup)}
    async with aiohttp.ClientSession() as s:
        await s.post(f"{TG_API}/editMessageReplyMarkup", json=payload)

async def answer_callback(callback_id, text=""):
    async with aiohttp.ClientSession() as s:
        await s.post(f"{TG_API}/answerCallbackQuery", json={"callback_query_id": callback_id, "text": text})

async def handle_update(data):
    # /start
    if "message" in data:
        msg = data["message"]
        text = msg.get("text", "")
        chat_id = msg["chat"]["id"]

        if text == "/start":
            kb = {"inline_keyboard": [[
                {"text": "🍕 Do'konni ochish", "url": "https://t.me/bloomuz_bot/fastfood"}
            ], [
                {"text": "🙋 Yordam", "callback_data": "help"}
            ]]}
            await send_message(chat_id,
                "🌸 *Bloom Fast Food ga xush kelibsiz!*\n\n"
                "Tez va mazali taomlar eshigingizgacha! 🚀\n\n"
                "Buyurtma berish uchun do'konni oching 👇",
                kb)

        elif text == "/help":
            await send_message(chat_id,
                "🙋 *Yordam*\n\n"
                "📞 Tel: +998 78 555 08 08\n"
                "✈️ Telegram: @bloom\\_support\n"
                "🕐 Ish vaqti: 08:40 — 22:40\n\n"
                "📍 Bloom Bozor: Angren, Bozor yaqini\n"
                "📍 Bloom Kalso: Angren, Kalso")

        elif text == "/orders":
            await send_message(chat_id,
                "📋 *Zakaslaringizni ko'rish uchun:*\n\n"
                "Do'konni ochib *Tarix* bo'limiga o'ting 👇",
                {"inline_keyboard": [[
                    {"text": "📋 Zakaslarim", "url": "https://t.me/bloomuz_bot/fastfood"}
                ]]})

    # Callback
    elif "callback_query" in data:
        cb = data["callback_query"]
        cb_id = cb["id"]
        cb_data = cb.get("data", "")
        chat_id = cb["message"]["chat"]["id"]
        msg_id = cb["message"]["message_id"]

        if cb_data == "help":
            await answer_callback(cb_id)
            await send_message(chat_id,
                "🙋 *Yordam*\n\n"
                "📞 Tel: +998 78 555 08 08\n"
                "✈️ @bloom\\_support\n"
                "🕐 08:40 — 22:40")

        elif cb_data == "done":
            await answer_callback(cb_id)

        elif cb_data.startswith("accept_"):
            parts = cb_data.split("_")
            user_id = parts[1]
            order_id = parts[2]
            await answer_callback(cb_id, "✅ Qabul qilindi!")
            # Admin xabarini yangilash
            await edit_markup(chat_id, msg_id, {"inline_keyboard": [[
                {"text": "✅ Qabul qilindi", "callback_data": "done"},
                {"text": "🚚 Yo'lda", "callback_data": f"way_{user_id}_{order_id}"},
            ]]})
            # Mijozga xabar
            if user_id and user_id != "0":
                try:
                    await send_message(int(user_id),
                        f"✅ *Buyurtmangiz qabul qilindi!*\n\n"
                        f"🆔 #{order_id}\n"
                        f"👨‍🍳 Tayyorlanmoqda...\n\n"
                        f"📞 Savollar: +998 78 555 08 08")
                except: pass

        elif cb_data.startswith("way_"):
            parts = cb_data.split("_")
            user_id = parts[1]
            order_id = parts[2]
            await answer_callback(cb_id, "🚚 Yo'lda!")
            await edit_markup(chat_id, msg_id, {"inline_keyboard": [[
                {"text": "🚚 Yo'lda", "callback_data": "done"},
                {"text": "🎉 Yetkazildi", "callback_data": f"done_{user_id}_{order_id}"},
            ]]})
            if user_id and user_id != "0":
                try:
                    await send_message(int(user_id),
                        f"🚚 *Buyurtmangiz yo'lda!*\n\n"
                        f"🆔 #{order_id}\n"
                        f"⏰ Tez orada yetkazib beramiz!")
                except: pass

        elif cb_data.startswith("done_"):
            parts = cb_data.split("_")
            user_id = parts[1]
            order_id = parts[2]
            await answer_callback(cb_id, "🎉 Yetkazildi!")
            await edit_markup(chat_id, msg_id, {"inline_keyboard": [[
                {"text": "🎉 Yetkazildi!", "callback_data": "done"},
            ]]})
            if user_id and user_id != "0":
                try:
                    await send_message(int(user_id),
                        f"🎉 *Buyurtmangiz yetkazildi!*\n\n"
                        f"🆔 #{order_id}\n"
                        f"Rahmat! Yana keling 🌸\n\n"
                        f"⭐ Baholang: t.me/bloomuz\\_bot/fastfood")
                except: pass

        elif cb_data.startswith("reject_"):
            parts = cb_data.split("_")
            user_id = parts[1]
            order_id = parts[2]
            await answer_callback(cb_id, "❌ Bekor qilindi!")
            await edit_markup(chat_id, msg_id, {"inline_keyboard": [[
                {"text": "❌ Bekor qilindi", "callback_data": "done"}
            ]]})
            if user_id and user_id != "0":
                try:
                    await send_message(int(user_id),
                        f"😔 *Kechirasiz, hozircha buyurtmani qabul qilib bo'lmaydi.*\n\n"
                        f"🆔 #{order_id}\n"
                        f"📞 Batafsil: +998 78 555 08 08")
                except: pass

def cors_headers():
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }

async def telegram_webhook(request):
    data = await request.json()
    asyncio.create_task(handle_update(data))
    return web.Response(text="ok", headers=cors_headers())

async def order_webhook(request):
    if request.method == "OPTIONS":
        return web.Response(status=200, headers=cors_headers())
    try:
        data = await request.json()
        logger.info(f"Zakaz keldi: {data}")
        o = data.get("order", {})
        items = "\n".join([
            f"  {i.get('emoji','')} {i.get('nom','')} x{i.get('n',1)} = {i.get('narx',0)*i.get('n',1):,} so'm"
            for i in o.get("items", [])
        ])
        text = (
            f"🌸 *YANGI ZAKAZ!*\n\n"
            f"🆔 {o.get('id','')}\n"
            f"👤 {o.get('name','')}\n"
            f"📞 {o.get('phone','')}\n"
            f"📍 {o.get('addr','')}\n"
            f"{o.get('type','')} | 🕐 {o.get('slot','')}\n"
            f"{o.get('pay','')}\n\n"
            f"🛒 *Mahsulotlar:*\n{items}\n\n"
            f"💰 *Jami: {o.get('total',0):,} so'm*"
        )
        uid = str(o.get("chat_id", 0))
        oid = o.get("id","").replace("#","")
        kb = {"inline_keyboard": [[
            {"text": "✅ Qabul qilish", "callback_data": f"accept_{uid}_{oid}"},
            {"text": "❌ Bekor qilish", "callback_data": f"reject_{uid}_{oid}"},
        ]]}
        await send_message(ADMIN_ID, text, kb)
        return web.json_response({"ok": True}, headers=cors_headers())
    except Exception as e:
        logger.error(f"Xato: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=500, headers=cors_headers())

async def health(request):
    return web.Response(text="Bloom Bot ishlayapti! 🌸", headers=cors_headers())

async def setup_webhook(app):
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    if render_url:
        async with aiohttp.ClientSession() as s:
            r = await s.post(f"{TG_API}/setWebhook", json={"url": f"{render_url}/tg"})
            logger.info(f"Webhook: {render_url}/tg — {await r.text()}")

app = web.Application()
app.router.add_get("/", health)
app.router.add_post("/tg", telegram_webhook)
app.router.add_post("/webhook", order_webhook)
app.router.add_route("OPTIONS", "/webhook", order_webhook)
app.on_startup.append(setup_webhook)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT)
