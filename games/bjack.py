import asyncio
import random
from enum import Enum
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler
from db import SessionLocal, get_player


# Стадии игры
class Stage(Enum):
    JOIN = "join"
    BET = "bet"
    PLAY = "play"
    END = "end"


# Таймауты и задержки
JOIN_TIMEOUT = 10  # сек на присоединение
BET_TIMEOUT = 10  # сек на ставку
ACTION_TIMEOUT = 20  # сек на ход
RESTART_DELAY = 5  # сек перед новой игрой

# Опции ставок
FIXED_BETS = [50, 100, 200, 300, 500]
PERCENT_BETS = [10, 20, 30, 40, 50]

# Колода карт
RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
SUITS = ["♠", "♥", "♦", "♣"]


def build_deck():
    deck = [r + s for r in RANKS for s in SUITS]
    random.shuffle(deck)
    return deck


def hand_value(hand):
    total, aces = 0, 0
    for c in hand:
        r = c[:-1]
        if r in ["J", "Q", "K"]:
            total += 10
        elif r == "A":
            total += 11
            aces += 1
        else:
            total += int(r)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


class BlackjackGame:
    def __init__(self, chat_id, msg_id, context):
        self.chat_id = chat_id
        self.msg_id = msg_id
        self.ctx = context
        self.stage = Stage.JOIN
        self.players = {}  # uid -> {'name', 'hand', 'bet', 'balance'}
        self.order = []
        self.dealer = {"hand": []}
        self.deck = []
        self.timer = None
        self.idx = 0

    @classmethod
    async def start(cls, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Запуск новой игры или приглашение к присоединению."""
        msg = await update.message.reply_text(
            "🃏 Блэкджек: нажмите «Присоединиться»",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("Присоединиться", callback_data="bj_join")]]
            ),
        )
        game = cls(update.effective_chat.id, msg.message_id, context)
        context.application.bot_data.setdefault("bj_games", {})[msg.chat.id] = game
        game.schedule_join_timeout()

    def schedule_join_timeout(self):
        self.timer = self.ctx.job_queue.run_once(self._end_join, JOIN_TIMEOUT)

    async def _end_join(self, ctx):
        await self.end_join()

    async def end_join(self):
        if not self.players:
            await self.ctx.bot.edit_message_text(
                "Никто не присоединился — игра отменена.",
                chat_id=self.chat_id,
                message_id=self.msg_id,
            )
            self.cleanup()
            return
        self.stage = Stage.BET
        await self.update_table(header="💰 Ставки: выберите опцию")
        self.schedule_bet_timeout()

    def schedule_bet_timeout(self):
        self.timer = self.ctx.job_queue.run_once(self._end_bet, BET_TIMEOUT)

    async def _end_bet(self, ctx):
        await self.end_bet()

    async def handle_join(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        uid = q.from_user.id
        if self.stage is not Stage.JOIN:
            return await q.answer("Регистрация закрыта", show_alert=True)
        with SessionLocal() as db:
            p = get_player(db, uid, self.chat_id, q.from_user.first_name)
        if p.balance <= 0:
            return await q.answer("У вас нет монет", show_alert=True)
        if uid in self.players:
            return await q.answer("Вы уже за столом", show_alert=True)
        self.players[uid] = {
            "name": q.from_user.first_name,
            "hand": [],
            "bet": None,
            "balance": p.balance,
        }
        self.order.append(uid)
        await q.answer("Вы присоединились!")
        await self.update_table()

    async def end_bet(self):
        # Удаление игроков без ставки
        for uid in list(self.players):
            if self.players[uid]["bet"] is None:
                self.players.pop(uid)
                self.order.remove(uid)
        if not self.players:
            await self.ctx.bot.edit_message_text(
                "Никто не сделал ставку — игра отменена.",
                chat_id=self.chat_id,
                message_id=self.msg_id,
            )
            self.cleanup()
            return
        self.stage = Stage.PLAY
        self.start_play()

    def start_play(self):
        # Раздача карт
        self.deck = build_deck()
        self.dealer["hand"] = [self.deck.pop(), self.deck.pop()]
        for uid, st in self.players.items():
            st["hand"] = [self.deck.pop(), self.deck.pop()]
            with SessionLocal() as db:
                p = get_player(db, uid, self.chat_id, st["name"])
                p.balance -= st["bet"]
                db.commit()
                st["balance"] = p.balance
        asyncio.create_task(self.update_table())
        asyncio.create_task(self.next_turn())

    async def handle_bet(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        uid = q.from_user.id
        if self.stage is not Stage.BET or uid not in self.players:
            return await q.answer("Нельзя ставить сейчас", show_alert=True)
        parts = q.data.split("_")
        if parts[2] == "pct":
            pct = int(parts[3])
            base = self.players[uid]["balance"]
            amount = base * pct // 100
        else:
            amount = int(parts[2])
        if amount <= 0:
            return await q.answer("Неверная ставка", show_alert=True)
        if amount > self.players[uid]["balance"]:
            return await q.answer("Ставка не может превышать баланс", show_alert=True)
        self.players[uid]["bet"] = amount
        await q.answer(f"Ставка {amount} принята")
        await self.update_table()

    async def next_turn(self):
        if self.idx < len(self.order):
            uid = self.order[self.idx]
            name = self.players[uid]["name"]
            await self.update_table(header=f"🔸 Ход: {name}")
            self.timer = self.ctx.job_queue.run_once(
                lambda ctx: asyncio.create_task(self._do_action("stand")),
                ACTION_TIMEOUT,
            )
        else:
            await self.finish_round()

    async def handle_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        uid = q.from_user.id
        if self.stage is not Stage.PLAY or uid != self.order[self.idx]:
            return await q.answer("Сейчас не ваш ход", show_alert=True)
        act = q.data.split("_")[-1]
        if self.timer:
            try:
                self.timer.schedule_removal()
            except:
                pass
        await q.answer()
        await self._do_action(act)

    async def _do_action(self, act):
        uid = self.order[self.idx]
        st = self.players[uid]
        if act in ("hit", "double"):
            st["hand"].append(self.deck.pop())
            if act == "double" and len(st["hand"]) == 3:
                st["bet"] *= 2
                with SessionLocal() as db:
                    p = get_player(db, uid, self.chat_id, st["name"])
                    p.balance -= st["bet"] // 2
                    db.commit()
                    st["balance"] = p.balance
        if act in ("stand", "double") or hand_value(st["hand"]) > 21:
            self.idx += 1
        await self.update_table()
        await self.next_turn()

    async def finish_round(self):
        # Дилер добирает
        while hand_value(self.dealer["hand"]) < 17:
            self.dealer["hand"].append(self.deck.pop())
        results = []
        d_val = hand_value(self.dealer["hand"])
        for uid, st in self.players.items():
            t = hand_value(st["hand"])
            bet = st["bet"]
            name = st["name"]
            if t > 21 or (d_val <= 21 and d_val > t):
                res = f"💀 {name} -{bet}"
            elif t == d_val:
                res = f"😑 {name} +{bet}"
                with SessionLocal() as db:
                    p = get_player(db, uid, self.chat_id, name)
                    p.balance += bet
                    db.commit()
                    st["balance"] = p.balance
            else:
                win = bet * 2
                res = f"🏅 {name} +{win}"
                with SessionLocal() as db:
                    p = get_player(db, uid, self.chat_id, name)
                    p.balance += win
                    db.commit()
                    st["balance"] = p.balance
            results.append(res)
        footer = "\n" + "\n".join(results) + f"\nНовая игра через {RESTART_DELAY} сек"
        await self.update_table(header="📊 Результаты раунда", footer=footer)
        await asyncio.sleep(RESTART_DELAY)
        # Сброс участников
        self.players.clear()
        self.order.clear()
        self.idx = 0
        self.stage = Stage.JOIN
        await self.update_table(header="🃏 Новая игра: нажмите «Присоединиться»")
        self.schedule_join_timeout()

    async def update_table(self, header=None, footer=""):
        lines = []
        if header:
            lines.append(header)
        # Карты дилера
        if self.stage is Stage.PLAY and self.idx < len(self.order):
            first = self.dealer["hand"][0]
            val = hand_value([first])
            lines.append(f"🂠 Дилер: {first} ({val}) 🂠")
        else:
            dcards = " ".join(self.dealer["hand"])
            dval = hand_value(self.dealer["hand"])
            lines.append(f"🂠 Дилер: {dcards} ({dval})")
        # Игроки
        for uid in self.order:
            st = self.players[uid]
            cards = " ".join(st["hand"]) if st["hand"] else ""
            val = hand_value(st["hand"]) if st["hand"] else ""
            lines.append(
                f"• {st['name']} | Карты: {cards} ({val}) | Ставка: {st['bet']} | Баланс: {st['balance']}"
            )
        if footer:
            lines.append(footer)
        try:
            await self.ctx.bot.edit_message_text(
                "\n".join(lines),
                chat_id=self.chat_id,
                message_id=self.msg_id,
                reply_markup=self._keyboard(),
            )
        except Exception:
            pass

    def _keyboard(self):
        if self.stage is Stage.JOIN:
            return InlineKeyboardMarkup(
                [[InlineKeyboardButton("Присоединиться", callback_data="bj_join")]]
            )
        if self.stage is Stage.BET:
            return InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(str(x), callback_data=f"bj_bet_{x}")
                        for x in FIXED_BETS
                    ],
                    [
                        InlineKeyboardButton(f"{x}%", callback_data=f"bj_bet_pct_{x}")
                        for x in PERCENT_BETS
                    ],
                ]
            )
        if self.stage is Stage.PLAY and self.idx < len(self.order):
            return InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("Hit", callback_data="bj_act_hit"),
                        InlineKeyboardButton("Stand", callback_data="bj_act_stand"),
                        InlineKeyboardButton("Double", callback_data="bj_act_double"),
                    ]
                ]
            )
        return None

    def cleanup(self):
        if self.timer:
            try:
                self.timer.schedule_removal()
            except:
                pass
        self.ctx.application.bot_data["bj_games"].pop(self.chat_id, None)


# Регистрация хендлеров


def register_handlers(app):
    app.add_handler(CommandHandler("blackjack", BlackjackGame.start))
    app.add_handler(
        CallbackQueryHandler(
            lambda u, c: asyncio.create_task(
                c.application.bot_data["bj_games"][u.effective_chat.id].handle_join(
                    u, c
                )
            ),
            pattern="^bj_join$",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            lambda u, c: asyncio.create_task(
                c.application.bot_data["bj_games"][u.effective_chat.id].handle_bet(u, c)
            ),
            pattern="^bj_bet_",
        )
    )
    app.add_handler(
        CallbackQueryHandler(
            lambda u, c: asyncio.create_task(
                c.application.bot_data["bj_games"][u.effective_chat.id].handle_action(
                    u, c
                )
            ),
            pattern="^bj_act_",
        )
    )
