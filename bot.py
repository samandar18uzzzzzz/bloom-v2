import os
import asyncio
import logging
import json
from datetime import datetime
from aiohttp import web
import aiohttp

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID  = os.environ.get("ADMIN_ID", "0")
PORT      = int(os.environ.get("PORT", "8080"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ── MA'LUMOTLAR BAZASI ─────────────────────────
orders_db = {}   # {order_id: order_data}
is_open = True   # Ish vaqti
daily_stats = {} # {date: {count, total}}

async def send_message(chat_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    async with aiohttp.ClientSession() as s:
        r = await s.post(f"{TG_API}/sendMessage", json=payload)
        return await r.json()

async def edit_markup(chat_id, message_id, reply_markup):
    payload = {"chat_id": chat_id, "message_id": message_id, "reply_markup": json.dumps(reply_markup)}
    async with aiohttp.ClientSession() as s:
        await s.post(f"{TG_API}/editMessageReplyMarkup", json=payload)

async def edit_message(chat_id, message_id, text, reply_markup=None):
    payload = {"chat_id": chat_id, "message_id": message_id, "text": text, "parse_mode": "Markdown"}
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)
    async with aiohttp.ClientSession() as s:
        await s.post(f"{TG_API}/editMessageText", json=payload)

async def answer_callback(callback_id, text=""):
    async with aiohttp.ClientSession() as s:
        await s.post(f"{TG_API}/answerCallbackQuery", json={"callback_query_id": callback_id, "text": text})

def admin_kb(order_id, uid):
    return {"inline_keyboard": [
        [
            {"text": "✅ Qabul qilish", "callback_data": f"accept_{uid}_{order_id}"},
            {"text": "❌ Bekor qilish", "callback_data": f"reject_{uid}_{order_id}"},
        ],
        [
            {"text": "📞 Qo'ng'iroq qilish", "callback_data": f"call_{uid}_{order_id}"},
            {"text": "⏱️ Kechikamiz", "callback_data": f"late_{uid}_{order_id}"},
        ],
        [
            {"text": "📝 Izoh yozish", "callback_data": f"note_{uid}_{order_id}"},
            {"text": "🗺️ Xaritada ko'rish", "callback_data": f"map_{uid}_{order_id}"},
        ],
    ]}

def format_stats():
    today = datetime.now().strftime("%Y-%m-%d")
    stats = daily_stats.get(today, {"count": 0, "total": 0})
    
    # Faol zakaslar
    active = [o for o in orders_db.values() if o.get("status") not in ["done", "rejected"]]
    done = [o for o in orders_db.values() if o.get("status") == "done"]
    
    text = (
        f"📊 *Bugungi statistika*\n"
        f"📅 {datetime.now().strftime('%d.%m.%Y')}\n\n"
        f"📦 Jami zakaslar: *{stats['count']}*\n"
        f"💰 Jami summa: *{stats['total']:,} so'm*\n\n"
        f"⏳ Faol zakaslar: *{len(active)}*\n"
        f"✅ Yetkazilgan: *{len(done)}*\n"
        f"❌ Bekor qilingan: *{len([o for o in orders_db.values() if o.get('status') == 'rejected'])}*\n\n"
        f"🏪 Do'kon: *{'🟢 Ochiq' if is_open else '🔴 Yopiq'}*"
    )
    return text

def format_order_list():
    active = [(oid, o) for oid, o in orders_db.items() if o.get("status") not in ["done", "rejected"]]
    if not active:
        return "📋 *Faol zakaslar yo'q*"
    
    text = f"📋 *Faol zakaslar ({len(active)} ta)*\n\n"
    for oid, o in active[-10:]:  # Oxirgi 10 ta
        status_emoji = {"new": "🆕", "prep": "👨‍🍳", "way": "🚚"}.get(o.get("status", "new"), "❓")
        text += (
            f"{status_emoji} *#{oid}*\n"
            f"👤 {o.get('name', '—')} | 📞 {o.get('phone', '—')}\n"
            f"💰 {o.get('total', 0):,} so'm\n"
            f"──────────────\n"
        )
    return text

async def handle_update(data):
    global is_open

    if "message" in data:
        msg = data["message"]
        text = msg.get("text", "")
        chat_id = str(msg["chat"]["id"])

        # Admin buyruqlari
        if chat_id == str(ADMIN_ID):

            if text == "/start" or text == "/menu":
                kb = {"inline_keyboard": [
                    [{"text": "📊 Statistika", "callback_data": "stats"},
                     {"text": "📋 Zakaslar", "callback_data": "orders_list"}],
                    [{"text": "🟢 Ochish" if not is_open else "🔴 Yopish", "callback_data": "toggle_open"}],
                    [{"text": "🍕 Do'konni ochish", "url": "https://t.me/bloomuz_bot/fastfood"}],
                ]}
                await send_message(chat_id,
                    "👨‍💼 *Admin panel*\n\n"
                    f"🏪 Do'kon: {'🟢 Ochiq' if is_open else '🔴 Yopiq'}\n"
                    f"📦 Faol zakaslar: {len([o for o in orders_db.values() if o.get('status') not in ['done','rejected']])}\n\n"
                    "Quyidagi tugmalardan foydalaning:", kb)

            elif text == "/stats":
                await send_message(chat_id, format_stats())

            elif text == "/orders":
                await send_message(chat_id, format_order_list())

            elif text == "/open":
                is_open = True
                await send_message(chat_id, "🟢 Do'kon *ochildi!* Zakaslar qabul qilinmoqda.")

            elif text == "/close":
                is_open = False
                await send_message(chat_id, "🔴 Do'kon *yopildi!* Zakaslar qabul qilinmaydi.")

            elif text == "/help":
                await send_message(chat_id,
                    "👨‍💼 *Admin buyruqlari:*\n\n"
                    "/menu — Admin panel\n"
                    "/stats — Bugungi statistika\n"
                    "/orders — Faol zakaslar\n"
                    "/open — Do'konni ochish\n"
                    "/close — Do'konni yopish\n"
                    "/help — Yordam")

        # Mijoz buyruqlari
        else:
            if text == "/start":
                if not is_open:
                    await send_message(chat_id,
                        "🔴 *Kechirasiz, hozir do'kon yopiq!*\n\n"
                        "🕐 Ish vaqtimiz: 08:40 — 22:40\n"
                        "📞 Ma'lumot: +998 78 555 08 08")
                    return

                kb = {"inline_keyboard": [[
                    {"text": "🍕 Do'konni ochish", "url": "https://t.me/bloomuz_bot/fastfood"}
                ], [
                    {"text": "🙋 Yordam", "callback_data": "help"}
                ]]}
                await send_message(chat_id,
                    "🌸 *Bloom Fast Food ga xush kelibsiz!*\n\n"
                    "Tez va mazali taomlar eshigingizgacha! 🚀\n\n"
                    "Buyurtma berish uchun do'konni oching 👇", kb)

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

    elif "callback_query" in data:
        cb = data["callback_query"]
        cb_id = cb["id"]
        cb_data = cb.get("data", "")
        chat_id = str(cb["message"]["chat"]["id"])
        msg_id = cb["message"]["message_id"]

        # ── ADMIN CALLBACKS ────────────────────────
        if chat_id == str(ADMIN_ID):

            if cb_data == "stats":
                await answer_callback(cb_id)
                await send_message(chat_id, format_stats())

            elif cb_data == "orders_list":
                await answer_callback(cb_id)
                await send_message(chat_id, format_order_list())

            elif cb_data == "toggle_open":
                is_open = not is_open
                await answer_callback(cb_id, "🟢 Ochildi!" if is_open else "🔴 Yopildi!")
                await edit_markup(chat_id, msg_id, {"inline_keyboard": [
                    [{"text": "📊 Statistika", "callback_data": "stats"},
                     {"text": "📋 Zakaslar", "callback_data": "orders_list"}],
                    [{"text": "🟢 Ochish" if not is_open else "🔴 Yopish", "callback_data": "toggle_open"}],
                    [{"text": "🍕 Do'konni ochish", "url": "https://t.me/bloomuz_bot/fastfood"}],
                ]})

            elif cb_data.startswith("accept_"):
                parts = cb_data.split("_")
                uid, oid = parts[1], parts[2]
                await answer_callback(cb_id, "✅ Qabul qilindi!")
                if oid in orders_db:
                    orders_db[oid]["status"] = "prep"
                await edit_markup(chat_id, msg_id, {"inline_keyboard": [
                    [{"text": "✅ Qabul qilindi", "callback_data": "done"}],
                    [{"text": "🚚 Yo'lda", "callback_data": f"way_{uid}_{oid}"},
                     {"text": "📞 Qo'ng'iroq", "callback_data": f"call_{uid}_{oid}"}],
                    [{"text": "⏱️ Kechikamiz", "callback_data": f"late_{uid}_{oid}"},
                     {"text": "📝 Izoh", "callback_data": f"note_{uid}_{oid}"}],
                ]})
                if uid and uid != "0":
                    try:
                        await send_message(int(uid),
                            f"✅ *Buyurtmangiz qabul qilindi!*\n\n"
                            f"🆔 #{oid}\n"
                            f"👨‍🍳 Tayyorlanmoqda...\n\n"
                            f"📞 Savollar: +998 78 555 08 08")
                    except: pass

            elif cb_data.startswith("way_"):
                parts = cb_data.split("_")
                uid, oid = parts[1], parts[2]
                await answer_callback(cb_id, "🚚 Yo'lda!")
                if oid in orders_db:
                    orders_db[oid]["status"] = "way"
                await edit_markup(chat_id, msg_id, {"inline_keyboard": [
                    [{"text": "🚚 Yo'lda", "callback_data": "done"}],
                    [{"text": "🎉 Yetkazildi", "callback_data": f"delivered_{uid}_{oid}"},
                     {"text": "📞 Qo'ng'iroq", "callback_data": f"call_{uid}_{oid}"}],
                    [{"text": "⏱️ Kechikamiz", "callback_data": f"late_{uid}_{oid}"},
                     {"text": "📝 Izoh", "callback_data": f"note_{uid}_{oid}"}],
                ]})
                if uid and uid != "0":
                    try:
                        await send_message(int(uid),
                            f"🚚 *Buyurtmangiz yo'lda!*\n\n"
                            f"🆔 #{oid}\n"
                            f"⏰ Tez orada yetkazib beramiz!")
                    except: pass

            elif cb_data.startswith("delivered_"):
                parts = cb_data.split("_")
                uid, oid = parts[1], parts[2]
                await answer_callback(cb_id, "🎉 Yetkazildi!")
                if oid in orders_db:
                    orders_db[oid]["status"] = "done"
                await edit_markup(chat_id, msg_id, {"inline_keyboard": [[
                    {"text": "🎉 Yetkazildi!", "callback_data": "done"}
                ]]})
                if uid and uid != "0":
                    try:
                        await send_message(int(uid),
                            f"🎉 *Buyurtmangiz yetkazildi!*\n\n"
                            f"🆔 #{oid}\n"
                            f"Rahmat! Yana keling 🌸")
                    except: pass

            elif cb_data.startswith("reject_"):
                parts = cb_data.split("_")
                uid, oid = parts[1], parts[2]
                await answer_callback(cb_id, "❌ Bekor qilindi!")
                if oid in orders_db:
                    orders_db[oid]["status"] = "rejected"
                await edit_markup(chat_id, msg_id, {"inline_keyboard": [[
                    {"text": "❌ Bekor qilindi", "callback_data": "done"}
                ]]})
                if uid and uid != "0":
                    try:
                        await send_message(int(uid),
                            f"😔 *Kechirasiz, hozircha buyurtmani qabul qilib bo'lmaydi.*\n\n"
                            f"🆔 #{oid}\n"
                            f"📞 Batafsil: +998 78 555 08 08")
                    except: pass

            elif cb_data.startswith("call_"):
                parts = cb_data.split("_")
                uid, oid = parts[1], parts[2]
                await answer_callback(cb_id)
                o = orders_db.get(oid, {})
                phone = o.get("phone", "—")
                await send_message(chat_id,
                    f"📞 *#{oid} — Mijoz telefoni:*\n\n"
                    f"`{phone}`\n\n"
                    f"[📲 Qo'ng'iroq qilish](tel:{phone.replace(' ', '').replace('+', '')})")

            elif cb_data.startswith("late_"):
                parts = cb_data.split("_")
                uid, oid = parts[1], parts[2]
                await answer_callback(cb_id, "⏱️ Xabar yuborildi!")
                if uid and uid != "0":
                    try:
                        await send_message(int(uid),
                            f"⏱️ *Kechirasiz, kechikish bo'lmoqda!*\n\n"
                            f"🆔 #{oid}\n"
                            f"Buyurtmangiz tez orada yetkaziladi.\n"
                            f"📞 Ma'lumot: +998 78 555 08 08")
                    except: pass

            elif cb_data.startswith("note_"):
                parts = cb_data.split("_")
                uid, oid = parts[1], parts[2]
                await answer_callback(cb_id)
                await send_message(chat_id,
                    f"📝 *#{oid} uchun izoh yozing:*\n\n"
                    f"Keyingi xabaringiz mijozga yuboriladi.\n"
                    f"Format: `izoh {oid} <matn>`")

            elif cb_data.startswith("map_"):
                parts = cb_data.split("_")
                uid, oid = parts[1], parts[2]
                await answer_callback(cb_id)
                o = orders_db.get(oid, {})
                addr = o.get("addr", "")
                await send_message(chat_id,
                    f"🗺️ *#{oid} — Manzil:*\n\n"
                    f"📍 `{addr}`\n\n"
                    f"[🗺️ Google Maps da qidirish](https://maps.google.com/?q={addr.replace(' ', '+')})")

            elif cb_data == "done":
                await answer_callback(cb_id)

        # ── MIJOZ CALLBACKS ────────────────────────
        else:
            if cb_data == "help":
                await answer_callback(cb_id)
                await send_message(chat_id,
                    "🙋 *Yordam*\n\n"
                    "📞 Tel: +998 78 555 08 08\n"
                    "✈️ @bloom\\_support\n"
                    "🕐 08:40 — 22:40")
            elif cb_data == "done":
                await answer_callback(cb_id)

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
        o = data.get("order", {})
        order_id = o.get("id","").replace("#","")
        uid = str(o.get("chat_id", 0))

        # Do'kon yopiqmi?
        if not is_open:
            return web.json_response({
                "ok": False,
                "error": "closed",
                "message": "Do'kon hozir yopiq!"
            }, headers=cors_headers())

        # Serverda saqlash
        orders_db[order_id] = {
            "status": "new",
            "user_id": uid,
            "total": o.get("total", 0),
            "name": o.get("name", ""),
            "phone": o.get("phone", ""),
            "addr": o.get("addr", ""),
            "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
        }

        # Statistika yangilash
        today = datetime.now().strftime("%Y-%m-%d")
        if today not in daily_stats:
            daily_stats[today] = {"count": 0, "total": 0}
        daily_stats[today]["count"] += 1
        daily_stats[today]["total"] += o.get("total", 0)

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
        await send_message(ADMIN_ID, text, admin_kb(order_id, uid))
        return web.json_response({"ok": True}, headers=cors_headers())
    except Exception as e:
        logger.error(f"Xato: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=500, headers=cors_headers())

async def status_webhook(request):
    if request.method == "OPTIONS":
        return web.Response(status=200, headers=cors_headers())
    try:
        data = await request.json()
        order_ids = data.get("ids", [])
        result = {}
        for oid in order_ids:
            clean = oid.replace("#", "")
            if clean in orders_db:
                result[oid] = orders_db[clean]["status"]
        return web.json_response({
            "ok": True,
            "statuses": result,
            "is_open": is_open
        }, headers=cors_headers())
    except Exception as e:
        return web.json_response({"ok": False}, status=500, headers=cors_headers())

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
app.router.add_post("/status", status_webhook)
app.router.add_route("OPTIONS", "/webhook", order_webhook)
app.router.add_route("OPTIONS", "/status", status_webhook)
app.on_startup.append(setup_webhook)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT)
