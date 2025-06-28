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


def _calc_prize(val: int, symbols: list[int], sevens: int) -> tuple[bool, int]:
    if val == 64:
        return [True, 15]
    if len(set(symbols)) == 1:
        return [False, 10]
    if sevens == 2:
        return [False, 8]
    return [False, 0]


async def _reply_clean(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
    text: str,
    *,
    is_slot: bool = False,
    **kwargs,
) -> Message:
    chat_id = update.effective_chat.id
    store = context.user_data

    keys = ("last_bot_id", "last_user_id", "last_slot_id")
    for key in keys:
        mid = store.pop(key, None)
        if mid:
            try:
                await context.bot.delete_message(chat_id, mid)
            except Exception:
                pass

    msg = await update.message.reply_text(text, **kwargs)

    if is_slot:
        store["last_slot_id"] = update.message.message_id
    store["last_bot_id"] = msg.message_id
    store["last_user_id"] = update.message.message_id

    return msg


def _is_chat_registered_for_events(
    chat_id: int, context: ContextTypes.DEFAULT_TYPE
) -> bool:
    return chat_id in context.application.bot_data.get("chats", set())


async def casino_spin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    user = update.effective_user
    dice_msg = update.message

    mgr: EventManager = context.application.bot_data["mgr"]
    if mgr.is_active_participant(chat_id, user.id):
        await _reply_clean(
            update, context, "🚧 Ты участвуешь в ивенте — дождись окончания."
        )
        return

    with SessionLocal() as db:
        player = get_player(db, user.id, user.first_name, START_BALANCE)
        jackpot_obj = get_jackpot(db, chat_id, JACKPOT_START)

        if player.balance < SPIN_COST:
            await _reply_clean(
                update, context, f"❌ {player.first_name}, недостаточно очков. Отдохни!"
            )
            return

        player.balance -= SPIN_COST

        val = dice_msg.dice.value
        symbols = _decode(val)
        is_jack, prize = _calc_prize(val, symbols, symbols.count(0))

        if not is_jack:
            jackpot_obj.jackpot += JACKPOT_INCREMENT
        else:
            prize += jackpot_obj.jackpot
            jackpot_before = jackpot_obj.jackpot
            jackpot_obj.jackpot = JACKPOT_START

        player.balance += prize
        profit = prize - SPIN_COST
        balance = player.balance
        db.commit()
        current_jackpot = jackpot_obj.jackpot

    for key in ("last_slot_id", "last_bot_id", "last_user_id"):
        mid = context.user_data.pop(key, None)
        if mid:
            try:
                await context.bot.delete_message(chat_id, mid)
            except Exception:
                pass

    trend = "🤑" if profit > 0 else "💀" if profit < 0 else "😑"
    text = f"🏦: {balance:,} | {trend} {profit:+,} | 🎰 {current_jackpot:,}"

    bot_msg = await dice_msg.reply_text(text)

    context.user_data["last_slot_id"] = dice_msg.message_id
    context.user_data["last_bot_id"] = bot_msg.message_id

    if is_jack and jackpot_before:
        await context.bot.send_message(
            chat_id,
            f"🎉 {user.first_name} сорвал джекпот — {jackpot_before:,} монет! 🎉",
        )


async def join_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_chat_registered_for_events(update.effective_chat.id, context):
        await _reply_clean(update, context, "Чат не участвует в ивентах.")
        return
    ev_id = context.args[0].lower() if context.args else None
    ok, msg = context.application.bot_data["mgr"].join(
        update.effective_chat.id,
        update.effective_user.id,
        ev_id,
        update.effective_user.first_name,
    )
    await _reply_clean(update, context, msg)


async def event_info_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _is_chat_registered_for_events(update.effective_chat.id, context):
        await _reply_clean(update, context, "Чат не участвует в ивентах.")
        return
    await _reply_clean(update, context, context.application.bot_data["mgr"].info())


async def jackpot_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with SessionLocal() as session:
        jp = get_jackpot(session, update.effective_chat.id, JACKPOT_START).jackpot
    await _reply_clean(update, context, f"🎯 Текущий джек-пот: {jp} очков")


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
    await _reply_clean(update, context, msg)


