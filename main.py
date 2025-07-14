import asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    filters,
)
from db import SessionLocal, get_player, get_room, load_event_chats
from models import PlayerModel
from games.rps import RPSGame
from games.bjack import register_handlers as register_bjack_handlers

from config import FREE_MONEY, SPIN_COST, TOKEN

MAP = [1, 2, 3, 0]


def _decode(val: int) -> list[int]:
    v = val - 1
    return [MAP[v & 3], MAP[(v >> 2) & 3], MAP[(v >> 4) & 3]]


def _calc_prize(val: int, symbols: list[int], sevens: int) -> tuple[bool, int]:
    if val == 64:
        return True, 15
    if len(set(symbols)) == 1:
        return False, 10
    if sevens == 2:
        return False, 8
    return False, 0


async def safe_reply(msg_obj, text: str, **kwargs):
    from telegram.error import TimedOut

    for attempt in range(3):
        try:
            return await msg_obj.reply_text(text, **kwargs)
        except TimedOut:
            if attempt < 2:
                await asyncio.sleep(1)
                continue
            raise


async def _reply_clean(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    is_slot: bool = False,
    **kwargs,
):
    chat_id = update.effective_chat.id
    store = context.user_data

    for key in ("last_bot_id", "last_user_id", "last_slot_id"):
        mid = store.pop(key, None)
        if mid:
            try:
                await context.bot.delete_message(chat_id, mid)
            except Exception:
                pass

    msg_obj = update.effective_message
    if not msg_obj:
        return

    bot_msg = await safe_reply(msg_obj, text, **kwargs)

    if is_slot:
        store["last_slot_id"] = msg_obj.message_id
    store["last_bot_id"] = bot_msg.message_id
    store["last_user_id"] = msg_obj.message_id

    return bot_msg


