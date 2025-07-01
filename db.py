import os
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, scoped_session
from models import Base, PlayerModel, ChatModel

START_BALANCE: int = int(os.getenv("START_BALANCE", "100"))

engine = create_engine(
    os.getenv("DB_URL", "sqlite:///data.db"),
    echo=False,
    future=True,
)
SessionLocal = scoped_session(sessionmaker(bind=engine, expire_on_commit=False))
Base.metadata.create_all(bind=engine)


def get_player(session, user_id, first_name):
    player = session.query(PlayerModel).filter_by(tg_id=user_id).first()
    if not player:
        player = PlayerModel(
            tg_id=user_id, first_name=first_name, balance=START_BALANCE
        )
        session.add(player)
        session.commit()
    return player


def get_player_by_id(session, user_id):
    player = session.query(PlayerModel).filter_by(tg_id=user_id).first()
    if not player:
        raise ValueError(f"Player with tg id {user_id} does not exist")
    return player


def get_chat(session, chat_id):
    chat = session.get(ChatModel, chat_id)
    if not chat:
        chat = ChatModel(chat_id=chat_id)
        session.add(chat)
        session.commit()
    return chat


def load_event_chats() -> set[int]:
    with SessionLocal() as s:
        rows = s.execute(select(ChatModel.chat_id).where(ChatModel.events == True))
        return {row[0] for row in rows}


def get_jackpot(session, chat_id, default_jackpot=0):
    jp = session.get(ChatModel, chat_id)
    if not jp:
        jp = ChatModel(chat_id=chat_id, jackpot=default_jackpot)
        session.add(jp)
        session.commit()
    return jp
