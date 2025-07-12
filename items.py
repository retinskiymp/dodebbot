from __future__ import annotations

import random
from enum import IntEnum, unique
from typing import TYPE_CHECKING, Dict, List

if TYPE_CHECKING:
    from models import PlayerModel


@unique
class ItemID(IntEnum):
    LOOTBOX = 1
    PRESTIJE = 2


def _inv(player: "PlayerModel") -> Dict[str, int]:
    return player.items or {}


class Item:
    id: ItemID
    name: str
    desc: str
    price: int
    stackable: bool = True  # можно ли хранить >1

    @staticmethod
    def _assert_positive(qty: int) -> None:
        if qty < 1:
            raise ValueError("Количество должно быть положительным")

    @staticmethod
    def _change_amount(player: "PlayerModel", item_id: ItemID, delta: int) -> None:
        inv = _inv(player)
        key = str(item_id)
        new_val = inv.get(key, 0) + delta
        if new_val < 0:
            raise ValueError("Недостаточно предметов для операции")
        if new_val:
            inv[key] = new_val
        else:
            inv.pop(key, None)
        player.items = inv

    def buy(self, player: "PlayerModel", qty: int = 1) -> None:
        self._assert_positive(qty)
        if not self.stackable and qty > 1:
            raise ValueError("Этот предмет нельзя покупать пачкой")
        if not self.stackable and str(self.id) in _inv(player):
            raise ValueError("У тебя уже есть такой предмет")
        self._change_amount(player, self.id, qty)

    def use(self, player: "PlayerModel", qty: int = 1) -> str:
        raise NotImplementedError


class LootBox(Item):
    id = ItemID.LOOTBOX
    name = "🎁 Лутбокс"
    desc = (
        "Открой его и получи случайное количество монет, а может быть и еще что-то...?"
    )
    price = 100
    stackable = True

    REWARDS: List[int] = [0, 50, 100, 150, 500, 1000, 10000]
    WEIGHTS: List[float] = [39, 30, 15, 10, 3, 2, 1]

    def use(self, player: "PlayerModel", qty: int = 1) -> str:
        self._assert_positive(qty)
        self._change_amount(player, self.id, -qty)

        prizes = random.choices(self.REWARDS, weights=self.WEIGHTS, k=qty)

        total = sum(prizes)
        player.balance += total

        return f"🎁 Открыто лутбоксов: {qty}, награда {total} монет"


class PrestigeHat(Item):
    id = ItemID.PRESTIJE
    name = "👑 Престиж"
    desc = "Просто показать всем, что ты крутой, можешь купить несколько, чтобы быть ещё круче"
    price = 1000
    stackable = True

    def buy(self, player: "PlayerModel", qty: int = 1) -> None:
        self._assert_positive(qty)
        super().buy(player, qty)

    def use(self, player: "PlayerModel", qty: int = 1) -> str:
        self._assert_positive(qty)
        return "Это просто шляпа, она не даёт никаких бонусов, но выглядит круто!"


ITEMS: Dict[int, Item] = {
    ItemID.LOOTBOX: LootBox(),
    ItemID.PRESTIJE: PrestigeHat(),
}


def get_item(item_id: int) -> Item | None:
    return ITEMS.get(item_id)
