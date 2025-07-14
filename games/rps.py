from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from events import EventManager
from config import FREE_MONEY
from db import SessionLocal, get_player, get_player_by_id

GESTURES = {
    "rock": "✊",
    "paper": "✋",
    "scissors": "✌️",
}


class RPSGame:
    TIMEOUT = 30

    @classmethod
    async def start_game(cls, update, context: ContextTypes.DEFAULT_TYPE):
        chat_id = update.effective_chat.id
        user = update.effective_user

        if chat_id in context.bot_data.get("games", {}):
            return await update.message.reply_text("В чате уже идёт игра!")

        try:
            with SessionLocal() as db:
                player = get_player(db, user.id, chat_id, user.first_name)
            stake = int(context.args[0])
            if stake <= 0 or stake > player.balance or stake < FREE_MONEY * 3:
                raise ValueError
        except (IndexError, ValueError):
            return await update.message.reply_text(
                "Недостаточно средств или неверный формат ввода\n"
                "Минимальная ставка: "
                f"{FREE_MONEY * 3} монет\n"
                "Использование: /rps <ставка>"
            )

        text = (
            "🎮 Камень–Ножницы–Бумага!\n"
            f"💰 Ставка: {stake}\n\n"
            "Нажмите одну из трёх кнопок-эмоджи, чтобы сыграть.\n"
            "Когда все сделают выбор (или вы захотите), нажмите «Завершить игру»."
        )
        msg = await update.message.reply_text(text, reply_markup=cls._rps_keyboard())

        job = context.job_queue.run_once(
            cls._rps_timeout, when=cls.TIMEOUT, data=chat_id
        )
        context.bot_data.setdefault("games", {})[chat_id] = cls(
            chat_id=chat_id,
            msg_id=msg.message_id,
            initiator_id=user.id,
            stake=stake,
            job=job,
        )

    @classmethod
    async def handle_callback(cls, update, context: ContextTypes.DEFAULT_TYPE):
        q = update.callback_query
        data = q.data
        chat_id = q.message.chat.id
        user = q.from_user

        game = context.bot_data.get("games", {}).get(chat_id)
        if not game:
            return await q.answer("Игра уже завершена", show_alert=True)

        if data.startswith("rps_play_"):

            mgr: EventManager = context.application.bot_data.get("mgr")
            if mgr and mgr.is_active_participant(chat_id, user.id):
                return await q.answer(
                    "🚧 Ты участвуешь в ивенте — не можешь играть", show_alert=True
                )

            with SessionLocal() as db:
                p = get_player(db, user.id, chat_id, user.first_name)
                if p.balance < game.stake:
                    return await q.answer(
                        "Недостаточно монет для участия", show_alert=True
                    )

            gesture = data.split("_")[-1]
            first_time = not game.is_participant(user.id)
            game.record(user.id, user.first_name, gesture)
            await q.answer(f"Вы выбрали {GESTURES[gesture]}")

            if first_time:
                try:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=game.message_id,
                        text=game.summary(),
                        reply_markup=cls._rps_keyboard(),
                    )
                except Exception:
                    pass
            return

        if data == "rps_end":
            if user.id != game.initiator_id:
                return await q.answer(
                    "Только инициатор может завершить игру", show_alert=True
                )
            await q.answer("Завершаю игру…")
            await game.finish(context, reason="по инициативе")

    @classmethod
    async def _rps_timeout(cls, context: ContextTypes.DEFAULT_TYPE):
        job = context.job
        chat_id = job.data
        game = context.bot_data.get("games", {}).get(chat_id)
        if game:
            await game.finish(context, reason="таймаут")

    @staticmethod
    def _rps_keyboard():
        row = [
            InlineKeyboardButton(emoji, callback_data=f"rps_play_{k}")
            for k, emoji in GESTURES.items()
        ]
        finish = [InlineKeyboardButton("🏁 Завершить игру", callback_data="rps_end")]
        return InlineKeyboardMarkup([row, finish])

    def __init__(self, chat_id: int, msg_id: int, initiator_id: int, stake: int, job):
        self.chat_id = chat_id
        self.message_id = msg_id
        self.initiator_id = initiator_id
        self.stake = stake
        self.participants = {}  # user_id -> {'name': ..., 'gesture': ...}
        self.job = job

    def is_participant(self, user_id: int) -> bool:
        return user_id in self.participants

    def record(self, user_id: int, name: str, gesture: str):
        self.participants[user_id] = {"name": name, "gesture": gesture}

    def summary(self) -> str:
        lines = ["🎮 Камень–Ножницы–Бумага", f"💰 Ставка: {self.stake}", ""]
        if self.participants:
            lines.append("👥 Участники:")
            lines += [f"• {info['name']}" for info in self.participants.values()]
        else:
            lines.append("👥 Никто ещё не пришёл")
        return "\n".join(lines)

    def compute_result(self):
        gestures = {info["gesture"] for info in self.participants.values()}
        if len(gestures) in (0, 1, 3):
            return None
        beats = {"rock": "scissors", "scissors": "paper", "paper": "rock"}
        winners, losers = [], []
        for uid, info in self.participants.items():
            g = info["gesture"]
            opp = beats[g]
            if opp in gestures and g in gestures:
                winners.append(uid)
            else:
                losers.append(uid)
        return winners, losers

    async def finish(self, context: ContextTypes.DEFAULT_TYPE, reason: str):
        try:
            self.job.schedule_removal()
        except Exception:
            pass

        header = ["👀 Жесты игроков:"]
        for info in self.participants.values():
            header.append(f"• {info['name']}: {GESTURES[info['gesture']]}")

        res = self.compute_result()
        if res is None:
            text = "\n".join(header + [f"\nНичья ({reason}), ставки возвращаются."])
        else:
            winners, losers = res
            bank = len(losers) * self.stake
            share = -(-bank // len(winners))

            with SessionLocal() as db:
                for uid in losers:
                    p = get_player_by_id(db, uid, self.chat_id)
                    p.balance -= self.stake
                for uid in winners:
                    p = get_player_by_id(db, uid, self.chat_id)
                    p.balance += share
                db.commit()

            names_w = [self.participants[uid]["name"] for uid in winners]
            names_l = [self.participants[uid]["name"] for uid in losers]
            footer = [
                "",
                f"🏅 Победители ({reason}): {', '.join(names_w)} — по {share} монет.",
                f"💀 Проигравшие: {', '.join(names_l)}.",
            ]
            text = "\n".join(header + footer)

        await context.bot.edit_message_text(
            chat_id=self.chat_id, message_id=self.message_id, text=text
        )
        context.bot_data.get("games", {}).pop(self.chat_id, None)
