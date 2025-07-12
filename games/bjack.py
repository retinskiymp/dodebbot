import asyncio
import random
from enum import Enum
from functools import wraps
from collections import defaultdict
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler
from db import SessionLocal, get_player


def safe_game_method(func):
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        try:
            return await func(self, *args, **kwargs)
        except Exception:
            self.cleanup()
            await self.ctx.bot.send_message(
                self.chat_id, f"Произошла ошибка в {func.__name__}."
            )

    return wrapper


class Stage(Enum):
    BET = "bet"
    PLAY = "play"
    END = "end"


BET_TIMEOUT = 10  # секунд на прием ставок
ACTION_TIMEOUT = 20  # секунд на ход игрока
RESTART_DELAY = 15  # секунд до новой игры

FIXED_BETS = [50, 100, 200, 300, 500]
PERCENT_BETS = [10, 20, 30, 50, 100]

RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"]
SUITS = ["♠", "♥", "♦", "♣"]


def build_deck():
    deck = [r + s for r in RANKS for s in SUITS]
    random.shuffle(deck)
    return deck


def hand_value(hand):
    total, aces = 0, 0
    for card in hand:
        rank = card[:-1]
        if rank in ("J", "Q", "K"):
            total += 10
        elif rank == "A":
            total += 11
            aces += 1
        else:
            total += int(rank)
    while total > 21 and aces:
        total -= 10
        aces -= 1
    return total


