import os


START_BALANCE: int = int(os.getenv("START_BALANCE", "100"))
JACKPOT_START: int = int(os.getenv("JACKPOT_START", "0"))
DB_URL: str = os.getenv("DB_URL", "sqlite:///data.db")
TOKEN: str = os.getenv("BOT_TOKEN")
SPIN_COST: int = int(os.getenv("SPIN_COST", "2"))
JACKPOT_INCREMENT: int = int(os.getenv("JACKPOT_INCREMENT", "1"))
