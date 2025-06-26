import os, random
from datetime import datetime, timedelta
from abc import ABC, abstractmethod
from db import SessionLocal, get_player

MIN_WAIT = int(os.getenv("EVENT_MIN_WAIT", "10"))
MAX_WAIT = int(os.getenv("EVENT_MAX_WAIT", "15"))
MIN_DUR = int(os.getenv("EVENT_MIN_DUR", "10"))
MAX_DUR = int(os.getenv("EVENT_MAX_DUR", "15"))


class BaseEvent(ABC):
    id: str
    name: str

    def __init__(self, participants: dict[int, set[int]]):
        self.participants = participants

    @abstractmethod
    def finish(self) -> dict[int, str]:
        """
        Вернуть {chat_id: текст}, который будет разослан в каждый чат.
        Метод может начислять награды игрокам.
        """


class BanEvent(BaseEvent):
    id = "ban"
    name = "Банька с Никитой"

    TEMPLATES = {
        100: [
            "{name} парился как чемпион – Никита выдал {prize} очков!",
            "🔥 {name} выдержал самый жар – +{prize} очков от Никиты.",
        ],
        60: [
            "{name} уверенно запотел, заслужив {prize} очков.",
            "Хороший заход, {name}! Никита дарит {prize} очков.",
        ],
        40: [
            "{name} писал на камни, рассмешил Никиту – {prize} очков.",
            "😂 {name} устроил шоу: Никита отсыпал {prize} очков.",
        ],
        20: [
            "{name} просто грелся в уголке и получил {prize} очков.",
            "Скромненько, {name}. Держи {prize} очков за участие.",
        ],
    }
    PRIZE_POOL = [100, 60, 40, 20]  # можно расширить

    def finish(self) -> dict[int, str]:
        result: dict[int, str] = {}

        with SessionLocal() as s:

            for chat_id, uids in self.participants.items():
                if not uids:
                    result[chat_id] = "Участников не было."
                    continue

                users = list(uids)
                random.shuffle(users)

                prizes = random.choices(self.PRIZE_POOL, k=len(users))

                lines = []
                for uid, prize in zip(users, prizes):
                    pl = get_player(s, uid, "", 0)
                    pl.balance += prize
                    phrase = random.choice(self.TEMPLATES[prize]).format(
                        name=pl.first_name, prize=prize
                    )
                    lines.append(phrase)

                s.commit()
                result[chat_id] = "\n".join(lines)

        return result


EVENT_POOL = [BanEvent]


class EventManager:
    def __init__(self, app):
        self.jq = app.job_queue
        self.curr = None
        self._schedule_next()

    def is_active_participant(self, chat_id: int, user_id: int) -> bool:
        return (
            self.curr
            and self.curr["status"] == "active"
            and user_id in self.curr["participants"].get(chat_id, set())
        )

    def join(self, chat_id: int, user_id: int, ev_id: str | None):
        if not self.curr or self.curr["status"] != "waiting":
            return False, "Регистрация закрыта."
        if ev_id and ev_id != self.curr["id"]:
            return False, "Такого ивента сейчас нет."
        self.curr["participants"].setdefault(chat_id, set()).add(user_id)
        return True, "Записан!"

    def info(self, chat_id: int) -> str:
        if not self.curr:
            return "Ивентов нет."
        if self.curr["status"] == "waiting":
            m = int((self.curr["start"] - datetime.utcnow()).total_seconds() // 60)
            return f"До начала «{self.curr['name']}» {m} мин."
        if self.curr["status"] == "active":
            m = int((self.curr["end"] - datetime.utcnow()).total_seconds() // 60)
            return f"«{self.curr['name']}» идёт, осталось {m} мин."
        return "Ивентов нет."

    def _schedule_next(self):
        wait = random.randint(MIN_WAIT, MAX_WAIT)
        ev_cls = random.choice(EVENT_POOL)
        self.curr = {
            "id": ev_cls.id,
            "name": ev_cls.name,
            "class": ev_cls,
            "status": "waiting",
            "start": datetime.utcnow() + timedelta(seconds=wait),
            "duration": None,
            "participants": {},  # chat_id → set(user_id)
        }
        self.jq.run_once(self._start, wait)

    async def _start(self, ctx):
        ev = self.curr
        ev["status"] = "active"
        dur = random.randint(MIN_DUR, MAX_DUR)
        ev["duration"] = dur
        ev["end"] = datetime.utcnow() + timedelta(seconds=dur)

        for cid in ctx.application.bot_data["chats"]:
            await ctx.bot.send_message(
                cid, f"🚀 «{ev['name']}» начался! {dur//60} мин."
            )

        ctx.job_queue.run_once(self._finish, dur)

    async def _finish(self, ctx):
        ev = self.curr
        texts = ev["class"](ev["participants"]).finish()

        for cid in ctx.application.bot_data["chats"]:
            await ctx.bot.send_message(
                cid,
                f"🏁 «{ev['name']}» завершён!\n{texts.get(cid, 'Участников не было.')}",
            )

        self.curr = None
        self._schedule_next()
