#!/usr/bin/env python3
import os
from telegram import Update, Message
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)
from db import SessionLocal, get_player, get_jackpot, get_chat, load_event_chats
from models import PlayerModel
from events import EventManager
from items import get_item, ITEMS

TOKEN: str = os.getenv("BOT_TOKEN")
SPIN_COST: int = int(os.getenv("SPIN_COST", "2"))
JACKPOT_INCREMENT: int = int(os.getenv("JACKPOT_INCREMENT", "1"))
JACKPOT_START: int = int(os.getenv("JACKPOT_START", "0"))
START_BALANCE: int = int(os.getenv("START_BALANCE", "100"))
MAP = [1, 2, 3, 0]


def _decode(val: int) -> list[int]:  # ---------------- инвентарь ----------------
    v = val - 1
    return [MAP[v & 3], MAP[(v >> 2) & 3], MAP[(v >> 4) & 3]]


def _calc_prize(
    val: int, symbols: list[int], sevens: int, jackpot_val: int
) -> tuple[int, int]:
    if val == 64:
        return 10 + jackpot_val, JACKPOT_START
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


def _is_chat_registered_for_events(
    chat_id: int, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    return chat_id in context.application.bot_data.get("chats", set())


async def _safe_delete(bot, chat_id: int, msg_id: int):
    from telegram.error import TelegramError

    try:
        await bot.delete_message(chat_id, msg_id)
    except TelegramError:
        pass


async def _reject_spin(
    context: ContextTypes.DEFAULT_TYPE,
    chat_id: int,
    dice_msg: Message,
    text: str,
):
    await _safe_delete(context.bot, chat_id, dice_msg.message_id)

    prev_err_id = context.user_data.pop("err_msg_id", None)
    if prev_err_id:
        await _safe_delete(context.bot, chat_id, prev_err_id)

    err = await context.bot.send_message(chat_id, text)
    context.user_data["err_msg_id"] = err.message_id


async def casino_spin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    dice_msg = update.message

    mgr: EventManager = context.application.bot_data["mgr"]
    if mgr.is_active_participant(chat_id, user.id):
        await _reject_spin(
            context,
            chat_id,
            dice_msg,
            "🚧 Ты участвуешь в ивенте — дождись окончания.",
        )
        return

    with SessionLocal() as session:
        player = get_player(session, user.id, user.first_name, START_BALANCE)
        jackpot_obj = get_jackpot(session, chat_id)

        if player.balance < SPIN_COST:
            await _insufficient_funds(context, chat_id, dice_msg, player)
            return

        player.balance -= SPIN_COST
        jackpot_obj.jackpot += JACKPOT_INCREMENT
        jackpot_before = jackpot_obj.jackpot

        val = dice_msg.dice.value
        symbols = _decode(val)
        prize, jackpot_obj.jackpot = _calc_prize(
            val, symbols, symbols.count(0), jackpot_obj.jackpot
        )

        player.balance += prize
        profit, balance = prize - SPIN_COST, player.balance
        session.commit()

    current_jackpot = jackpot_obj.jackpot
    jackpot_won = current_jackpot < jackpot_before

    await _delete_prev(context, chat_id)
    context.user_data["last_slot_id"] = dice_msg.message_id

    err_id = context.user_data.pop("err_msg_id", None)
    if err_id:
        await _safe_delete(context.bot, chat_id, err_id)

    trend_emoji = "🤑" if profit > 0 else "💀" if profit < 0 else "😑"

    msg_text = (
        f"🏦: {balance:,} | {trend_emoji} {profit:+,} | " f"🎰 {current_jackpot:,}"
    )
    bot_msg = await dice_msg.reply_text(msg_text)
    context.user_data["last_bot_id"] = bot_msg.message_id

    if jackpot_won and jackpot_before:
        announce = (
            f"🎉 {user.first_name} сорвал джекпот — " f"{jackpot_before:,} монет! 🎉"
        )
        await context.bot.send_message(chat_id, announce)


async def join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_chat_registered_for_events(update.effective_chat.id, context):
        await update.message.reply_text("Чат не участвует в ивентах.")
        return
    ev_id = context.args[0].lower() if context.args else None
    ok, msg = context.application.bot_data["mgr"].join(
        update.effective_chat.id,
        update.effective_user.id,
        ev_id,
        update.effective_user.first_name,
    )
    await update.message.reply_text(msg)


async def event_info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_chat_registered_for_events(update.effective_chat.id, context):
        await update.message.reply_text("Чат не участвует в ивентах.")
        return
    await update.message.reply_text(context.application.bot_data["mgr"].info())


async def jackpot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with SessionLocal() as session:
        jp = get_jackpot(session, update.effective_chat.id).jackpot
    await update.message.reply_text(f"🎯 Текущий джек-пот: {jp} очков")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    with SessionLocal() as session:
        player = get_player(session, user.id, user.first_name, START_BALANCE)

        rank = (
            session.query(PlayerModel)
            .filter(PlayerModel.balance > player.balance)
            .count()
            + 1
        )

        inv = player.items or {}
        if inv:
            inv_lines = []
            for id_str, qty in inv.items():
                item_obj = ITEMS.get(int(id_str))
                name = item_obj.name if item_obj else f"ID {id_str}"
                inv_lines.append(f"• (ID:{id_str}) {name} × {qty}")
            inv_block = "🎒 Инвентарь:\n" + "\n".join(inv_lines)
        else:
            inv_block = "🎒 Инвентарь пуст"

    msg = (
        f"👽 {player.first_name} (id:{player.id})\n"
        f"🏦 Баланс: {player.balance:,}\n"
        f"📊 Место в топе: {rank}\n\n"
        f"{inv_block}"
    )
    await update.message.reply_text(msg)


async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with SessionLocal() as session:
        top = (
            session.query(PlayerModel)
            .order_by(PlayerModel.balance.desc())
            .limit(10)
            .all()
        )

    if not top:
        await update.message.reply_text("Пока нет ни одного игрока.")
        return

    lines = ["🏆 ТОП-10 игроков:"]
    for i, p in enumerate(top, 1):
        lines.append(f"{i}. {p.first_name} (id:{p.id}) — {p.balance:,}")
    await update.message.reply_text("\n".join(lines))


async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /buy <id> [кол-во]")
        return

    try:
        item_id = int(context.args[0])
        qty = int(context.args[1]) if len(context.args) > 1 else 1
    except ValueError:
        await update.message.reply_text("id и количество должны быть числами")
        return

    item = get_item(item_id)
    if not item:
        await update.message.reply_text("Неизвестный товар")
        return

    user = update.effective_user
    with SessionLocal() as s:
        player = get_player(s, user.id, user.first_name, START_BALANCE)
        cost = item.price * qty
        if player.balance < cost:
            await update.message.reply_text("Недостаточно монет, дружок")
            return
        try:
            item.buy(player, qty)
        except ValueError as e:
            await update.message.reply_text(str(e))
            return

        player.balance -= cost
        s.commit()

    await update.message.reply_text(f"🛒 Куплено: {item.name} ×{qty} за {cost} монет")


async def use_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Использование: /use <id> [кол-во]")
        return

    try:
        item_id = int(context.args[0])
        qty = int(context.args[1]) if len(context.args) > 1 else 1
    except ValueError:
        await update.message.reply_text("id и количество должны быть числами")
        return

    item = get_item(item_id)
    if not item:
        await update.message.reply_text("Неизвестный предмет")
        return

    user = update.effective_user
    with SessionLocal() as s:
        player = get_player(s, user.id, user.first_name, START_BALANCE)

        have = (player.items or {}).get(str(item.id), 0)
        if have < qty:
            await update.message.reply_text("У тебя нет такого количества, друг")
            return

        try:
            msg = item.use(player, qty)
        except ValueError as e:
            await update.message.reply_text(str(e))
            return

        s.commit()

    await update.message.reply_text(msg)


async def shop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["🛍 Доступные товарчики:"]
    for item_id in sorted(ITEMS):
        it = ITEMS[item_id]
        lines.append(f"ID:{item_id}. {it.name} — {it.price} монет\n" f"📜 {it.desc}")
    await update.message.reply_text("\n".join(lines))


async def register_chat_for_events_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    chat_id = update.effective_chat.id
    if _is_chat_registered_for_events(update.effective_chat.id, context):
        await update.message.reply_text(f"Чат уже зарегистрирован для ивентов")
        return

    with SessionLocal() as session:
        chat_model = get_chat(session, chat_id)
        chat_model.events = True
        context.application.bot_data.setdefault("chats", set()).add(chat_id)
        session.commit()
        await update.message.reply_text(f"Чат теперь участвует в ивентах")


async def after_init(app):
    app.bot_data["chats"] = load_event_chats()
    app.bot_data["mgr"] = EventManager(app)


def main() -> None:
    app = ApplicationBuilder().token(TOKEN).post_init(after_init).build()

    slot_filter = filters.Dice.SLOT_MACHINE & ~filters.FORWARDED
    app.add_handler(MessageHandler(slot_filter, casino_spin))
    app.add_handler(CommandHandler("join", join_cmd))
    app.add_handler(CommandHandler(["event", "events"], event_info_cmd))
    app.add_handler(CommandHandler(["jackpot", "ochko"], jackpot_cmd))
    app.add_handler(
        CommandHandler("register_chat_for_events", register_chat_for_events_cmd)
    )
    app.add_handler(CommandHandler("status", status_cmd))
    app.add_handler(CommandHandler("top", top_cmd))
    app.add_handler(CommandHandler("buy", buy_cmd))
    app.add_handler(CommandHandler("use", use_cmd))
    app.add_handler(CommandHandler("shop", shop_cmd))

    app.run_polling()


if __name__ == "__main__":
    main()
