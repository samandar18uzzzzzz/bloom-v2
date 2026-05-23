import os
import asyncio
import logging
import json
import time
from datetime import datetime
from aiohttp import web
import aiohttp

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
# Bir nechta admin: "123,456,789" formatida
ADMIN_IDS = [x.strip() for x in os.environ.get("ADMIN_ID", "0").split(",") if x.strip()]
ADMIN_ID = ADMIN_IDS[0] if ADMIN_IDS else "0"  # Asosiy admin
PORT      = int(os.environ.get("PORT", "8080"))

# Yetkazish sozlamalari
FREE_DELIVERY_MIN = 50000   # Bepul yetkazish chegarasi
DELIVERY_FEE = 10000        # Yetkazish narxi
MIN_ORDER = 30000           # Minimal zakaz

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TG_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ── MA'LUMOTLAR BAZASI (fayl bilan saqlash) ──────
DB_FILE = "/tmp/bloom_orders.json"
orders_db = {}
is_open = True
daily_stats = {}

# Rate limiting: {user_id: [timestamp, ...]}
rate_limit = {}
RATE_MAX = 5        # 5 ta zakaz
RATE_WINDOW = 300   # 5 daqiqada

def load_db():
    global orders_db, daily_stats, is_open
    try:
        if os.path.exists(DB_FILE):
            with open(DB_FILE, 'r') as f:
                data = json.load(f)
                orders_db = data.get("orders", {})
                daily_stats = data.get("stats", {})
                is_open = data.get("is_open", True)
                logger.info(f"DB yuklandi: {len(orders_db)} zakaz")
    except Exception as e:
        logger.error(f"DB yuklashda xato: {e}")

def save_db():
    try:
        with open(DB_FILE, 'w') as f:
            json.dump({
                "orders": orders_db,
                "stats": daily_stats,
                "is_open": is_open
            }, f)
    except Exception as e:
        logger.error(f"DB saqlashda xato: {e}")

def check_rate_limit(user_id):
    now = time.time()
    uid = str(user_id)
    if uid not in rate_limit:
        rate_limit[uid] = []
    # Eski yozuvlarni tozalash
    rate_limit[uid] = [t for t in rate_limit[uid] if now - t < RATE_WINDOW]
    if len(rate_limit[uid]) >= RATE_MAX:
        return False
    rate_limit[uid].append(now)
    return True

def escape_html(text):
    """XSS himoya - maxsus belgilarni tozalash"""
    if not isinstance(text, str):
        return str(text)
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;")
                .replace("'", "&#39;"))

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

async def answer_callback(callback_id, text=""):
    async with aiohttp.ClientSession() as s:
        await s.post(f"{TG_API}/answerCallbackQuery", json={"callback_query_id": callback_id, "text": text})

async def notify_all_admins(text, reply_markup=None):
    """Barcha adminlarga xabar yuborish"""
    for aid in ADMIN_IDS:
        try:
            await send_message(aid, text, reply_markup)
        except: pass

def admin_kb(order_id, uid):
    return {"inline_keyboard": [
        [
            {"text": "✅ Qabul qilish", "callback_data": f"accept_{uid}_{order_id}"},
            {"text": "❌ Bekor qilish", "callback_data": f"reject_{uid}_{order_id}"},
        ],
        [
            {"text": "📞 Qo'ng'iroq", "callback_data": f"call_{uid}_{order_id}"},
            {"text": "⏱️ Kechikamiz", "callback_data": f"late_{uid}_{order_id}"},
        ],
        [
            {"text": "🗺️ Manzil", "callback_data": f"map_{uid}_{order_id}"},
        ],
    ]}

def format_stats():
    today = datetime.now().strftime("%Y-%m-%d")
    stats = daily_stats.get(today, {"count": 0, "total": 0})
    active = [o for o in orders_db.values() if o.get("status") not in ["done", "rejected"]]
    done = [o for o in orders_db.values() if o.get("status") == "done"]
    rejected = [o for o in orders_db.values() if o.get("status") == "rejected"]
    return (
        f"📊 *Bugungi statistika*\n"
        f"📅 {datetime.now().strftime('%d.%m.%Y')}\n\n"
        f"📦 Jami zakaslar: *{stats['count']}*\n"
        f"💰 Jami summa: *{stats['total']:,} so'm*\n\n"
        f"⏳ Faol: *{len(active)}*\n"
        f"✅ Yetkazilgan: *{len(done)}*\n"
        f"❌ Bekor: *{len(rejected)}*\n\n"
        f"🏪 Do'kon: *{'🟢 Ochiq' if is_open else '🔴 Yopiq'}*"
    )

