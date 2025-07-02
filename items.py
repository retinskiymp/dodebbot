from __future__ import annotations

import random
from enum import IntEnum, unique
from typing import TYPE_CHECKING, Dict

if TYPE_CHECKING:
    from models import PlayerModel


@unique
class ItemID(IntEnum):
    LOOTBOX = 1
    SAUNA_HAT = 2


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

    REWARD_MIN = 50
    REWARD_MAX = 140

    def use(self, player: "PlayerModel", qty: int = 1) -> str:
        self._assert_positive(qty)
        self._change_amount(player, self.id, -qty)
        total = sum(
            random.randint(self.REWARD_MIN, self.REWARD_MAX) for _ in range(qty)
        )
        player.balance += total
        return f"🎁 Открыто боксов: {qty}, награда {total} монет"


class SaunaHat(Item):
    id = ItemID.SAUNA_HAT
    name = "🎩 Шапочка для бани"
    desc = "Никите нравятся ответственные люди, а ты ведь ответственный, да? Поди защитит тебя от неприятных последствий баньки"
    price = 500
    stackable = False

    def buy(self, player: "PlayerModel", qty: int = 1) -> None:
        self._assert_positive(qty)
        super().buy(player, 1)

    def use(self, player: "PlayerModel", qty: int = 1) -> str:
        self._assert_positive(qty)
        return "Не волнуйся, она всегда с тобой, просто иди в баньку"


ITEMS: Dict[int, Item] = {
    ItemID.LOOTBOX: LootBox(),
    ItemID.SAUNA_HAT: SaunaHat(),
}


def get_item(item_id: int) -> Item | None:
    return ITEMS.get(item_id)
