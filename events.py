import os, random
from datetime import datetime, timedelta
from abc import ABC, abstractmethod
from db import SessionLocal, get_player_by_id
from items import ItemID

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
    def finish(self) -> dict[int, str]: ...


class BanEvent(BaseEvent):
    id = "ban"
    name = "Банька с Никитой"

    PRIZES = [
        (
            200,
            [
                "{name} так разошёлся с веником, что Никита заподозрил неладное {prize} очков за банный фетиш!",
                "{name} упал на каменку и теперь у него «фирменный» узор на жопе {prize} очков за брендирование!",
                "{name} случайно сел на шариковую ручку и теперь ходит с синей точкой {prize} очков за тату-мастера!",
                "{name} устроил «дождик» из таза, но забыл, что был без трусов {prize} очков за внезапный стриптиз!",
                "{name} так громко пукнул в парилке, что Никита проверил газовую плиту {prize} очков за звуковой эффект!",
                "{name} использовал веник как микрофон и спел «Банные страсти» {prize} очков за вокальный подвиг!",
                "{name} поскользнулся на мыле и принял позу «орла» {prize} очков за акробатику!",
                "{name} разогрелся до такой степени, что от него исходил пар даже на улице {prize} очков за эффект паровоза!",
                "{name} устроил соревнование «чей веник пышнее» и победил {prize} очков за банную эстетику!",
                "{name} случайно заперся в парилке и теперь его ищет МЧС {prize} очков за экстремальное выживание!",
            ],
        ),
        (
            150,
            [
                "{name} перепутал полотенце с простынёй и вышел «в платье» {prize} очков за банную моду!",
                "{name} пытался охладиться, но сел на лёд и примёрз {prize} очков за эффект «поп-мороженое»!",
                "{name} так активно парился, что его спутали с демоном {prize} очков за мистификацию!",
                "{name} забыл снять цепочку и теперь у него «выгравирован» узор {prize} очков за ювелирный эксперимент!",
                "{name} устроил «массаж» веником, но перестарался {prize} очков за садомазо!",
                "{name} решил, что баня это солярий, и загорал голышом {prize} очков за ровный загар!",
                "{name} уронил мыло и устроил шоу «поймай его попой» {prize} очков за ловкость!",
                "{name} заснул в парилке и проснулся в другом измерении {prize} очков за межпространственный прыжок!",
                "{name} пытался поддать пару, но перепутал воду с водкой {prize} очков за огненное дыхание!",
                "{name} так громко пел в душе, что соседи вызвали полицию {prize} очков за вокальный терроризм!",
            ],
        ),
        (
            100,
            [
                "{name} перепутал веник с метлой и пытался «улететь» {prize} очков за банную магию!",
                "{name} устроил «битву полотенцами» и проиграл {prize} очков за мокрое поражение!",
                "{name} пытался сделать «сальто» с полки и приземлился в таз {prize} очков за акробатику!",
                "{name} забыл, что нельзя трогать каменку, и теперь у него «автограф» {prize} очков за тактильный эксперимент!",
                "{name} решил, что баня это бар, и заказал «коктейль из пара» {prize} очков за креатив!",
                "{name} устроил «дождик» из таза, но забыл, что вода была ледяная {prize} очков за контрастный душ!",
                "{name} пытался париться в противогазе {prize} очков за атмосферу апокалипсиса!",
                "{name} разогрел баню так, что термометр взорвался {prize} очков за научный эксперимент!",
                "{name} зашёл в женское отделение «по ошибке» {prize} очков за актёрскую игру!",
                "{name} пытался поднять мыло ногами, но забыл, что не йог {prize} очков за банную акробатику!",
            ],
        ),
        (
            50,
            [
                "{name} сидел в углу и тихо парился, как монах {prize} очков за банную медитацию!",
                "{name} уронил шапку для пара в лоханку {prize} очков за мокрый головной убор!",
                "{name} перепутал берёзовый веник с дубовым {prize} очков за ботанический провал!",
                "{name} зашёл в баню в шлёпанцах и поскользнулся {prize} очков за грацию пингвина!",
                "{name} пытался охладиться, но сел на снег голой жопой {prize} очков за криотерапию!",
                "{name} заснул в предбаннике и проспал всё веселье {prize} очков за банный анабиоз!",
                "{name} перепутал свой таз с чужим {prize} очков за неловкость!",
                "{name} пытался париться в носках {prize} очков за стиль!",
                "{name} забыл полотенце и выходил «как мать родила» {prize} очков за естественность!",
                "{name} уронил мыло, но сделал вид, что так и задумано {prize} очков за актёрское мастерство!",
            ],
        ),
        (
            -20,
            [
                "{name} устроил потоп, забыв закрыть кран минус {prize} очков за подводную баню!",
                "{name} принёс в парилку лампу с аромамаслами… это был бензин минус {prize} очков за пиротехническое шоу!",
                "{name} попытался париться с кофе вместо воды минус {prize} очков за кофейный скраб!",
                "{name} уснул на верхнем полке и превратился в вяленое мясо минус {prize} очков за долгую просушку!",
                "{name} пытался поддать пару, но перепутал воду с уксусом минус {prize} очков за химическую атаку!",
                "{name} устроил драку вениками и проиграл минус {prize} очков за поражение!",
                "{name} зашёл в баню в обуви и оставил следы минус {prize} очков за антисанитарию!",
                "{name} пытался париться с телефоном минус {prize} очков за техногенную глупость!",
                "{name} кричал «ЖАРКО!», когда все уже вышли минус {prize} очков за медленную реакцию!",
            ],
        ),
    ]

    def finish(self) -> dict[int, str]:
        result: dict[int, str] = {}

        prize_pool = [p for p, _ in self.PRIZES]
        templates = {p: t for p, t in self.PRIZES}
        min_pos = min(p for p in prize_pool if p > 0)

        with SessionLocal() as s:
            for chat_id, uids in self.participants.items():
                if not uids:
                    result[chat_id] = "Участников не было."
                    continue

                users = list(uids)
                random.shuffle(users)
                prizes = random.choices(prize_pool, k=len(users))

                lines: list[str] = []
                for uid, prize in zip(users, prizes):
                    pl = get_player_by_id(s, uid, chat_id)

                    if pl.balance <= 20:
                        pity = 100
                        pl.balance += pity
                        lines.append(
                            f"Никите стало жаль {pl.first_name}: он пришёл даже без "
                            f"трусиков, поэтому Никита просто так дал {pity} очков."
                        )
                        continue

                    inv = pl.items or {}
                    has_hat = str(ItemID.SAUNA_HAT) in inv
                    bonus = 30 if has_hat else 0

                    new_balance = pl.balance + prize + bonus
                    if new_balance < 0:
                        prize = min_pos
                        new_balance = pl.balance + prize + bonus

                    pl.balance = new_balance

                    phrase = random.choice(templates[prize]).format(
                        name=pl.first_name, prize=prize
                    )
                    if has_hat:
                        phrase += f" (+{bonus} очков за шапочку Никита доволен!)"
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

        already_registered = any(
            user_id in users for users in self.curr["participants"].values()
        )
        if already_registered:
            return False, "Уже зарегистрирован в этом ивенте"

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
        return "Видимо ивент сейчас выбирается..."

    async def _schedule_next(self, ctx=None):
        try:
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
        except Exception as e:
            print(f"Error in event scheduling: {e}")
            self.curr = None
            self.next_start = datetime.utcnow() + timedelta(seconds=MIN_WAIT)
            self.jq.run_once(self._schedule_next, MIN_WAIT)

    async def _start(self, ctx):
        try:
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
        except Exception as e:
            print(f"Error in event start: {e}")
            self.curr = None
            self.next_start = datetime.utcnow() + timedelta(seconds=MIN_WAIT)
            self.jq.run_once(self._schedule_next, MIN_WAIT)

    async def _finish(self, ctx):
        try:
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
        except Exception as e:
            print(f"Error in event finish: {e}")
            self.curr = None
            self.next_start = datetime.utcnow() + timedelta(seconds=MIN_WAIT)
            self.jq.run_once(self._schedule_next, MIN_WAIT)
