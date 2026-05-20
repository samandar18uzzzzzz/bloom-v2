import os
import json
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
from aiohttp import web

# ─── SOZLAMALAR ───────────────────────────────────────────
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID  = int(os.environ.get("ADMIN_ID", "0"))
PORT      = int(os.environ.get("PORT", "8080"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── /start BUYRUGI ───────────────────────────────────────
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🌸 *Bloom Do'koniga xush kelibsiz!*\n\n"
        "Bizda eng toza va yangi mahsulotlar mavjud.\n\n"
        "🛒 Buyurtma berish uchun quyidagi tugmani bosing:",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup([
            [InlineKeyboardButton("🛒 Do'konni ochish", url="https://samandar18uzzzzzz.github.io/bloom-v2")],
            [InlineKeyboardButton("🙋 Yordam", callback_data="help")],
        ])
    )

# ─── YORDAM ───────────────────────────────────────────────
async def help_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.message.reply_text(
        "🙋 *Yordam*\n\n"
        "📞 Telefon: +998 71 200 00 00\n"
        "✈️ Telegram: @bloom\\_support\n"
        "🕐 Ish vaqti: 08:00 — 22:00\n\n"
        "Savollaringiz bo'lsa yozing!",
        parse_mode="Markdown"
    )

# ─── ZAKAZ QABUL QILISH / BEKOR QILISH ───────────────────
async def order_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data  # "accept_CHATID_ORDERID" yoki "reject_CHATID_ORDERID"
    parts = data.split("_")
    action   = parts[0]
    chat_id  = int(parts[1])
    order_id = parts[2]

    if action == "accept":
        # Adminga xabar
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("✅ Qabul qilindi", callback_data="done")]
            ])
        )
        # Klientga xabar
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"✅ *Buyurtmangiz qabul qilindi!*\n\n"
                     f"🆔 Zakaz: #{order_id}\n"
                     f"🚚 Tez orada yetkazib beramiz!\n\n"
                     f"📞 Savollar uchun: +998 71 200 00 00",
                parse_mode="Markdown"
            )
        except:
            pass

    elif action == "reject":
        # Adminga xabar
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup([
                [InlineKeyboardButton("❌ Bekor qilindi", callback_data="done")]
            ])
        )
        # Klientga xabar
        try:
            await context.bot.send_message(
                chat_id=chat_id,
                text=f"😔 *Kechirasiz, hozircha buyurtmangizni qabul qilib bo'lmaydi.*\n\n"
                     f"🆔 Zakaz: #{order_id}\n"
                     f"📞 Batafsil: +998 71 200 00 00",
                parse_mode="Markdown"
            )
        except:
            pass

# ─── WEBHOOK — MINI APP DAN ZAKAZ KELADI ─────────────────
async def webhook_handler(request):
    try:
        data = await request.json()
        order = data.get("order", {})

        order_id  = order.get("id", "—")
        name      = order.get("name", "—")
        phone     = order.get("phone", "—")
        addr      = order.get("addr", "—")
        tip       = order.get("type", "—")
        slot      = order.get("slot", "—")
        pay       = order.get("pay", "—")
        total     = order.get("total", 0)
        items     = order.get("items", [])
        chat_id   = order.get("chat_id", 0)

        mahsulotlar = "\n".join([
            f"  {i.get('emoji','')} {i.get('nom','')} × {i.get('n',1)} = {i.get('narx',0)*i.get('n',1):,} so'm"
            for i in items
        ])

        xabar = (
            f"🌸 *YANGI ZAKAZ!*\n\n"
            f"🆔 {order_id}\n"
            f"📅 {order.get('date','')}\n\n"
            f"👤 *{name}*\n"
            f"📞 {phone}\n"
            f"📍 {addr}\n\n"
            f"{tip}\n"
            f"🕐 {slot}\n"
            f"{pay}\n\n"
            f"🛒 *Mahsulotlar:*\n{mahsulotlar}\n\n"
            f"💰 *Jami: {total:,} so'm*"
        )

        clean_id = order_id.replace("#", "")
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("✅ Qabul qilish", callback_data=f"accept_{chat_id}_{clean_id}"),
                InlineKeyboardButton("❌ Bekor qilish", callback_data=f"reject_{chat_id}_{clean_id}"),
            ]
        ])

        app = request.app["bot_app"]
        await app.bot.send_message(
            chat_id=ADMIN_ID,
            text=xabar,
            parse_mode="Markdown",
            reply_markup=keyboard
        )

        return web.json_response({"ok": True})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return web.json_response({"ok": False, "error": str(e)}, status=500)

# ─── HEALTH CHECK ─────────────────────────────────────────
async def health(request):
    return web.Response(text="Bloom Bot ishlayapti! 🌸")

# ─── ASOSIY ───────────────────────────────────────────────
async def main():
    bot_app = Application.builder().token(BOT_TOKEN).build()
    bot_app.add_handler(CommandHandler("start", start))
    bot_app.add_handler(CallbackQueryHandler(help_callback, pattern="^help$"))
    bot_app.add_handler(CallbackQueryHandler(order_action, pattern="^(accept|reject)_"))

    await bot_app.initialize()
    await bot_app.start()

    # Web server
    web_app = web.Application()
    web_app["bot_app"] = bot_app
    web_app.router.add_get("/", health)
    web_app.router.add_post("/webhook", webhook_handler)

    # Polling ishga tushirish
    await bot_app.updater.start_polling()

    runner = web.AppRunner(web_app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", PORT)
    await site.start()

    logger.info(f"Bot va server ishga tushdi! Port: {PORT}")

    # Doim ishlaydi
    import asyncio
    await asyncio.Event().wait()

if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