class BlackjackGame:
    def __init__(self, chat_id: int, msg_id: int, context: ContextTypes.DEFAULT_TYPE):
        self.chat_id = chat_id
        self.msg_id = msg_id
        self.ctx = context
        self.stage = Stage.BET
        self.players = {}  # uid -> {'name', 'hand', 'bet', 'balance'}
        self.order = []
        self.dealer = {"hand": []}
        self.deck = []
        self.timer = None
        self.idx = 0
        self.session_results: dict[int, int] = defaultdict(int)
        self.player_names: dict[int, str] = {}

    @classmethod
    @safe_game_method
    async def start(cls, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id in context.application.bot_data.get("bj_games", {}):
            return await update.message.reply_text("Игра уже идет в этом чате.")
        msg = await update.message.reply_text(
            "♠ BLACKJACK: ожидание ставок в течение 10 секунд",
            reply_markup=cls._build_bet_keyboard(),
        )
        game = cls(update.effective_chat.id, msg.message_id, context)
        context.application.bot_data.setdefault("bj_games", {})[msg.chat.id] = game
        game.dealer["hand"] = []
        await game.update_table()
        game.timer = context.job_queue.run_once(
            lambda ctx: asyncio.create_task(game.end_bet()), when=BET_TIMEOUT
        )

    @staticmethod
    def _build_bet_keyboard() -> InlineKeyboardMarkup:
        buttons = [
            [
                InlineKeyboardButton(str(x), callback_data=f"bj_bet_{x}")
                for x in FIXED_BETS
            ],
            [
                InlineKeyboardButton(f"{x}%", callback_data=f"bj_bet_pct_{x}")
                for x in PERCENT_BETS
            ],
        ]
        return InlineKeyboardMarkup(buttons)

    @safe_game_method
    async def handle_bet(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        uid = query.from_user.id
        parts = query.data.split("_")
        if uid not in self.players:
            with SessionLocal() as db:
                p = get_player(db, uid, self.chat_id, query.from_user.first_name)
            if p.balance <= 0:
                return await query.answer("Нет монет", show_alert=True)
            self.players[uid] = {
                "name": query.from_user.first_name,
                "hand": [],
                "bet": 0,
                "balance": p.balance,
            }
            self.order.append(uid)
        if parts[2] == "pct":
            pct = int(parts[3])
            amount = self.players[uid]["balance"] * pct // 100
        else:
            amount = int(parts[2])
        if amount <= 0 or amount > self.players[uid]["balance"]:
            return await query.answer("Неверная ставка", show_alert=True)
        self.players[uid]["bet"] = amount
        await query.answer(f"Ставка {amount} принята")
        await self.update_table()

    @safe_game_method
    async def end_bet(self):
        for uid in list(self.players):
            if self.players[uid]["bet"] == 0:
                del self.players[uid]
                self.order.remove(uid)
        if not self.players:
            if self.session_results:
                lines = ["♠ BLACKJACK: Стол закрыт, итоги:"]
                for uid, net in self.session_results.items():
                    name = self.player_names.get(uid, str(uid))
                    sign = "+" if net >= 0 else ""
                    lines.append(f"• {name}: {sign}{net}")
                text = "\n".join(lines)
            else:
                text = "♠ BLACKJACK: Никто не поставил — игра отменена."

            await self.ctx.bot.edit_message_text(
                text, chat_id=self.chat_id, message_id=self.msg_id
            )
            self.cleanup()
            return

        self.stage = Stage.PLAY
        self.deck = build_deck()
        self.dealer["hand"] = [self.deck.pop(), self.deck.pop()]
        for uid in self.order:
            self.players[uid]["hand"] = [self.deck.pop(), self.deck.pop()]
        await self.update_table()
        await self.next_turn()

    @safe_game_method
    async def next_turn(self):
        if self.idx < len(self.order):
            uid = self.order[self.idx]
            await self.update_table(header=f"🔸 Ход: {self.players[uid]['name']}")
            self.timer = self.ctx.job_queue.run_once(
                lambda ctx: asyncio.create_task(self._do_action("stand")),
                when=ACTION_TIMEOUT,
            )
        else:
            await self.finish_round()

    @safe_game_method
    async def handle_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        uid = query.from_user.id
        if self.stage != Stage.PLAY or uid != self.order[self.idx]:
            return await query.answer("Не ваш ход", show_alert=True)
        act = query.data.split("_")[-1]
        if self.timer:
            try:
                self.timer.schedule_removal()
            except:
                pass
        await query.answer()
        await self._do_action(act)

    @safe_game_method
    async def _do_action(self, act: str):
        uid = self.order[self.idx]
        state = self.players[uid]
        if act == "hit":
            state["hand"].append(self.deck.pop())
        if act == "stand" or hand_value(state["hand"]) > 21:
            self.idx += 1
        await self.update_table()
        await self.next_turn()

    @safe_game_method
    async def finish_round(self):
        while hand_value(self.dealer["hand"]) < 17:
            self.dealer["hand"].append(self.deck.pop())
        results = []
        dealer_val = hand_value(self.dealer["hand"])
        with SessionLocal() as db:
            for uid, st in self.players.items():
                t = hand_value(st["hand"])
                bet = st["bet"]
                name = st["name"]
                p = get_player(db, uid, self.chat_id, name)
                profit = 0
                if t > 21 or (dealer_val <= 21 and dealer_val > t) and t != 21:
                    res = f"💀 {name} -{bet}"
                    p.balance -= bet
                    profit = -bet
                elif t == dealer_val:
                    res = f"😑 {name} Ничья"
                else:
                    coef = 1
                    if t == 21:
                        coef = 1.5
                    win = bet * coef
                    res = f"🏅 {name} +{win}"
                    p.balance += win
                    profit += win
                res += f" | 🏦 {p.balance}"
                self.session_results[uid] += profit
                self.player_names[uid] = name
                results.append(res)
            db.commit()

        footer = "\n" + "\n".join(results) + f"\nНовая игра через {RESTART_DELAY} сек"
        self.stage = Stage.END
        await self.update_table(header="📊 Результаты раунда", footer=footer)

        self.ctx.job_queue.run_once(
            lambda job_ctx: asyncio.create_task(self._restart_game()),
            when=RESTART_DELAY,
        )

    @safe_game_method
    async def _restart_game(self):
        self.players.clear()
        self.order.clear()
        self.idx = 0
        self.stage = Stage.BET

        await self.ctx.bot.edit_message_text(
            "🔁 Ставки открыты снова",
            chat_id=self.chat_id,
            message_id=self.msg_id,
            reply_markup=self._build_bet_keyboard(),
        )

        self.timer = self.ctx.job_queue.run_once(
            lambda job_ctx: asyncio.create_task(self.end_bet()), when=BET_TIMEOUT
        )

    @safe_game_method
    async def update_table(self, header: str = None, footer: str = ""):
        lines = []
        if header:
            lines.append(header)

        if self.stage == Stage.PLAY and self.idx < len(self.order):
            first = self.dealer["hand"][0]
            val = hand_value([first])
            lines.append(f"• Дилер: {first} ({val})\n")
        elif self.stage == Stage.END:
            cards = " ".join(self.dealer["hand"])
            val = hand_value(self.dealer["hand"])
            lines.append(f"• Дилер: {cards} ({val})\n")

        for uid in self.order:
            st = self.players[uid]
            cards = " ".join(st["hand"])
            val = hand_value(st["hand"])
            if self.stage == Stage.BET:
                lines.append(
                    f"• {st['name']} | Ставка: {st['bet']} | Баланс: {st['balance']}"
                )
            else:
                lines.append(f"• {st['name']} | {cards} ({val}) | Ставка: {st['bet']}")

        if footer:
            lines.append(footer)
        keyboard = None
        if self.stage == Stage.BET:
            keyboard = self._build_bet_keyboard()
        elif self.stage == Stage.PLAY and self.idx < len(self.order):
            keyboard = InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton("Hit", callback_data="bj_act_hit"),
                        InlineKeyboardButton("Stand", callback_data="bj_act_stand"),
                    ]
                ]
            )
        try:
            await self.ctx.bot.edit_message_text(
                "\n".join(lines),
                chat_id=self.chat_id,
                message_id=self.msg_id,
                reply_markup=keyboard,
            )
        except:
            pass

    def cleanup(self):
        if self.timer:
            try:
                self.timer.schedule_removal()
            except:
                pass
        self.ctx.application.bot_data["bj_games"].pop(self.chat_id, None)


def register_handlers(app):
    app.add_handler(CommandHandler(["blackjack", "bj"], BlackjackGame.start))
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
