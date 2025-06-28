import os, random
from datetime import datetime, timedelta
from abc import ABC, abstractmethod
from db import SessionLocal, get_player

# Все интервалы в СЕКУНДАХ
MIN_WAIT = int(os.getenv("EVENT_MIN_WAIT", "10"))  # 10 мин → 600 с
MAX_WAIT = int(os.getenv("EVENT_MAX_WAIT", "10"))
MIN_DUR = int(os.getenv("EVENT_MIN_DUR", "10"))
MAX_DUR = int(os.getenv("EVENT_MAX_DUR", "10"))
MIN_GAP = int(os.getenv("EVENT_GAP_MIN", "10"))
MAX_GAP = int(os.getenv("EVENT_GAP_MAX", "10"))


def fmt(sec: int) -> str:
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    parts = []
    if h:
        parts.append(f"{h} ч")
    if m:
        parts.append(f"{m} мин")
    if not parts:
        parts.append(f"{s} сек")
    return " ".join(parts)


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
        self.next_start: datetime | None = None
        gap_sec = random.randint(MIN_GAP, MAX_GAP)
        self.next_start = datetime.utcnow() + timedelta(seconds=gap_sec)
        self.jq.run_once(self._schedule_next, gap_sec)

    def is_active_participant(self, chat_id: int, user_id: int) -> bool:
        return (
            self.curr
            and self.curr["status"] == "active"
            and user_id in self.curr["participants"].get(chat_id, set())
        )

    def join(
        self, chat_id: int, user_id: int, ev_id: str | None, user_name: str
    ) -> tuple[bool, str]:
        if not self.curr or self.curr["status"] != "waiting":
            return False, "Регистрация закрыта"
        if ev_id and ev_id != self.curr["id"]:
            return False, "Такого ивента сейчас нет"
        if user_id in self.curr["participants"].get(chat_id, set()):
            return False, "Ты уже зарегистрирован в этом ивенте"

        self.curr["participants"].setdefault(chat_id, set()).add(user_id)
        return True, f"Удачи, {user_name}, в участии в «{self.curr['name']}»!"

    def info(self) -> str:
        if self.curr:
            if self.curr["status"] == "waiting":
                s = int((self.curr["start"] - datetime.utcnow()).total_seconds())
                return f"До начала «{self.curr['name']}» {fmt(s)}."
            if self.curr["status"] == "active":
                s = int((self.curr["end"] - datetime.utcnow()).total_seconds())
                return f"«{self.curr['name']}» идёт, осталось {fmt(s)}."
        else:
            if self.next_start:
                s = int((self.next_start - datetime.utcnow()).total_seconds())
                if s > 0:
                    return f"Новый ивент через {fmt(s)}."
        return "если вы видите это сообщение, то разраб долбаеб"

    async def _schedule_next(self, ctx=None):
        wait_sec = random.randint(MIN_WAIT, MAX_WAIT)

        ev_cls = random.choice(EVENT_POOL)
        self.curr = {
            "id": ev_cls.id,
            "name": ev_cls.name,
            "class": ev_cls,
            "status": "waiting",
            "start": datetime.utcnow() + timedelta(seconds=wait_sec),
            "duration": None,
            "participants": {},
        }
        self.next_start = None
        self.jq.run_once(self._start, wait_sec)

    async def _start(self, ctx):
        ev = self.curr
        ev["status"] = "active"

        dur_sec = random.randint(MIN_DUR, MAX_DUR)
        ev["duration"] = dur_sec
        ev["end"] = datetime.utcnow() + timedelta(seconds=dur_sec)

        for cid, users in ev["participants"].items():
            if not users:
                continue
            await ctx.bot.send_message(
                cid, f"🚀 «{ev['name']}» начался! {fmt(dur_sec)}."
            )

        self.jq.run_once(self._finish, dur_sec)

    async def _finish(self, ctx):
        ev = self.curr
        texts = ev["class"](ev["participants"]).finish()

        for cid, users in ev["participants"].items():
            if not users:
                continue
            await ctx.bot.send_message(
                cid, f"🏁 «{ev['name']}» завершён!\n{texts[cid]}"
            )

        ev["participants"].clear()
        self.curr = None

        gap_sec = random.randint(MIN_GAP, MAX_GAP)
        self.next_start = datetime.utcnow() + timedelta(seconds=gap_sec)
        self.jq.run_once(self._schedule_next, gap_sec)