def _is_chat_registered_for_events(
    chat_id: int, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    return chat_id in context.application.bot_data.get("chats", set())


async def casino_spin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    dice_msg = update.effective_message

    with SessionLocal() as db:
        player = get_player(db, user.id, chat_id, user.first_name)
        room = get_room(db, chat_id)

        if player.balance < SPIN_COST:
            await _reply_clean(
                update, context, f"❌ {player.first_name}, недостаточно очков. Отдохни!"
            )
            return

        player.balance -= SPIN_COST
        val = dice_msg.dice.value
        symbols = _decode(val)
        is_jack, prize = _calc_prize(val, symbols, symbols.count(0))

        player.balance += prize
        profit = prize - SPIN_COST
        balance = player.balance
        db.commit()

    for key in ("last_bot_id", "last_slot_id", "last_user_id"):
        mid = context.user_data.pop(key, None)
        if mid:
            try:
                await context.bot.delete_message(chat_id, mid)
            except Exception:
                pass

    trend = "🤑" if profit > 0 else "💀" if profit < 0 else "😑"
    text = f"🏦: {balance:,} | {trend} {profit:+,}"

    bot_msg = await safe_reply(dice_msg, text)
    context.user_data["last_slot_id"] = dice_msg.message_id
    context.user_data["last_bot_id"] = bot_msg.message_id


# async def join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     if not _is_chat_registered_for_events(update.effective_chat.id, context):
#         await _reply_clean(update, context, "Чат не участвует в ивентах.")
#         return
#     ev_id = context.args[0].lower() if context.args else None
#     ok, msg = context.application.bot_data["mgr"].join(
#         update.effective_chat.id,
#         update.effective_user.id,
#         ev_id,
#         update.effective_user.first_name,
#     )
#     await _reply_clean(update, context, msg)


# async def event_info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     if not _is_chat_registered_for_events(update.effective_chat.id, context):
#         await _reply_clean(update, context, "Чат не участвует в ивентах.")
#         return
#     info = context.application.bot_data["mgr"].info()
#     await _reply_clean(update, context, info)


# async def jackpot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     with SessionLocal() as session:
#         jp = get_jackpot(session, update.effective_chat.id)
#     await _reply_clean(update, context, f"🎯 Текущий джек-пот: {jp} очков")


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    with SessionLocal() as session:
        player = get_player(session, user.id, chat_id, user.first_name)
        higher_count = (
            session.query(PlayerModel)
            .filter(
                PlayerModel.room_id == chat_id, PlayerModel.balance > player.balance
            )
            .count()
        )
        rank = higher_count + 1
    msg = (
        f"👽 {player.first_name} (id:{player.id})\n"
        f"🏦 Баланс: {player.balance:,}\n"
        f"📊 Место в топе: {rank}\n\n"
    )
    await _reply_clean(update, context, msg)


async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    with SessionLocal() as session:
        top = (
            session.query(PlayerModel)
            .filter(PlayerModel.room_id == chat_id)
            .order_by(PlayerModel.balance.desc())
            .limit(10)
            .all()
        )
    if not top:
        await _reply_clean(update, context, "Пока нет ни одного игрока.")
        return
    lines = ["🏆 ТОП-10 игроков:"] + [
        f"{i+1}. {p.first_name} (id:{p.id}) — {p.balance:,}" for i, p in enumerate(top)
    ]
    await _reply_clean(update, context, "\n".join(lines))


# async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     if not context.args:
#         await _reply_clean(update, context, "Использование: /buy <id> [кол-во]")
#         return
#     try:
#         item_id = int(context.args[0])
#         qty = int(context.args[1]) if len(context.args) > 1 else 1
#     except ValueError:
#         await _reply_clean(update, context, "id и количество должны быть числами")
#         return
#     item = get_item(item_id)
#     if not item:
#         await _reply_clean(update, context, "Неизвестный товар")
#         return
#     user = update.effective_user
#     chat_id = update.effective_chat.id
#     with SessionLocal() as s:
#         player = get_player(s, user.id, chat_id, user.first_name)
#         cost = item.price * qty
#         if player.balance < cost:
#             await _reply_clean(update, context, "Недостаточно монет, дружок")
#             return
#         try:
#             item.buy(player, qty)
#         except ValueError as e:
#             await _reply_clean(update, context, str(e))
#             return
#         player.balance -= cost
#         s.commit()
#     await _reply_clean(
#         update, context, f"🛒 Куплено: {item.name} ×{qty} за {cost} монет"
#     )


# async def use_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     if not context.args:
#         await _reply_clean(update, context, "Использование: /use <id> [кол-во]")
#         return
#     try:
#         item_id = int(context.args[0])
#         qty = int(context.args[1]) if len(context.args) > 1 else 1
#     except ValueError:
#         await _reply_clean(update, context, "id и количество должны быть числами")
#         return
#     item = get_item(item_id)
#     if not item:
#         await _reply_clean(update, context, "Неизвестный предмет")
#         return
#     user = update.effective_user
#     chat_id = update.effective_chat.id
#     with SessionLocal() as s:
#         player = get_player(s, user.id, chat_id, user.first_name)
#         have = (player.items or {}).get(str(item.id), 0)
#         if have < qty:
#             await _reply_clean(update, context, "У тебя нет такого количества, друг")
#             return
#         try:
#             msg = item.use(player, qty)
#         except ValueError as e:
#             await _reply_clean(update, context, str(e))
#             return
#         s.commit()
#     await _reply_clean(update, context, msg)


# async def shop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
#     lines = ["🛍 Доступные товарчики:"]
#     for item_id in sorted(ITEMS):
#         it = ITEMS[item_id]
#         lines.append(f"ID:{item_id}. {it.name} — {it.price} монет\n📜 {it.desc}")
#     await _reply_clean(update, context, "\n".join(lines))


async def microzaim_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    with SessionLocal() as session:
        money = FREE_MONEY
        player = get_player(session, user.id, chat_id, user.first_name)
        if player.balance > SPIN_COST:
            await _reply_clean(
                update, context, "💰 У тебя еще есть деньги, друг, одумайся"
            )
            return
        player.balance = money
        session.commit()
    await _reply_clean(
        update, context, f"✅ {user.first_name}, тебе выдан микрозайм на {money} монет!"
    )


async def register_chat_for_events_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    chat_id = update.effective_chat.id
    if _is_chat_registered_for_events(chat_id, context):
        await _reply_clean(update, context, "Этот чат уже зарегистрирован для ивентов.")
        return
    with SessionLocal() as session:
        chat_model = get_room(session, chat_id)
        chat_model.events = True
        context.application.bot_data.setdefault("chats", set()).add(chat_id)
        session.commit()
    await _reply_clean(
        update, context, "Чат успешно зарегистрирован для участия в ивентах."
    )


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 <b>Доступные команды</b>\n"
        "\n"
        "🎰 <b>Слот-машина</b> — просто пришлите в чат.\n"
        "\n"
        "👤  /status /st - ваш баланс, место\n"
        "🏆  /top /t - топ-10 игроков по балансу\n"
        "💳  /microzaim /mz - взять микрозайм (если нет денег)\n"
        "\n"
        "✊  /rps - начать игру Камень–Ножницы–Бумага с ставкой\n"
        "🃏  /blackjack /bj - начать игру в блэкджек\n"
    )
    await update.effective_message.reply_text(help_text, parse_mode="HTML")


async def after_init(app):
    app.bot_data["games"] = {}
    app.bot_data["chats"] = load_event_chats()
    # app.bot_data["mgr"] = EventManager(app)


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    import logging

    logging.exception("Ошибка в обработчике")

    msg = getattr(update, "effective_message", None)
    if msg:
        try:
            await msg.reply_text("Произошла ошибка, попробуйте позже.")
        except Exception:
            pass


def main() -> None:
    app = ApplicationBuilder().token(TOKEN).post_init(after_init).build()
    app.add_error_handler(error_handler)

    slot_filter = filters.Dice.SLOT_MACHINE & ~filters.FORWARDED
    app.add_handler(MessageHandler(slot_filter, casino_spin))

    app.add_handler(CommandHandler(["status", "st"], status_cmd))
    app.add_handler(CommandHandler(["top", "t"], top_cmd))
    app.add_handler(CommandHandler(["help", "h"], help_cmd))
    app.add_handler(CommandHandler(["microzaim", "mz"], microzaim_cmd))

    app.add_handler(
        CommandHandler(
            [
                "stone",
                "paper",
                "scissors",
                "rps",
                "rsp",
                "srp",
                "spr",
                "psr",
                "prs",
                "ppc",
            ],
            RPSGame.start_game,
        )
    )
    app.add_handler(CallbackQueryHandler(RPSGame.handle_callback, pattern=r"^rps_"))

    register_bjack_handlers(app)

    app.run_polling()


if __name__ == "__main__":
    main()
