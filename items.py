from __future__ import annotations

import random
from enum import IntEnum, StrEnum, unique
from typing import TYPE_CHECKING, Dict, List

if TYPE_CHECKING:
    from models import PlayerModel


@unique
class ItemIdName(StrEnum):
    Lootbox = "lootbox"


@unique
class ItemIdShortName(StrEnum):
    Lootbox = "lb"


def _inv(player: "PlayerModel") -> Dict[str, int]:
    return player.items or {}


class Item:
    id_name: str
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
    def _impossible_to_use(item: Item) -> str:
        return f"Невозможно использовать {item.name} ({item.id_name})"

    @staticmethod
    def _change_amount(
        player: "PlayerModel", item_id_name: ItemIdName, delta: int
    ) -> None:
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
        # self._assert_positive(qty)
        # if not self.stackable and qty > 1:
        #     raise ValueError("Этот предмет нельзя покупать пачкой")
        # if not self.stackable and str(self.id) in _inv(player):
        #     raise ValueError("У тебя уже есть такой предмет")
        # self._change_amount(player, self.id, qty)

    def use(self, player: "PlayerModel", qty: int = 1) -> str:
        raise NotImplementedError


class LootBox(Item):
    id_name = "lootbox"
    id_short_name = "lb"
    name = "🎁 Лутбокс"
    desc = (
        "Открой его и получи случайное количество монет, а может быть и еще что-то...?"
    )
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


ITEMS: Dict[str, Item] = {
    ItemIdName.Lootbox: LootBox(),
}

SHOP_ITEMS: Dict[str, Item] = {
    ItemIdName.Lootbox: LootBox(),
}


def get_item(item_id: str) -> Item | None:
    for item in ITEMS.values():
        if item.id_name == item_id or item.id_short_name == item_id:
            return item
