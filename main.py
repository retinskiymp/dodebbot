#!/usr/bin/env python3
import os
import asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)
from db import SessionLocal, get_player, get_jackpot
from events import EventManager

TOKEN: str = os.getenv("BOT_TOKEN")
SPIN_COST: int = int(os.getenv("SPIN_COST", "2"))
JACKPOT_INCREMENT: int = int(os.getenv("JACKPOT_INCREMENT", "1"))
START_BALANCE: int = int(os.getenv("START_BALANCE", "100"))
MAP = [1, 2, 3, 0]


def _decode(val: int) -> list[int]:
    v = val - 1
    return [MAP[v & 3], MAP[(v >> 2) & 3], MAP[(v >> 4) & 3]]


def _calc_prize(
    val: int, symbols: list[int], sevens: int, jackpot_val: int
) -> tuple[int, int]:
    if val == 64:
        return 10 + jackpot_val, 10
    if len(set(symbols)) == 1:
        return 7, jackpot_val
    if sevens == 2:
        return 5, jackpot_val
    return 0, jackpot_val


async def _delete_prev(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    for key in ("last_slot_id", "last_bot_id"):
        mid = context.user_data.get(key)
        if mid:
            try:
                await context.bot.delete_message(chat_id, mid)
            except Exception:
                pass


async def _insufficient_funds(
    context: ContextTypes.DEFAULT_TYPE, chat_id: int, dice_msg, player
) -> None:
    await _delete_prev(context, chat_id)
    try:
        await context.bot.delete_message(chat_id, dice_msg.message_id)
    except Exception:
        pass
    msg = await context.bot.send_message(
        chat_id, f"❌ {player.first_name}, недостаточно очков. Отдохни!"
    )
    context.user_data["last_bot_id"] = msg.message_id


async def casino_spin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    dice_msg = update.message

    context.application.bot_data.setdefault("chats", set()).add(chat_id)
    mgr: EventManager = context.application.bot_data["mgr"]
    if mgr.is_active_participant(chat_id, user.id):
        await update.message.reply_text("Ты участвуешь в ивенте — подожди окончания.")
        return

    with SessionLocal() as session:
        player = get_player(session, user.id, user.first_name, START_BALANCE)
        jackpot_obj = get_jackpot(session, chat_id)

        if player.balance < SPIN_COST:
            await _insufficient_funds(context, chat_id, dice_msg, player)
            return

        player.balance -= SPIN_COST
        jackpot_obj.value += JACKPOT_INCREMENT

        val = dice_msg.dice.value
        symbols = _decode(val)
        prize, jackpot_obj.value = _calc_prize(
            val, symbols, symbols.count(0), jackpot_obj.value
        )

        player.balance += prize
        profit, balance = prize - SPIN_COST, player.balance
        session.commit()

    await _delete_prev(context, chat_id)
    context.user_data["last_slot_id"] = dice_msg.message_id
    msg = f"💸: -{SPIN_COST} | 🤑: {prize} | 🏦: {balance} (💹 {profit})"
    bot_msg = await dice_msg.reply_text(msg)
    context.user_data["last_bot_id"] = bot_msg.message_id


async def join_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    ev_id = c.args[0].lower() if c.args else None
    ok, msg = c.application.bot_data["mgr"].join(
        u.effective_chat.id, u.effective_user.id, ev_id
    )
    await u.message.reply_text(msg)


async def event_info_cmd(u: Update, c: ContextTypes.DEFAULT_TYPE):
    await u.message.reply_text(c.application.bot_data["mgr"].info(u.effective_chat.id))


async def jackpot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with SessionLocal() as session:
        jp = get_jackpot(session, update.effective_chat.id).value
    await update.message.reply_text(f"🎯 Текущий джек-пот: {jp} очков")


async def after_init(app):
    app.bot_data["mgr"] = EventManager(app)
    app.bot_data["chats"] = set()


def main() -> None:
    app = ApplicationBuilder().token(TOKEN).post_init(after_init).build()

    slot_filter = filters.Dice.SLOT_MACHINE & ~filters.FORWARDED
    app.add_handler(MessageHandler(slot_filter, casino_spin))
    app.add_handler(CommandHandler("join", join_cmd))
    app.add_handler(CommandHandler(["event", "events"], event_info_cmd))
    app.add_handler(CommandHandler(["jackpot", "ochko"], jackpot_cmd))

    app.run_polling()


if __name__ == "__main__":
    main()
