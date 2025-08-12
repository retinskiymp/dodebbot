from typing import Dict, Tuple
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler

from handlers import HandlerBlackJack, HandlerWiki  # твои структурки с long/short
from items import ItemId, ITEMS

BLACK_JACK_RULES = """
♠️♥️♦️♣️ Правила игры в Блэкджек ♣️♦️♥️♠️

🎯 1. Цель игры
Набрать сумму очков как можно ближе к 21, не превышая его.
Туз (A) может стоить 1 или 11 очков — значение выбирается автоматически так,
чтобы рука была максимально выгодной, но не превысила 21.
Картинки (J, Q, K) = 10 очков.
Остальные карты — по номиналу.
"Блэкджек" = туз + карта на 10 очков с первых двух карт.

🃏 2. Раздача карт
Каждый игрок и дилер получают по 2 карты.
Карты игрока открыты, у дилера одна открыта, вторая закрыта.
Игроки ходят по очереди сверху вниз, активный игрок отмечен «🔸».

🎮 3. Действия игрока
🕹️ Взять карту (Hit) — получить ещё одну карту.
🚗💨 Хватит (Stand) — завершить ход, оставить текущие карты.
🚀 Удвоить (Double) — удвоить ставку, взять ровно одну карту и завершить ход. Доступно только на первых двух картах и при достаточном балансе.
✂️ Разделить (Split) — если две первые карты одинаковые, можно разделить их на две руки, добавив ставку на вторую. Ограничение — не более 3 сплитов.

🤵 4. Дилер
После завершения ходов всех игроков дилер открывает вторую карту.
Берёт карты, пока не наберёт минимум 17 очков.
На 17 (включая «мягкие» 17 с тузом) дилер останавливается.

🏆 5. Выигрыш и проигрыш
>21: перебор, игрок проигрывает.
Дилер >21: выигрывают все оставшиеся игроки.
Блэкджек (игрок) побеждает обычные 21 дилера (>2 карт) и игроку выплачивается 3:2.
Если у дилера блэкджек, а у игрока нет — проигрыш.
Если суммы равны — ничья (Push), ставка возвращается.
"""

DOUBLE_DESC = """
🚀 Удвоить (Double)

Удваивает ставку руки, выдаётся ровно одна карта, и ход этой руки сразу завершается.  
Доступно только при 2 картах в руке и достаточном балансе для второй ставки.    

Можно использовать и после сплита.

Пример:
У тебя 9♠ и 2♥ (11 очков), ставка 100.  
Жмёшь «Удвоить», ставка становится 200, с баланса списывается ещё 100.  
Получаешь 10♦ → всего 21 очко, и ход завершается.
"""

SPLIT_DESC = """
✂️ Разделить (Split)

Делит руку на две, если первые две карты одного ранга (например, K♠ и K♦, не работает 10♠ и K♦).  
С баланса списывается вторая ставка такого же размера. Каждая новая рука получает по одной карте и играется отдельно.  

Особенности:
Максимум 3 сплита за раздачу.  
Каждая рука считается и оплачивается отдельно.  
После сплита можно удваивать и использовать предметы (например, страховку).

Пример:
У тебя 8♣ и 8♥, ставка 200.  
Жмёшь «Разделить» → две руки:  
1️⃣ name 8♣ + A♦ 
2️⃣ name (✂️) 8♥ + 3♠ 
С баланса списывается ещё 200 на вторую руку.
Для каждой руки игра продолжается отдельно, как обычно.
"""

INSURANCE_DESC = f"""
{ITEMS[ItemId.Insurance].name} <{ITEMS[ItemId.Insurance].id_short_name}>

Что это
Разовый талон, позволяющий купить страховку в блэкджеке, если у дилера первая карта — туз.

Как работает
— Нужен предмет «{ITEMS[ItemId.Insurance].name}» в инвентаре.  
— Кнопка страховки появляется только при 2 картах в руке и тузе у дилера.  
— Стоимость: ставка / 2, списывается с баланса и расходуется 1 талон.  
— Если у дилера натуральный блэкджек: выплата 2:1 по страховке.  
— Если блэкджека у дилера нет: страховая ставка сгорает.  
— Страховка не влияет на исход основной руки; она считается отдельно.

Пример:
Поставлено 100 монет, у дилера туз.  
В инвентаре есть страховка → появляется кнопка «{ITEMS[ItemId.Insurance].name}».  
При нажатии кнопки с баланса списывается 50 монет и тратится 1 талон.  
Если у дилера блэкджек → получение 150-и монет по страховке (выигрыш 100 + возврат 50).  
Если нет → проигрыш 50 монет за страховку.
"""

HOTCARD_DESC = f"""
{ITEMS[ItemId.HotCard].name} <{ITEMS[ItemId.HotCard].id_short_name}>

Что это
Одноразовый предмет-подсказка: оценивает несколько ближайших карт в колоде и подсказывает, чего больше — высоких или низких.

Как работает
— Расходует 1 «{ITEMS[ItemId.HotCard].name}».  
— Анализирует ближайшие карты в колоде (без раскрытия самих карт).  
— Даёт подсказку:
   • 🔥 «Старшие впереди» (10, J, Q, K, A больше)  
   • ❄️ «Младшие впереди» (2–9 больше)  
   • ⚖️ «Баланс/нет явного перевеса»
— Это только ориентир; шансы, не гарантия исхода.
"""

ALIAS_BJ = (HandlerBlackJack.long, HandlerBlackJack.short)
ALIAS_DOUBLE = ("double",)
ALIAS_SPLIT = ("split",)
ALIAS_INSURANCE = (ITEMS[ItemId.Insurance].id, ITEMS[ItemId.Insurance].id_short_name)
ALIAS_HOTCARD = (ITEMS[ItemId.HotCard].id, ITEMS[ItemId.HotCard].id_short_name)

WIKI_DATA: Dict[Tuple[str, ...], str] = {
    ALIAS_BJ: BLACK_JACK_RULES,
    ALIAS_DOUBLE: DOUBLE_DESC,
    ALIAS_SPLIT: SPLIT_DESC,
    ALIAS_INSURANCE: INSURANCE_DESC,
    ALIAS_HOTCARD: HOTCARD_DESC,
}


def _normalize(s: str) -> str:
    return s.strip().lower()


def _lookup(term: str) -> str:
    q = _normalize(term)
    for keys, desc in WIKI_DATA.items():
        if q in (k.lower() for k in keys if k):
            return desc
    return f"❌ Термин «{term}» не найден. Попробуй другой вариант или синоним."


def _is_bj(term: str) -> bool:
    q = _normalize(term)
    return q in {k.lower() for k in ALIAS_BJ if k}


def _wiki_inline_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(text="/wiki double", callback_data="wiki:double"),
                InlineKeyboardButton(text="/wiki split", callback_data="wiki:split"),
            ]
        ]
    )


async def wiki_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not context.args:
        await update.effective_chat.send_message("Использование: /wiki <cmd>/<item_id>")
        return

    query = " ".join(context.args)
    text = _lookup(query)

    if _is_bj(query):
        await update.effective_chat.send_message(text, reply_markup=_wiki_inline_kb())
    else:
        await update.effective_chat.send_message(text)


async def wiki_inline_cb(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    q = update.callback_query
    await q.answer()
    term = q.data.split(":", 1)[1]  # "double" | "split"
    text = _lookup(term)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=text)


def register_handlers(app):
    app.add_handler(CommandHandler(list(HandlerWiki), wiki_command))
    app.add_handler(
        CallbackQueryHandler(wiki_inline_cb, pattern=r"^wiki:(double|split)$")
    )
