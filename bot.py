import os
import logging
import asyncio
from aiohttp import web
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
ADMIN_ID  = int(os.environ.get("ADMIN_ID", "0"))
PORT      = int(os.environ.get("PORT", "8080"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app_bot = None

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛒 Do'konni ochish", url="https://samandar18uzzzzzz.github.io/bloom-v2")],
        [InlineKeyboardButton("🙋 Yordam", callback_data="help")],
    ])
    await update.message.reply_text(
        "🌸 *Bloom Do'koniga xush kelibsiz!*\n\n"
        "Toza va yangi mahsulotlar eshigingizgacha! 🚀\n\n"
        "Buyurtma berish uchun do'konni oching 👇",
        parse_mode="Markdown",
        reply_markup=keyboard
    )

async def help_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    await update.callback_query.message.reply_text(
        "🙋 *Yordam*\n\n"
        "📞 Tel: +998 50 211 18 06\n"
        "✈️ Telegram: @bloom\\_support\n"
        "🕐 Ish vaqti: 08:00 — 22:00",
        parse_mode="Markdown"
    )

async def order_cb(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    parts = query.data.split("_")
    action, chat_id, order_id = parts[0], int(parts[1]), parts[2]

    if action == "accept":
        await query.edit_message_reply_markup(
            InlineKeyboardMarkup([[InlineKeyboardButton("✅ Qabul qilindi", callback_data="done")]]))
        if chat_id:
            try:
                await context.bot.send_message(chat_id,
                    f"✅ *Buyurtmangiz qabul qilindi!*\n🆔 #{order_id}\n🚚 Tez orada yetkazamiz!",
                    parse_mode="Markdown")
            except: pass

    elif action == "reject":
        await query.edit_message_reply_markup(
            InlineKeyboardMarkup([[InlineKeyboardButton("❌ Bekor qilindi", callback_data="done")]]))
        if chat_id:
            try:
                await context.bot.send_message(chat_id,
                    f"😔 *Kechirasiz, hozircha buyurtma qabul qilib bo'lmaydi.*\n🆔 #{order_id}\n📞 +998 71 200 00 00",
                    parse_mode="Markdown")
            except: pass

async def webhook(request):
    try:
        data = await request.json()
        o = data.get("order", {})
        items = "\n".join([f"  {i.get('emoji','')} {i.get('nom','')} x{i.get('n',1)} = {i.get('narx',0)*i.get('n',1):,} som" for i in o.get("items",[])])
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
        cid = o.get("id","").replace("#","")
        uid = o.get("chat_id", 0)
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Qabul", callback_data=f"accept_{uid}_{cid}"),
            InlineKeyboardButton("❌ Bekor", callback_data=f"reject_{uid}_{cid}"),
        ]])
        await app_bot.bot.send_message(ADMIN_ID, text, parse_mode="Markdown", reply_markup=kb)
        return web.json_response({"ok": True})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)

async def health(request):
    return web.Response(text="Bloom Bot ishlayapti! 🌸")

async def main():

    global app_bot

    app_bot = Application.builder().token(BOT_TOKEN).build()

    app_bot.add_handler(CommandHandler("start", start))

    app_bot.add_handler(CallbackQueryHandler(help_cb, pattern="^help$"))

    app_bot.add_handler(

        CallbackQueryHandler(order_cb, pattern="^(accept|reject)_")

    )

    await app_bot.initialize()

    await app_bot.start()

    await app_bot.updater.start_polling()

    web_app = web.Application()

    web_app.router.add_get("/", health)

    web_app.router.add_post("/webhook", webhook)

    runner = web.AppRunner(web_app)

    await runner.setup()

    await web.TCPSite(runner, "0.0.0.0", PORT).start()

    logger.info(f"Ishga tushdi! Port: {PORT}")

    await asyncio.Event().wait()

if __name__ == "__main__":

    asyncio.run(main())
