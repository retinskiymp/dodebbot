from __future__ import annotations

import random
from enum import IntEnum, StrEnum, unique
from typing import TYPE_CHECKING, Dict, List, Optional, Union

if TYPE_CHECKING:
    from models import PlayerModel


@unique
class ItemId(StrEnum):
    Lootbox = "lootbox"
    BlackJackLootbox = "bjlootbox"
    Calculator = "calculator"
    Insurance = "insurance"


@unique
class ItemIdShortName(StrEnum):
    Lootbox = "lb"
    BlackJackLootbox = "bjlb"
    Calculator = "calc"
    Insurance = "ins"


def _inv(player: "PlayerModel") -> Dict[str, int]:
    return player.items or {}


class Item:
    id: str
    id_short_name: str
    name: str
    desc: str
    price: int

    @staticmethod
    def _assert_positive(qty: int) -> None:
        if qty < 1:
            raise ValueError("Количество должно быть положительным")

    @staticmethod
    def _purchase(player: "PlayerModel", item: Item, qty: int = 1) -> None:
        total_cost = item.price * qty
        player.balance -= total_cost

    @staticmethod
    def _player_has_item(player: "PlayerModel", item: Item) -> bool:
        inv = _inv(player)
        return inv.get(str(item.id), 0) > 0

    @staticmethod
    def _possible_have_only_one(player: "PlayerModel", item: Item) -> None:
        if Item._player_has_item(player, item):
            raise ValueError(f"Невозможно иметь более одного {item.name} ({item.id})")

    @staticmethod
    def _impossible_to_use(item: Item) -> str:
        return f"Невозможно использовать {item.name} ({item.id})"

    @staticmethod
    def _impossible_to_buy(item: Item) -> str:
        return f"Невозможно купить {item.name} ({item.id})"

    @staticmethod
    def _change_amount(player: "PlayerModel", item_id_name: ItemId, delta: int) -> None:
        inv = _inv(player)
        key = str(item_id_name)
        new_val = inv.get(key, 0) + delta
        if new_val < 0:
            raise ValueError("Недостаточно предметов для операции")
        if new_val:
            inv[key] = new_val
        else:
            inv.pop(key, None)
        player.items = inv

    def buy(self, player: "PlayerModel", qty: int = 1) -> str:
        raise NotImplementedError

    def use(self, player: "PlayerModel", qty: int = 1) -> str:
        raise NotImplementedError


class LootBox(Item):
    id = ItemId.Lootbox
    id_short_name = ItemIdShortName.Lootbox
    name = "🎁 Лутбокс монет"
    desc = "Открой его и получи случайное количество монет"
    price = 100
    stackable = True

    REWARDS: List[int] = [0, 50, 100, 150, 500, 1000, 5500]
    WEIGHTS: List[float] = [
        26.6667,  # 0 монет   → ~26.67%
        26.6667,  # 50 монет   → ~26.67%
        26.6667,  # 100 монет  → ~26.67%
        13.1148,  # 150 монет  → ~13.11%
        6.5574,  # 500 монет  → ~6.56%
        0.2623,  # 1000 монет → ~0.26%
        0.0656,  # 5500 монет→ ~0.07%
    ]

    def buy(self, player: "PlayerModel", qty: int = 1) -> str:
        self._assert_positive(qty)

        balance_before = player.balance
        self._purchase(player, self, qty)
        prizes = random.choices(self.REWARDS, weights=self.WEIGHTS, k=qty)
        total = sum(prizes)
        player.balance += total
        profit = player.balance - balance_before
        profit_sign = "+" if profit > 0 else ""

        return (
            f"🎁 Открыто лутбоксов: {qty}\n"
            f"💰 Всего получено: {total} монет\n"
            f"🏦 {profit_sign}{profit} монет к балансу"
        )

    def use(self, player: "PlayerModel", qty: int = 1) -> str:
        self._impossible_to_use(self)


