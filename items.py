from __future__ import annotations

import random
from enum import IntEnum, StrEnum, unique
from typing import TYPE_CHECKING, Dict, List, Optional, Union

if TYPE_CHECKING:
    from models import PlayerModel


@unique
class ItemId(StrEnum):
    Lootbox = "lootbox"
    Calculator = "calculator"
    Insurance = "insurance"


@unique
class ItemIdShortName(StrEnum):
    Lootbox = "lb"
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
    def _player_has_item(player: "PlayerModel", item: Item, qty: int = 1) -> bool:
        inv = _inv(player)
        return inv.get(str(item.id), 0) >= qty

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
    name = "🎁 Лутбокс"
    desc = "Содержит случайные предметы и монеты"
    price = 300
    stackable = True

    # chance, min, max
    LOOT_TABLE: dict[Optional[str], tuple[int, int, int]] = {
        None: (50, 0, 0),
        ItemId.Insurance: (50, 1, 2),
    }

    def open_lootbox(self, player: "PlayerModel", qty: int = 1) -> str:
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

    def buy(self, player: "PlayerModel", qty: int = 1) -> str:
        self._assert_positive(qty)
        self._purchase(player, self, qty)
        return self.open_lootbox(player, qty)

    def use(self, player: "PlayerModel", qty: int = 1) -> str:
        self._assert_positive(qty)
        self._change_amount(player, self.id, -qty)
        return self.open_lootbox(player, qty)


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
        return self._impossible_to_use(self)


class Insurance(Item):
    id = ItemId.Insurance
    id_short_name = ItemIdShortName.Insurance
    name = "🛡 Талончик-страховка"
    desc = "Позволяет застраховать свою ставку в blackjack, если у дилера туз первой картой"
    price = 50

    def buy(self, player: "PlayerModel", qty: int = 1) -> str:
        return self._impossible_to_buy(self)

    def use(self, player: "PlayerModel", qty: int = 1) -> str:
        return self._impossible_to_use(self)


ITEMS: Dict[str, Item] = {
    ItemId.Lootbox: LootBox(),
    ItemId.Calculator: Calculator(),
    ItemId.Insurance: Insurance(),
}

SHOP_ITEMS: Dict[str, Item] = {
    ItemId.Lootbox: LootBox(),
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


def player_has_item(player: "PlayerModel", item_id: str, qty: int = 1) -> bool:
    item = get_item(item_id)
    if not item:
        return False
    return Item._player_has_item(player, item, qty)


def change_item_amount(player: "PlayerModel", item_id: str, delta: int) -> None:
    item = get_item(item_id)
    if not item:
        raise ValueError(f"Предмет с id {item_id} не найден")
    Item._change_amount(player, item.id, delta)
