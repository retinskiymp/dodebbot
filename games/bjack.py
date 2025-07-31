import math
import random
from enum import Enum
from functools import wraps, partial
from collections import defaultdict
from dataclasses import dataclass, field
from typing import List, Dict

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler
from db import SessionLocal, get_player, get_player_by_id, set_balance, change_balance
from config import BJ_RESTART, FREE_MONEY

from telegram.error import BadRequest, RetryAfter


def safe_game_method(func):
    @wraps(func)
    async def wrapper(self, *args, **kwargs):
        try:
            return await func(self, *args, **kwargs)
        except Exception as e:
            await self.ctx.bot.send_message(
                chat_id=self.chat_id, text=f"Произошла ошибка в {func.__name__}: {e}"
            )
            import traceback

            traceback.print_exc()

            with SessionLocal() as db:
                for player in self.players:
                    change_balance(db, player.uid, self.chat_id, player.bet)
            db.commit()
            self.cleanup()
            self._paused_msg = "⚠️ Кирдык"
            raise

    return wrapper


class Stage(Enum):
    Bet = "bet"
    Play = "play"
    End = "end"
    Close = "close"


BET_TIMEOUT = BJ_RESTART
ACTION_TIMEOUT = 20
RESTART_DELAY = BJ_RESTART

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


def can_split(hand: list[str]) -> bool:
    if len(hand) != 2:
        return False

    rank1 = hand[0][:-1]
    rank2 = hand[1][:-1]

    return rank1 == rank2


@dataclass
class Player:
    uid: int
    name: str
    hand: List[str] = field(default_factory=list)
    bet: int = 0
    balance: int = 0
    splitted: bool = False
    result: str = ""


@dataclass
class Dealer:
    hand: List[str] = field(default_factory=list)


@dataclass
class SessionResults:
    name: str = ""
    profit: int = 0


