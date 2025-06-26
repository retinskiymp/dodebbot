from sqlalchemy import Column, Integer, String, BigInteger
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Player(Base):
    __tablename__ = "players"
    user_id = Column(BigInteger, primary_key=True)
    first_name = Column(String, nullable=False)
    balance = Column(Integer, default=5)


class ChatJackpot(Base):
    __tablename__ = "jackpots"
    chat_id = Column(BigInteger, primary_key=True)
    value = Column(Integer, default=10)
