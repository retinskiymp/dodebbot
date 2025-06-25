#!/usr/bin/env python3
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)

TOKEN = "7899355394:AAFiSRwuXWGP-fFBWraH_l9Le2FVTTAZzWw"
SPIN_COST = 1
START_BALANCE = 50
MAP = [1, 2, 3, 0]                 # раскодировка барабанов


# ─────────── вспомогательные ───────────
def _decode(val: int) -> list[int]:
    """1…64 → три символа 0‥3 (0 — это 7️⃣)."""
    v = val - 1
    return [MAP[v & 3], MAP[(v >> 2) & 3], MAP[(v >> 4) & 3]]


def get_jackpot(chat_data: dict) -> int:
    """Всегда возвращает актуальный джек-пот (min 10)."""
    if "jackpot" not in chat_data or chat_data["jackpot"] < 10:
        chat_data["jackpot"] = 10
    return chat_data["jackpot"]


# ─────────── /jackpot ───────────
async def jackpot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    jp = get_jackpot(context.chat_data)
    await update.message.reply_text(f"🎯 Текущий джек-пот: {jp} очков")


# ─────────── основной спин ───────────
async def casino_spin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    dice_msg = update.message
    balance = context.user_data.get("balance", START_BALANCE)

    # ── если баланс уже < 0 ──────────────────────────────
    if balance < 0:
        # удаляем прошлый 🎰 и ответ бота
        for key in ("last_slot_id", "last_bot_id"):
            mid = context.user_data.get(key)
            if mid:
                try:
                    await context.bot.delete_message(chat_id, mid)
                except Exception:
                    pass
        # удаляем этот 🎰
        try:
            await context.bot.delete_message(chat_id, dice_msg.message_id)
        except Exception:
            pass

        # отвечаем «нет денег»
        bot_msg = await context.bot.send_message(
            chat_id, f"❌ {update.effective_user.first_name}, недостаточно очков. Отдохни!")
        context.user_data["last_bot_id"] = bot_msg.message_id
        return

    # ── нормальная игра ─────────────────────────────────
    balance -= SPIN_COST                            # ставка
    jackpot = get_jackpot(context.chat_data) + SPIN_COST  # пополняем банк

    # считаем приз
    val = dice_msg.dice.value
    symbols = _decode(val)
    sevens = symbols.count(0)

    if val == 64:                                   # 7️⃣7️⃣7️⃣
        prize = 10 + jackpot
        jackpot = 10                                # сброс банка
    elif len(set(symbols)) == 1:                    # три одинаковых
        prize = 7
    elif sevens == 2:                               # ровно две 7-ки
        prize = 5
    else:
        prize = 0

    balance += prize
    profit = prize - SPIN_COST

    # сохраняем баланс и банк
    context.user_data["balance"] = balance
    context.chat_data["jackpot"] = jackpot

    # удаляем предыдущую пару сообщений
    for key in ("last_slot_id", "last_bot_id"):
        mid = context.user_data.get(key)
        if mid:
            try:
                await context.bot.delete_message(chat_id, mid)
            except Exception:
                pass

    # запоминаем и отвечаем
    context.user_data["last_slot_id"] = dice_msg.message_id
    reply = (f"💸: -{SPIN_COST} | 🤑: {prize} "
             f"| 🏦: {balance} (💹 {profit})")
    bot_msg = await dice_msg.reply_text(reply)
    context.user_data["last_bot_id"] = bot_msg.message_id


# ─────────── запуск ───────────
def main() -> None:
    app = ApplicationBuilder().token(TOKEN).build()

    slot_filter = filters.Dice.SLOT_MACHINE & ~filters.FORWARDED
    app.add_handler(MessageHandler(slot_filter, casino_spin))
    app.add_handler(CommandHandler("jackpot", jackpot_cmd))

    app.run_polling()


if __name__ == "__main__":
    main()