def format_order_list():
    active = [(oid, o) for oid, o in orders_db.items() if o.get("status") not in ["done", "rejected"]]
    if not active:
        return "📋 *Faol zakaslar yo'q*"
    text = f"📋 *Faol zakaslar ({len(active)} ta)*\n\n"
    for oid, o in active[-10:]:
        se = {"new": "🆕", "prep": "👨‍🍳", "way": "🚚"}.get(o.get("status", "new"), "❓")
        text += (
            f"{se} *#{oid}*\n"
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
        is_admin = chat_id in ADMIN_IDS

        if is_admin:
            if text in ("/start", "/menu"):
                kb = {"inline_keyboard": [
                    [{"text": "📊 Statistika", "callback_data": "stats"},
                     {"text": "📋 Zakaslar", "callback_data": "orders_list"}],
                    [{"text": "🟢 Ochish" if not is_open else "🔴 Yopish", "callback_data": "toggle_open"}],
                    [{"text": "🍕 Do'konni ochish", "url": "https://t.me/bloomuz_bot/fastfood"}],
                ]}
                active = len([o for o in orders_db.values() if o.get('status') not in ['done','rejected']])
                await send_message(chat_id,
                    f"👨‍💼 *Admin panel*\n\n"
                    f"🏪 Do'kon: {'🟢 Ochiq' if is_open else '🔴 Yopiq'}\n"
                    f"📦 Faol zakaslar: {active}", kb)
            elif text == "/stats":
                await send_message(chat_id, format_stats())
            elif text == "/orders":
                await send_message(chat_id, format_order_list())
            elif text == "/open":
                is_open = True; save_db()
                await send_message(chat_id, "🟢 Do'kon *ochildi!*")
            elif text == "/close":
                is_open = False; save_db()
                await send_message(chat_id, "🔴 Do'kon *yopildi!*")
            elif text == "/help":
                await send_message(chat_id,
                    "👨‍💼 *Admin buyruqlari:*\n\n"
                    "/menu — Panel\n/stats — Statistika\n"
                    "/orders — Zakaslar\n/open — Ochish\n"
                    "/close — Yopish")
        else:
            if text == "/start":
                if not is_open:
                    await send_message(chat_id,
                        "🔴 *Kechirasiz, hozir do'kon yopiq!*\n\n"
                        "🕐 Ish vaqtimiz: 08:40 — 22:40\n"
                        "📞 +998 78 555 08 08")
                    return
                kb = {"inline_keyboard": [
                    [{"text": "🍕 Menyuni ochish", "url": "https://t.me/bloomuz_bot/fastfood"}],
                    [{"text": "📞 Bog'lanish", "callback_data": "help"},
                     {"text": "📍 Manzil", "callback_data": "location"}]
                ]}
                first_name = msg.get("from", {}).get("first_name", "")
                greeting = f"Assalomu alaykum, {first_name}! 👋\n\n" if first_name else "Assalomu alaykum! 👋\n\n"
                await send_message(chat_id,
                    "🌸 *BLOOM FAST FOOD* 🌸\n"
                    "━━━━━━━━━━━━━━━\n\n"
                    + greeting +
                    "🍕 Pizza  •  🍔 Burger  •  🌯 Lavash\n"
                    "🍗 Chicken  •  🎁 Setlar  •  🍰 Dessert\n\n"
                    "✨ _Tez va mazali taomlar eshigingizgacha!_\n\n"
                    "🚚 Yetkazib berish: *50,000 so'm dan bepul*\n"
                    "🕐 Ish vaqti: *08:40 — 22:40*\n\n"
                    "👇 *Buyurtma berish uchun menyuni oching*", kb)
            elif text == "/help":
                await send_message(chat_id,
                    "🙋 *Yordam*\n\n📞 +998 78 555 08 08\n"
                    "✈️ @bloom\\_support\n🕐 08:40 — 22:40")

    elif "callback_query" in data:
        cb = data["callback_query"]
        cb_id = cb["id"]
        cb_data = cb.get("data", "")
        chat_id = str(cb["message"]["chat"]["id"])
        msg_id = cb["message"]["message_id"]
        is_admin = chat_id in ADMIN_IDS

        if is_admin:
            if cb_data == "stats":
                await answer_callback(cb_id)
                await send_message(chat_id, format_stats())
            elif cb_data == "orders_list":
                await answer_callback(cb_id)
                await send_message(chat_id, format_order_list())
            elif cb_data == "toggle_open":
                is_open = not is_open; save_db()
                await answer_callback(cb_id, "🟢 Ochildi!" if is_open else "🔴 Yopildi!")
                await edit_markup(chat_id, msg_id, {"inline_keyboard": [
                    [{"text": "📊 Statistika", "callback_data": "stats"},
                     {"text": "📋 Zakaslar", "callback_data": "orders_list"}],
                    [{"text": "🟢 Ochish" if not is_open else "🔴 Yopish", "callback_data": "toggle_open"}],
                    [{"text": "🍕 Do'konni ochish", "url": "https://t.me/bloomuz_bot/fastfood"}],
                ]})
            elif cb_data.startswith("accept_"):
                _, uid, oid = cb_data.split("_", 2)
                await answer_callback(cb_id, "✅ Qabul qilindi!")
                if oid in orders_db: orders_db[oid]["status"] = "prep"; save_db()
                await edit_markup(chat_id, msg_id, {"inline_keyboard": [
                    [{"text": "✅ Qabul qilindi", "callback_data": "done"}],
                    [{"text": "🚚 Yo'lda", "callback_data": f"way_{uid}_{oid}"},
                     {"text": "📞 Qo'ng'iroq", "callback_data": f"call_{uid}_{oid}"}],
                    [{"text": "⏱️ Kechikamiz", "callback_data": f"late_{uid}_{oid}"}],
                ]})
                if uid != "0":
                    try:
                        await send_message(int(uid),
                            f"✅ *Buyurtmangiz qabul qilindi!*\n\n🆔 #{oid}\n"
                            f"👨‍🍳 Tayyorlanmoqda...\n\n📞 +998 78 555 08 08")
                    except: pass
            elif cb_data.startswith("way_"):
                _, uid, oid = cb_data.split("_", 2)
                await answer_callback(cb_id, "🚚 Yo'lda!")
                if oid in orders_db: orders_db[oid]["status"] = "way"; save_db()
                await edit_markup(chat_id, msg_id, {"inline_keyboard": [
                    [{"text": "🚚 Yo'lda", "callback_data": "done"}],
                    [{"text": "🎉 Yetkazildi", "callback_data": f"delivered_{uid}_{oid}"},
                     {"text": "📞 Qo'ng'iroq", "callback_data": f"call_{uid}_{oid}"}],
                ]})
                if uid != "0":
                    try:
                        await send_message(int(uid),
                            f"🚚 *Buyurtmangiz yo'lda!*\n\n🆔 #{oid}\n⏰ Tez orada yetkazib beramiz!")
                    except: pass
            elif cb_data.startswith("delivered_"):
                _, uid, oid = cb_data.split("_", 2)
                await answer_callback(cb_id, "🎉 Yetkazildi!")
                if oid in orders_db: orders_db[oid]["status"] = "done"; save_db()
                await edit_markup(chat_id, msg_id, {"inline_keyboard": [[
                    {"text": "🎉 Yetkazildi!", "callback_data": "done"}
                ]]})
                if uid != "0":
                    try:
                        await send_message(int(uid),
                            f"🎉 *Buyurtmangiz yetkazildi!*\n\n🆔 #{oid}\nRahmat! Yana keling 🌸")
                    except: pass
            elif cb_data.startswith("reject_"):
                _, uid, oid = cb_data.split("_", 2)
                await answer_callback(cb_id, "❌ Bekor qilindi!")
                if oid in orders_db: orders_db[oid]["status"] = "rejected"; save_db()
                await edit_markup(chat_id, msg_id, {"inline_keyboard": [[
                    {"text": "❌ Bekor qilindi", "callback_data": "done"}
                ]]})
                if uid != "0":
                    try:
                        await send_message(int(uid),
                            f"😔 *Kechirasiz, buyurtmani qabul qilib bo'lmaydi.*\n\n🆔 #{oid}\n📞 +998 78 555 08 08")
                    except: pass
            elif cb_data.startswith("call_"):
                _, uid, oid = cb_data.split("_", 2)
                await answer_callback(cb_id)
                phone = orders_db.get(oid, {}).get("phone", "—")
                await send_message(chat_id, f"📞 *#{oid} telefoni:*\n\n`{phone}`")
            elif cb_data.startswith("late_"):
                _, uid, oid = cb_data.split("_", 2)
                await answer_callback(cb_id, "⏱️ Xabar yuborildi!")
                if uid != "0":
                    try:
                        await send_message(int(uid),
                            f"⏱️ *Kechikish bo'lmoqda!*\n\n🆔 #{oid}\nTez orada yetkaziladi.\n📞 +998 78 555 08 08")
                    except: pass
            elif cb_data.startswith("map_"):
                _, uid, oid = cb_data.split("_", 2)
                await answer_callback(cb_id)
                addr = orders_db.get(oid, {}).get("addr", "")
                q = addr.replace(' ', '+')
                await send_message(chat_id,
                    f"🗺️ *#{oid} manzil:*\n\n📍 {addr}\n\n[Google Maps]( https://maps.google.com/?q={q})")
            elif cb_data == "done":
                await answer_callback(cb_id)
        else:
            if cb_data == "help":
                await answer_callback(cb_id)
                await send_message(chat_id,
                    "📞 *BOG'LANISH*\n"
                    "━━━━━━━━━━━━━━━\n\n"
                    "📱 Telefon: +998 50 211 18 06\n"
                    "✈️ Telegram: @samik\\_1806\n"
                    "📸 Instagram: @samik\\_dev\n\n"
                    "🕐 Ish vaqti: 08:40 — 22:40")
            elif cb_data == "location":
                await answer_callback(cb_id)
                await send_message(chat_id,
                    "📍 *BIZNING FILIALLAR*\n"
                    "━━━━━━━━━━━━━━━\n\n"
                    "🏪 *Bloom Bozor*\n"
                    "Angren shahri, Bozor yaqini\n"
                    "[🗺️ Xaritada]( https://maps.google.com/?q=41.018495,70.084128)\n\n"
                    "🏪 *Bloom Kalso*\n"
                    "Angren shahri, Kalso\n"
                    "[🗺️ Xaritada]( https://maps.google.com/?q=41.013078,70.087399)")
            elif cb_data.startswith("cancel_"):
                # Mijoz o'z zakazini bekor qiladi
                _, uid, oid = cb_data.split("_", 2)
                await answer_callback(cb_id, "Zakaz bekor qilindi")
                if oid in orders_db and orders_db[oid]["status"] == "new":
                    orders_db[oid]["status"] = "rejected"; save_db()
                    await send_message(chat_id, f"❌ *#{oid} bekor qilindi.*")
                    # Adminga xabar
                    await notify_all_admins(f"⚠️ Mijoz #{oid} zakazini bekor qildi.")
                else:
                    await send_message(chat_id, "⚠️ Bu zakazni endi bekor qilib bo'lmaydi (tayyorlanmoqda).")
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
        order_id = str(o.get("id","")).replace("#","")
        uid = str(o.get("chat_id", 0))

        # Do'kon yopiqmi?
        if not is_open:
            return web.json_response({"ok": False, "error": "closed",
                "message": "Do'kon hozir yopiq!"}, headers=cors_headers())

        # Rate limiting
        if uid != "0" and not check_rate_limit(uid):
            return web.json_response({"ok": False, "error": "rate_limit",
                "message": "Juda ko'p zakaz! Biroz kuting."}, headers=cors_headers())

        # Minimal zakaz
        total = o.get("total", 0)
        if total < MIN_ORDER:
            return web.json_response({"ok": False, "error": "min_order",
                "message": f"Minimal zakaz {MIN_ORDER:,} so'm!"}, headers=cors_headers())

        # XSS himoya
        name = escape_html(o.get("name", ""))[:50]
        phone = escape_html(o.get("phone", ""))[:20]
        addr = escape_html(o.get("addr", ""))[:100]

        # Takroriy zakaz oldini olish
        if order_id in orders_db:
            return web.json_response({"ok": True, "duplicate": True}, headers=cors_headers())

        orders_db[order_id] = {
            "status": "new", "user_id": uid, "total": total,
            "name": name, "phone": phone, "addr": addr,
            "date": datetime.now().strftime("%d.%m.%Y %H:%M"),
        }

        today = datetime.now().strftime("%Y-%m-%d")
        if today not in daily_stats:
            daily_stats[today] = {"count": 0, "total": 0}
        daily_stats[today]["count"] += 1
        daily_stats[today]["total"] += total
        save_db()

        items = "\n".join([
            f"  {i.get('emoji','')} {escape_html(i.get('nom',''))} x{i.get('n',1)} = {i.get('narx',0)*i.get('n',1):,} so'm"
            for i in o.get("items", [])
        ])
        text = (
            f"🌸 *YANGI ZAKAZ!*\n\n"
            f"🆔 {o.get('id','')}\n"
            f"👤 {name}\n📞 {phone}\n📍 {addr}\n"
            f"{o.get('type','')} | 🕐 {o.get('slot','')}\n"
            f"{o.get('pay','')}\n\n"
            f"🛒 *Mahsulotlar:*\n{items}\n\n"
            f"💰 *Jami: {total:,} so'm*"
        )
        await notify_all_admins(text, admin_kb(order_id, uid))
        return web.json_response({"ok": True}, headers=cors_headers())
    except Exception as e:
        logger.error(f"Xato: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=500, headers=cors_headers())

async def status_webhook(request):
    if request.method == "OPTIONS":
        return web.Response(status=200, headers=cors_headers())
    try:
        data = await request.json()
        result = {}
        for oid in data.get("ids", []):
            clean = str(oid).replace("#", "")
            if clean in orders_db:
                result[oid] = orders_db[clean]["status"]
        return web.json_response({"ok": True, "statuses": result, "is_open": is_open}, headers=cors_headers())
    except Exception as e:
        return web.json_response({"ok": False}, status=500, headers=cors_headers())

async def settings_webhook(request):
    """Frontend uchun sozlamalar (do'kon ochiq/yopiq, narxlar)"""
    if request.method == "OPTIONS":
        return web.Response(status=200, headers=cors_headers())
    return web.json_response({
        "ok": True,
        "is_open": is_open,
        "free_delivery_min": FREE_DELIVERY_MIN,
        "delivery_fee": DELIVERY_FEE,
        "min_order": MIN_ORDER,
    }, headers=cors_headers())

async def health(request):
    return web.Response(text="Bloom Bot ishlayapti! 🌸", headers=cors_headers())

async def setup_webhook(app):
    load_db()  # DB yuklash
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    if render_url:
        async with aiohttp.ClientSession() as s:
            r = await s.post(f"{TG_API}/setWebhook", json={"url": f"{render_url}/tg"})
            logger.info(f"Webhook: {render_url}/tg — {await r.text()}")

# Server uxlamasligi uchun self-ping
async def keep_alive():
    render_url = os.environ.get("RENDER_EXTERNAL_URL", "")
    if not render_url:
        return
    while True:
        await asyncio.sleep(600)  # 10 daqiqada bir
        try:
            async with aiohttp.ClientSession() as s:
                await s.get(f"{render_url}/")
                logger.info("Keep-alive ping")
        except: pass

async def start_keepalive(app):
    asyncio.create_task(keep_alive())

app = web.Application()
app.router.add_get("/", health)
app.router.add_post("/tg", telegram_webhook)
app.router.add_post("/webhook", order_webhook)
app.router.add_post("/status", status_webhook)
app.router.add_post("/settings", settings_webhook)
app.router.add_route("OPTIONS", "/webhook", order_webhook)
app.router.add_route("OPTIONS", "/status", status_webhook)
app.router.add_route("OPTIONS", "/settings", settings_webhook)
app.on_startup.append(setup_webhook)
app.on_startup.append(start_keepalive)

if __name__ == "__main__":
    web.run_app(app, host="0.0.0.0", port=PORT)