class BlackjackGame:
    def __init__(self, chat_id: int, msg_id: int, context: ContextTypes.DEFAULT_TYPE):
        self.chat_id = chat_id
        self.msg_id = msg_id
        self.ctx = context
        self.stage = Stage.Bet
        self.dealer = Dealer()
        self.players: List[Player] = []
        self.active_player_index = 0
        self.deck = []
        self.session_results: Dict[int, SessionResults] = {}

        self.timer = None

        self._last_table = None
        self._last_keyboard = None
        self._paused = False
        self._paused_msg = None
        self._paused_timeout = None

    @classmethod
    @safe_game_method
    async def start(cls, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat.id in context.application.bot_data.get("games", {}):
            return await update.message.reply_text("Игра уже идет в этом чате.")

        msg = await update.message.reply_text(
            "Запуск игры...",
        )

        game = cls(update.effective_chat.id, msg.message_id, context)
        game.stage = Stage.Bet

        context.application.bot_data.setdefault("games", {})[msg.chat.id] = game
        game.dealer.hand = []
        await game.update_table()

        game.timer = context.job_queue.run_once(
            game.end_bet,
            when=BET_TIMEOUT,
            chat_id=game.chat_id,
            name=f"bj_end_bet_{game.chat_id}",
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
            [
                InlineKeyboardButton("Микрозайм", callback_data="bj_bet_mz"),
            ],
        ]
        return InlineKeyboardMarkup(buttons)

    @staticmethod
    def _build_play_keyboard(self) -> InlineKeyboardMarkup:
        rows = [
            [
                InlineKeyboardButton("🕹️ Hit", callback_data="bj_act_hit"),
                InlineKeyboardButton("🚗💨 Stand", callback_data="bj_act_stand"),
            ]
        ]

        active_player = self._active_player()
        if active_player:
            with SessionLocal() as db:
                p = get_player_by_id(db, active_player.uid, self.chat_id)
                if p.balance >= active_player.bet:
                    rows.append(
                        [
                            InlineKeyboardButton(
                                "🚀 Double", callback_data="bj_act_double"
                            )
                        ]
                    )
                    hand = active_player.hand
                    if can_split(hand):
                        splits_done = sum(
                            1
                            for pl in self.players
                            if pl.uid == active_player.uid and pl.splitted
                        )
                        if splits_done < 3:
                            rows.append(
                                [
                                    InlineKeyboardButton(
                                        "✂️ Split", callback_data="bj_act_split"
                                    )
                                ]
                            )

        return InlineKeyboardMarkup(rows)

    def _active_player(self):
        if self.active_player_index < len(self.players):
            return self.players[self.active_player_index]
        else:
            return None

    def _build_keyboard(self) -> InlineKeyboardMarkup:
        if self.stage == Stage.Bet:
            return self._build_bet_keyboard()
        elif self.stage == Stage.Play and not self._active_player() is None:
            return self._build_play_keyboard(self)
        return None

    @safe_game_method
    async def _build_table(self, header: str = None, footer: str = ""):
        print(
            f"Building table for chat {self.chat_id}, stage: {self.stage}, paused: {self._paused}, players: {self.players}, dealer: {self.dealer}"
        )
        lines = []

        lines.append("=_=_♠️ BLACKJACK ♠️_=_=\n")

        if header:
            lines.append(header + "\n")

        active_player = self._active_player()
        if self.stage == Stage.Play and not active_player is None:
            first = self.dealer.hand[0]
            val = hand_value([first])
            lines.append(f"😎 Дилер [{first}]\n")
        elif self.stage == Stage.End:
            cards = " ".join(self.dealer.hand)
            val = hand_value(self.dealer.hand)
            lines.append(f"😎 Дилер [{cards}] [{val}]\n")

        for player in self.players:
            cards = " ".join(player.hand)
            val = hand_value(player.hand)

            prefix = (
                "🔸 " if self.stage == Stage.Play and player == active_player else ""
            )
            if self.stage == Stage.Bet:
                lines.append(
                    f"{prefix}{player.name} | 💸: {player.bet} | 🏦: {player.balance}"
                )
            elif self.stage == Stage.Play:
                lines.append(f"{prefix} {player.name} [{cards}]")
            else:
                lines.append(f"{prefix} {player.name} [{cards}] [{val}]\n")

        if self.stage == Stage.End:
            lines.append("Результаты:")
            for player in self.players:
                res = player.result
                lines.append(f"{res}")

        if footer:
            lines.append(footer)

        keyboard = self._build_keyboard()
        return "\n".join(lines), keyboard

    async def _pause_game(self, delay_seconds: int, notice: str):
        print(f"Pausing game {self.chat_id} for {delay_seconds} seconds")
        if self._paused:
            return

        self._paused = True
        self._paused_msg = (
            f"{notice}, игра скоро возобновится, подождите {delay_seconds} сек."
        )
        if self.timer:
            try:
                self.timer.schedule_removal()
            except Exception:
                pass

        self.pause_timer = self.ctx.job_queue.run_once(
            self._recover,
            when=delay_seconds,
            chat_id=self.chat_id,
            name=f"bj_recover_{self.chat_id}",
        )

    async def _recover(self, job_ctx=None):
        print(f"Recovering game {self.chat_id} after pause")
        self._paused = False
        self._paused_msg = None
        self._paused_timeout = None

        await self.update_table(header="♻️ Игра возобновлена")

        if self.stage == Stage.Bet:
            print("Resuming betting stage")
            self.timer = self.ctx.job_queue.run_once(
                self.end_bet,
                when=BET_TIMEOUT,
                chat_id=self.chat_id,
                name=f"bj_end_bet_{self.chat_id}",
            )
        elif self.stage == Stage.Play:
            print("Resuming play stage")
            await self.next_turn()
        elif self.stage == Stage.End:
            print("Resuming end stage")
            self.ctx.job_queue.run_once(
                self._restart_game,
                when=RESTART_DELAY,
                chat_id=self.chat_id,
                name=f"bj_restart_{self.chat_id}",
            )

    @safe_game_method
    async def handle_bet(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if self._paused:
            return await query.answer(
                self._paused_msg,
                show_alert=True,
            )

        uid = query.from_user.id
        player = next((p for p in self.players if p.uid == uid), None)
        tmp_bet = player.bet if player else 0
        parts = query.data.split("_")
        with SessionLocal() as db:
            p = get_player(db, uid, self.chat_id, query.from_user.first_name)
            total_balance = p.balance + tmp_bet
            if parts[2] == "mz":
                if total_balance >= FREE_MONEY:
                    return await query.answer("У тебя еще есть деньги", show_alert=True)
                amount = FREE_MONEY
                total_balance = FREE_MONEY
            elif total_balance <= 0:
                return await query.answer("Нет монеточек", show_alert=True)
            elif parts[2] == "pct":
                pct = int(parts[3])
                amount = total_balance * pct // 100
            else:
                amount = int(parts[2])

            if amount <= 0 or amount > total_balance:
                return await query.answer("Неверная ставка", show_alert=True)
            if amount == tmp_bet:
                return await query.answer("Такая ставка уже сделана", show_alert=False)
            set_balance(db, uid, self.chat_id, total_balance - amount)
            db.commit()

        new_player = Player(
            uid=uid,
            name=query.from_user.first_name,
            bet=amount,
            balance=p.balance,
        )
        for i, pl in enumerate(self.players):
            if pl.uid == uid:
                self.players[i] = new_player
            break
        else:
            self.players.append(new_player)
        self.session_results[uid] = SessionResults(
            name=query.from_user.first_name, profit=0
        )

        await query.answer(f"Ставка {amount} принята")
        await self.update_table()

    @safe_game_method
    async def end_bet(self, job_ctx=None):
        print(
            f"Ending betting for chat {self.chat_id}, stage: {self.stage}, paused: {self._paused}"
        )
        if self._paused:
            return

        if not self.players:
            if self.session_results:
                lines = ["Стол закрыт, итоги:"]
                for uid, result in self.session_results.items():
                    name = result.name
                    sign = "+" if result.profit >= 0 else ""
                    lines.append(f"• {name}: {sign}{result.profit}")
                text = "\n".join(lines)
            else:
                text = "Никто не поставил — игра отменена."

            self.stage = Stage.Close
            await self.update_table(footer=text)
            self.cleanup()
            return

        self.stage = Stage.Play
        self.deck = build_deck()
        self.dealer.hand = [self.deck.pop(), self.deck.pop()]
        for player in self.players:
            player.hand = [
                self.deck.pop(),
                self.deck.pop(),
            ]
        await self.update_table()
        await self.next_turn()

    @safe_game_method
    async def next_turn(self):
        print(
            f"Next turn for chat {self.chat_id}, , stage: {self.stage}, paused: {self._paused}"
        )
        if self._paused:
            return
        active_player = self._active_player()
        if active_player:
            self.timer = self.ctx.job_queue.run_once(
                partial(self._do_action, "stand", None),
                when=ACTION_TIMEOUT,
                chat_id=self.chat_id,
                name=f"bj_auto_stand_{self.chat_id}",
            )
        else:
            await self.finish_round()

    @safe_game_method
    async def handle_action(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        print(
            f"Handling action for chat {self.chat_id}, , stage: {self.stage}, paused: {self._paused}"
        )
        query = update.callback_query
        if self._paused:
            return await query.answer(
                self._paused_msg,
                show_alert=True,
            )
        uid = query.from_user.id
        active_player = self._active_player()
        if (
            self.stage != Stage.Play
            or active_player is None
            or active_player.uid != uid
        ):
            return await query.answer("Не ваш ход", show_alert=True)
        act = query.data.split("_")[-1]
        if self.timer:
            try:
                self.timer.schedule_removal()
            except Exception as e:
                print(f"Error handle_action: {e}")
        await self._do_action(act, query)

    @safe_game_method
    async def _do_action(self, act: str, query, job_ctx=None):
        print(
            f"Doing action '{act}' for chat {self.chat_id}, idx: {self.active_player_index}, stage: {self.stage}, paused: {self._paused}"
        )

        active_player = self._active_player()
        if act == "hit":
            active_player.hand.append(self.deck.pop())
        if act == "stand" or hand_value(active_player.hand) > 21:
            self.active_player_index += 1
        if act == "double":
            with SessionLocal() as db:
                p = get_player_by_id(db, active_player.uid, self.chat_id)
                if p.balance < active_player.bet:
                    if query:
                        return await query.answer(
                            "Недостаточно средств для удвоения ставки", show_alert=True
                        )
                set_balance(
                    db,
                    active_player.uid,
                    self.chat_id,
                    p.balance - active_player.bet,
                )
                active_player.bet *= 2
                db.commit()
            active_player.hand.append(self.deck.pop())
            self.active_player_index += 1
        if act == "split":
            if can_split(active_player.hand) is False:
                if query:
                    return await query.answer(
                        "Невозможно разделить руки", show_alert=True
                    )
            with SessionLocal() as db:
                p = get_player_by_id(db, active_player.uid, self.chat_id)
                if p.balance < active_player.bet:
                    if query:
                        return await query.answer(
                            "Недостаточно средств для сплита", show_alert=True
                        )
                set_balance(
                    db,
                    active_player.uid,
                    self.chat_id,
                    p.balance - active_player.bet,
                )
                db.commit()
            new_hand = [active_player.hand.pop(), self.deck.pop()]
            self.players.append(
                Player(
                    uid=active_player.uid,
                    name=active_player.name + " (✂️)",
                    hand=new_hand,
                    bet=active_player.bet,
                    balance=p.balance,
                    splitted=True,
                )
            )
            active_player.hand.append(self.deck.pop())

        if query:
            await query.answer()
        await self.update_table()
        await self.next_turn()

    @safe_game_method
    async def finish_round(self):
        print(
            f"Finishing round for chat {self.chat_id}, , stage: {self.stage}, paused: {self._paused}"
        )
        while hand_value(self.dealer.hand) < 17:
            self.dealer.hand.append(self.deck.pop())

        dealer_val = hand_value(self.dealer.hand)
        dealer_hand_count = len(self.dealer.hand)
        with SessionLocal() as db:
            for player in self.players:
                player_val = hand_value(player.hand)
                player_bet = player.bet
                player_name = player.name
                player_hand_count = len(player.hand)
                player_profit = 0
                if (
                    player_val > 21
                    or (dealer_val <= 21 and dealer_val > player_val)
                    and player_val != 21
                ):
                    res = f"💀 {player_name} -{player_bet}"
                    player_profit = -player_bet
                elif (
                    player_val == dealer_val
                    and dealer_hand_count > 2
                    and player_hand_count > 2
                ) or (
                    player_val == 21
                    and dealer_val == 21
                    and dealer_hand_count == 2
                    and player_hand_count == 2
                ):
                    res = f"😐 {player_name} Ничья"
                    change_balance(db, player.uid, self.chat_id, player_bet)
                else:
                    coef = 1
                    if player_val == 21:
                        coef = 1.5
                    win = math.ceil(player_bet * coef)
                    res = f"💹 {player_name} +{win}"
                    player_profit += win
                    change_balance(db, player.uid, self.chat_id, win + player_bet)
                player.result = res
                self.session_results[player.uid].profit += player_profit

            db.commit()

        self.stage = Stage.End
        await self.update_table()
        if self._paused:
            return
        self.ctx.job_queue.run_once(
            self._restart_game,
            when=RESTART_DELAY,
            chat_id=self.chat_id,
            name=f"bj_restart_{self.chat_id}",
        )

    @safe_game_method
    async def _restart_game(self, job_ctx=None):
        print(
            f"Restarting game for chat {self.chat_id}, stage: {self.stage}, paused: {self._paused}"
        )
        self.players.clear()
        self.active_player_index = 0
        self.stage = Stage.Bet
        self._last_table = None
        self._last_keyboard = None

        await self.update_table(header="Открыта новая раздача!")

        self.timer = self.ctx.job_queue.run_once(
            self.end_bet,
            when=BET_TIMEOUT,
            chat_id=self.chat_id,
            name=f"bj_end_bet_{self.chat_id}",
        )

    @safe_game_method
    async def update_table(self, header: str = None, footer: str = ""):
        print(
            f"Updating table for chat {self.chat_id}, stage: {self.stage}, paused: {self._paused}"
        )
        table, keyboard = await self._build_table(header, footer)
        if table == self._last_table and keyboard == self._last_keyboard:
            return
        self._last_table, self._last_keyboard = table, keyboard
        try:
            if keyboard:
                await self.ctx.bot.edit_message_text(
                    table,
                    chat_id=self.chat_id,
                    message_id=self.msg_id,
                    reply_markup=keyboard,
                )
            else:
                await self.ctx.bot.edit_message_text(
                    table,
                    chat_id=self.chat_id,
                    message_id=self.msg_id,
                )
        except RetryAfter as e:
            await self._pause_game(
                e.retry_after,
                notice=(f"⚠️ Флуд кокблок"),
            )
        except Exception as e:
            await self._pause_game(5, notice=(f"⚠️ Ошибка обновления"))

    def cleanup(self):
        if self.timer:
            try:
                self.timer.schedule_removal()
            except Exception as e:
                print(f"Error cleanup: {e}")
        self.ctx.application.bot_data["games"].pop(self.chat_id, None)


async def dispatch_bet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = context.application.bot_data.get("games", {}).get(update.effective_chat.id)
    if game:
        await game.handle_bet(update, context)


async def dispatch_act(update: Update, context: ContextTypes.DEFAULT_TYPE):
    game = context.application.bot_data.get("games", {}).get(update.effective_chat.id)
    if game:
        await game.handle_action(update, context)


def register_handlers(app):
    app.add_handler(CommandHandler(["blackjack", "bj"], BlackjackGame.start))
    app.add_handler(CallbackQueryHandler(dispatch_bet, pattern="^bj_bet_"))
    app.add_handler(CallbackQueryHandler(dispatch_act, pattern="^bj_act_"))
