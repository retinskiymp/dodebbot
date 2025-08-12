import asyncio
from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    MessageHandler,
    CommandHandler,
    ContextTypes,
    filters,
)
from db import SessionLocal, get_player, get_room
from models import PlayerModel

from items import SHOP_ITEMS, get_shop_item, get_item, player_has_item
from handlers import (
    HandlerStatus,
    HandlerTop,
    HandlerHelp,
    HandlerShop,
    HandlerBuy,
    HandlerUse,
    HandlerBlackJack,
    HandlerWiki,
)

from games.bjack import register_handlers as register_bjack_handlers
from wiki import register_handlers as register_wiki_handlers

from config import SPIN_COST, TOKEN

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


async def status_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat_id = update.effective_chat.id
    with SessionLocal() as session:
        p = get_player(session, user.id, chat_id, user.first_name)
        higher_count = (
            session.query(PlayerModel)
            .filter(PlayerModel.room_id == chat_id, PlayerModel.balance > p.balance)
            .count()
        )
        rank = higher_count + 1
        inv = p.items or {}
        lines: list[str] = []
        for item_id, qty in inv.items():
            item = get_item(item_id)
            if item:
                lines.append(f"{item.name} <{item.id_short_name}> × {qty}")

        if lines:
            inventory_text = "\n".join(f"  {line}" for line in lines)
        else:
            inventory_text = ""

    msg = (
        f"👽 {p.first_name}\n"
        f"🏦 Баланс: {p.balance:,}\n"
        f"📊 Место в топе: {rank}\n"
        f"📦 Инвентарь:\n"
        f"{inventory_text}"
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


async def buy_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await _reply_clean(update, context, "Использование: /buy <id> [кол-во]")
        return
    try:
        item_name = str(context.args[0])
        qty = int(context.args[1]) if len(context.args) > 1 else 1
    except ValueError:
        await _reply_clean(update, context, "Неверные аргументы")
        return
    item = get_shop_item(item_name)
    if not item:
        await _reply_clean(update, context, "Неизвестный товар")
        return
    user = update.effective_user
    chat_id = update.effective_chat.id
    with SessionLocal() as s:
        player = get_player(s, user.id, chat_id, user.first_name)
        cost = item.price * qty
        buy_result = ""
        if player.balance < cost:
            await _reply_clean(update, context, "Недостаточно монет, дружок")
            return
        try:
            buy_result = item.buy(player, qty)
        except ValueError as e:
            await _reply_clean(update, context, str(e))
            return
        await _reply_clean(update, context, buy_result)
        s.commit()


async def use_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await _reply_clean(update, context, "Использование: /use <id> [кол-во]")
        return
    try:
        item_id = str(context.args[0])
        qty = int(context.args[1]) if len(context.args) > 1 else 1
    except ValueError:
        await _reply_clean(update, context, "Неверные аргументы")
        return
    item = get_item(item_id)
    if not item:
        await _reply_clean(update, context, "Неизвестный предмет")
        return
    user = update.effective_user
    chat_id = update.effective_chat.id
    with SessionLocal() as s:
        player = get_player(s, user.id, chat_id, user.first_name)
        if not player_has_item(player, item_id, qty):
            await _reply_clean(update, context, "Нет такого количества")
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
    for item_id in SHOP_ITEMS:
        it = SHOP_ITEMS[item_id]
        lines.append(
            f"{it.name} — {it.price} монет\n🔑 <{it.id}> <{it.id_short_name}>\n📄: {it.desc}"
        )

    await _reply_clean(update, context, "\n\n".join(lines))


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


def _fmt_cmds(aliases) -> str:
    return " ".join(f"/{name}" for name in list(aliases))


async def help_cmd(update: Update, context: ContextTypes.DEFAULT_TYPE):
    help_text = (
        "📖 <b>Доступные команды</b>\n"
        "\n"
        "🎰 <b>Слот-машина</b> — просто пришлите в чат.\n"
        "\n"
        f"👤  {_fmt_cmds(HandlerStatus)} - ваш баланс, место, инвентарь\n"
        f"🏆  {_fmt_cmds(HandlerTop)} - топ-10 игроков по балансу\n"
        f"💰  {_fmt_cmds(HandlerShop)} - магазинчик\n"
        f"🛒  {_fmt_cmds(HandlerBuy)} - купить товар в магазине\n"
        f"📦  {_fmt_cmds(HandlerUse)} - использовать предмет из инвентаря\n"
        "\n"
        f"🃏  {_fmt_cmds(HandlerBlackJack)} - начать игру в блэкджек\n"
        "\n"
        f"📚  {_fmt_cmds(HandlerWiki)} - справочник по терминам (/wiki (cmd or item))"
    )
    await update.effective_message.reply_text(help_text, parse_mode="HTML")


async def after_init(app):
    app.bot_data["games"] = {}


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

    app.add_handler(CommandHandler(list(HandlerStatus), status_cmd))
    app.add_handler(CommandHandler(list(HandlerTop), top_cmd))
    app.add_handler(CommandHandler(list(HandlerHelp), help_cmd))

    app.add_handler(CommandHandler(list(HandlerShop), shop_cmd))
    app.add_handler(CommandHandler(list(HandlerBuy), buy_cmd))
    app.add_handler(CommandHandler(list(HandlerUse), use_cmd))

    register_bjack_handlers(app)
    register_wiki_handlers(app)

    app.run_polling()


if __name__ == "__main__":
    main()
