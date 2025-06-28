from sqlalchemy import Column, Integer, String, BigInteger, Boolean
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class PlayerModel(Base):
    __tablename__ = "players"
    user_id = Column(BigInteger, primary_key=True)
    first_name = Column(String, nullable=False)
    balance = Column(Integer, default=5)


class ChatModel(Base):
    __tablename__ = "jackpots"
    chat_id = Column(BigInteger, primary_key=True)
    jackpot = Column(Integer, default=10)
    events = Column(Boolean, default=False)
