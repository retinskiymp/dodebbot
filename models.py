from sqlalchemy import Column, Integer, String, BigInteger, Boolean, JSON
from sqlalchemy.orm import declarative_base
from sqlalchemy.ext.mutable import MutableDict

Base = declarative_base()


class PlayerModel(Base):
    __tablename__ = "players"
    id = Column(Integer, primary_key=True, autoincrement=True)
    tg_id = Column(BigInteger, nullable=False, index=True)
    room_id = Column(Integer, nullable=False, index=True)
    first_name = Column(String, nullable=False)
    balance = Column(Integer, default=5)
    items = Column(MutableDict.as_mutable(JSON), default=dict)


class RoomModel(Base):
    __tablename__ = "room"
    id = Column(Integer, primary_key=True, autoincrement=True)
    chat_tg_id = Column(BigInteger, unique=True, nullable=False, index=True)
    jackpot = Column(Integer, default=10)
    events = Column(Boolean, default=False)
