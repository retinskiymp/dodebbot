from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, scoped_session
from models import Base, PlayerModel, RoomModel
from config import START_BALANCE, JACKPOT_START, DB_URL

engine = create_engine(
    DB_URL,
    echo=False,
    future=True,
)
SessionLocal = scoped_session(sessionmaker(bind=engine, expire_on_commit=False))
Base.metadata.create_all(bind=engine)


def change_balance_f(player: "PlayerModel", amount) -> None:
    player.balance += amount


def change_balance(session, user_id, chat_id, amount):
    player = (
        session.query(PlayerModel).filter_by(tg_id=user_id, room_id=chat_id).first()
    )
    if not player:
        raise ValueError(f"Player with tg id {user_id} does not exist")
    player.balance += amount


def set_balance(session, user_id, chat_id, amount):
    player = (
        session.query(PlayerModel).filter_by(tg_id=user_id, room_id=chat_id).first()
    )
    if not player:
        raise ValueError(f"Player with tg id {user_id} does not exist")
    player.balance = amount


def get_player(session, user_id, chat_id, first_name):
    player = (
        session.query(PlayerModel).filter_by(tg_id=user_id, room_id=chat_id).first()
    )
    if not player:
        player = PlayerModel(
            tg_id=user_id, first_name=first_name, room_id=chat_id, balance=START_BALANCE
        )
        session.add(player)
        session.commit()
    return player


def get_player_by_id(session, user_id, chat_id):
    player = (
        session.query(PlayerModel).filter_by(tg_id=user_id, room_id=chat_id).first()
    )
    if not player:
        raise ValueError(f"Player with tg id {user_id} does not exist")
    return player


def get_room(session, chat_id):
    room = session.query(RoomModel).filter_by(chat_tg_id=chat_id).first()
    if not room:
        room = RoomModel(chat_tg_id=chat_id, jackpot=JACKPOT_START, events=False)
        session.add(room)
        session.commit()
    return room


def load_event_chats() -> set[int]:
    with SessionLocal() as s:
        rows = s.execute(select(RoomModel.chat_tg_id).where(RoomModel.events == True))
        return {row[0] for row in rows}


def get_jackpot(session, chat_id):
    room = get_room(session, chat_id)
    return room.jackpot