class Calculator(Item):
    id = ItemId.Calculator
    id_short_name = ItemIdShortName.Calculator
    name = "📱 Калькулятор"
    desc = "Автоматически cчитает карты на твоей руке за столом в blackjack, возможно иметь только один калькулятор"
    price = 500

    def buy(self, player: "PlayerModel", qty: int = 1) -> str:
        self._possible_have_only_one(player, self)
        self._purchase(player, self, 1)
        self._change_amount(player, ItemId.Calculator, 1)
        return f"✅ Куплен {self.name}!"

    def use(self, player: "PlayerModel", qty: int = 1) -> str:
        self._impossible_to_use(self)


class Insurance(Item):
    id = ItemId.Insurance
    id_short_name = ItemIdShortName.Insurance
    name = "🛡 Талончик-страховка"
    desc = "Позволяет застраховать свою ставку в blackjack, если у дилера туз первой картой"
    price = 50

    def buy(self, player: "PlayerModel", qty: int = 1) -> str:
        self._impossible_to_buy(self)

    def use(self, player: "PlayerModel", qty: int = 1) -> str:
        self._impossible_to_use(self)


class BlackJackLootBox(Item):
    id = ItemId.BlackJackLootbox
    id_short_name = ItemIdShortName.BlackJackLootbox
    name = "♠️ Blackjack лутбокс"
    desc = "Открой его и получи случайный предмет для blackjack"
    price = 300

    # chance, min, max
    LOOT_TABLE: dict[Optional[str], tuple[int, int, int]] = {
        None: (50, 0, 0),
        ItemId.Insurance: (50, 1, 2),
    }

    def buy(self, player: "PlayerModel", qty: int = 1) -> str:
        self._assert_positive(qty)
        self._purchase(player, self, qty)

        choices: list[Optional[str]] = list(self.LOOT_TABLE.keys())
        weights = [cfg[0] for cfg in self.LOOT_TABLE.values()]

        awarded: dict[str, int] = {}

        for _ in range(qty):
            picked: Optional[str] = random.choices(choices, weights=weights, k=1)[0]
            weight, mn, mx = self.LOOT_TABLE[picked]
            if picked is None:
                continue

            count = random.randint(mn, mx)
            Item._change_amount(player, picked, count)
            awarded[picked] = awarded.get(picked, 0) + count

        if not awarded:
            return "😢 В этот раз ничего не выпало."

        lines = []
        for item_id, cnt in awarded.items():
            item = get_item(item_id)
            name = item.name if item else item_id
            lines.append(f"{name} × {cnt}")

        return (
            f"🎲 Открыто {qty} Blackjack-лутбоксов\n"
            "🎁 В них выпало:\n" + "\n".join(f"— {line}" for line in lines)
        )

    def use(self, player: "PlayerModel", qty: int = 1) -> str:
        self._impossible_to_use(self)


ITEMS: Dict[str, Item] = {
    ItemId.Lootbox: LootBox(),
    ItemId.BlackJackLootbox: BlackJackLootBox(),
    ItemId.Calculator: Calculator(),
    ItemId.Insurance: Insurance(),
}

SHOP_ITEMS: Dict[str, Item] = {
    ItemId.Lootbox: LootBox(),
    ItemId.BlackJackLootbox: BlackJackLootBox(),
    ItemId.Calculator: Calculator(),
}


def get_item(item_id: str) -> Item | None:
    for item in ITEMS.values():
        if item.id == item_id or item.id_short_name == item_id:
            return item


def get_shop_item(item_id: str) -> Item | None:
    for item in SHOP_ITEMS.values():
        if item.id == item_id or item.id_short_name == item_id:
            return item


def player_has_item(player: "PlayerModel", item_id: str) -> bool:
    item = get_item(item_id)
    if not item:
        return False
    return Item._player_has_item(player, item)


def change_item_amount(player: "PlayerModel", item_id: str, delta: int) -> None:
    item = get_item(item_id)
    if not item:
        raise ValueError(f"Предмет с id {item_id} не найден")
    Item._change_amount(player, item.id, delta)