async def top_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    with SessionLocal() as session:
        top = (
            session.query(PlayerModel)
            .order_by(PlayerModel.balance.desc())
            .limit(10)
            .all()
        )

    if not top:
        await _reply_clean(update, context, "Пока нет ни одного игрока.")
        return

    lines = ["🏆 ТОП-10 игроков:"]
    for i, p in enumerate(top, 1):
        lines.append(f"{i}. {p.first_name} (id:{p.id}) — {p.balance:,}")
    await _reply_clean(update, context, "\n".join(lines))


async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await _reply_clean(update, context, "Использование: /buy <id> [кол-во]")
        return

    try:
        item_id = int(context.args[0])
        qty = int(context.args[1]) if len(context.args) > 1 else 1
    except ValueError:
        await _reply_clean(update, context, "id и количество должны быть числами")
        return

    item = get_item(item_id)
    if not item:
        await _reply_clean(update, context, "Неизвестный товар")
        return

    user = update.effective_user
    with SessionLocal() as s:
        player = get_player(s, user.id, user.first_name, START_BALANCE)
        cost = item.price * qty
        if player.balance < cost:
            await _reply_clean(update, context, "Недостаточно монет, дружок")
            return
        try:
            item.buy(player, qty)
        except ValueError as e:
            await _reply_clean(update, context, str(e))
            return

        player.balance -= cost
        s.commit()

    await _reply_clean(
        update, context, f"🛒 Куплено: {item.name} ×{qty} за {cost} монет"
    )


async def use_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await _reply_clean(update, context, "Использование: /use <id> [кол-во]")
        return

    try:
        item_id = int(context.args[0])
        qty = int(context.args[1]) if len(context.args) > 1 else 1
    except ValueError:
        await _reply_clean(update, context, "id и количество должны быть числами")
        return

    item = get_item(item_id)
    if not item:
        await _reply_clean(update, context, "Неизвестный предмет")
        return

    user = update.effective_user
    with SessionLocal() as s:
        player = get_player(s, user.id, user.first_name, START_BALANCE)

        have = (player.items or {}).get(str(item.id), 0)
        if have < qty:
            await _reply_clean(update, context, "У тебя нет такого количества, друг")
            return

        try:
            msg = item.use(player, qty)
        except ValueError as e:
            await _reply_clean(update, context, str(e))
            return

        s.commit()

    await _reply_clean(update, context, msg)


async def shop_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lines = ["🛍 Доступные товарчики:"]
    for item_id in sorted(ITEMS):
        it = ITEMS[item_id]
        lines.append(f"ID:{item_id}. {it.name} — {it.price} монет\n" f"📜 {it.desc}")
    await _reply_clean(update, context, "\n".join(lines))


async def register_chat_for_events_cmd(
    update: Update, context: ContextTypes.DEFAULT_TYPE
):
    chat_id = update.effective_chat.id
    if _is_chat_registered_for_events(update.effective_chat.id, context):
        await _reply_clean(update, context, "Этот чат уже зарегистрирован для ивентов.")
        return

    with SessionLocal() as session:
        chat_model = get_chat(session, chat_id)
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
        "🎰 <b>Слот-машина</b> — просто пришлите кубик-слот в чат.\n"
        "\n"
        "🛎️  /join - присоединиться к текущему ивенту\n"
        "📅  /event(s) - информация о ивентах\n"
        "🎯  /jackpot - размер джек-пота в чате\n"
        "\n"
        "👤  /status - ваш баланс, место и инвентарь\n"
        "🏆  /top - топ-10 игроков по балансу\n"
        "🛍️  /shop - список товаров магазина\n"
        "💰  /buy <i>id</i> [n] - купить товар (по умолчанию 1 шт.)\n"
        "🎒  /use <i>id</i> [n] - использовать товар из инвентаря\n"
        "\n"
        "⚙️  /register_chat_for_events - подключить чат к ивентам\n"
    )
    await update.message.reply_text(help_text, parse_mode="HTML")


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
    app.add_handler(CommandHandler("help", help_cmd))

    app.run_polling()


if __name__ == "__main__":
    main()
