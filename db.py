import os
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker, scoped_session
from models import Base, Player, ChatJackpot

engine = create_engine(
    os.getenv("DB_URL", "sqlite:///data.db"),
    echo=False,
    future=True,
)
SessionLocal = scoped_session(sessionmaker(bind=engine, expire_on_commit=False))
Base.metadata.create_all(bind=engine)


def get_player(session, user_id, first_name, start_balance):
    player = session.get(Player, user_id)
    if not player:
        player = Player(user_id=user_id, first_name=first_name, balance=start_balance)
        session.add(player)
        session.commit()
    return player


def get_jackpot(session, chat_id):
    jp = session.get(ChatJackpot, chat_id)
    if not jp:
        jp = ChatJackpot(chat_id=chat_id, value=0)
        session.add(jp)
        session.commit()
    return jp
