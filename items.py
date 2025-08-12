from __future__ import annotations

import random
from enum import IntEnum, StrEnum, unique
from typing import TYPE_CHECKING, Dict, List, Optional, Union
from db import change_balance_f

if TYPE_CHECKING:
    from models import PlayerModel


@unique
class ItemId(StrEnum):
    Lootbox = "lootbox"
    Calculator = "calculator"
    Insurance = "insurance"
    HotCard = "hot_card"
    Escape = "escape"


@unique
class ItemIdShortName(StrEnum):
    Lootbox = "lb"
    Calculator = "calc"
    Insurance = "ins"
    HotCard = "hc"
    Escape = "esc"


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
    price = 200
    stackable = True

    # chance, min, max
    LOOT_TABLE: dict[Optional[str], tuple[int, int, int]] = {
        "coins": (30, 0, 150),
        ItemId.Escape: (25, 1, 3),
        ItemId.Insurance: (15, 1, 3),
        ItemId.Lootbox: (20, 1, 3),
        ItemId.HotCard: (10, 1, 3),
    }

    def open_lootbox(self, player: "PlayerModel", qty: int = 1) -> str:
        choices = list(self.LOOT_TABLE.keys())
        weights = [cfg[0] for cfg in self.LOOT_TABLE.values()]

        awarded: dict[str, int] = {}

        for _ in range(qty):
            picked = random.choices(choices, weights=weights, k=1)[0]
            weight, mn, mx = self.LOOT_TABLE[picked]

            if picked == "coins":
                tens_min = mn // 10
                tens_max = mx // 10
                count = random.randint(tens_min, tens_max) * 10
                if count > 0:
                    change_balance_f(player, count)
                    awarded["coins"] = awarded.get("coins", 0) + count
                continue

            if picked is None:
                continue

            count = random.randint(mn, mx)
            Item._change_amount(player, picked, count)
            awarded[picked] = awarded.get(picked, 0) + count

        if not awarded:
            return "😢 В этот раз ничего не выпало."

        lines = []
        for item_id, cnt in awarded.items():
            if item_id == "coins":
                name = "🪙 Монеты"
            else:
                item = get_item(item_id)
                name = item.name if item else str(item_id)
            lines.append(f"{name} × {cnt}")

        return f"🎁 Открыто {qty} лутбоксов\n" "🏆 Содержимое:\n" + "\n".join(
            f"— {line}" for line in lines
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


class HotCard(Item):
    id = ItemId.HotCard
    id_short_name = ItemIdShortName.HotCard
    name = "🌡️ Картоградусник"
    desc = "Узнай какого номинала несколько ближайших карт в колоде"
    price = 200

    def buy(self, player: "PlayerModel", qty: int = 1) -> str:
        return self._impossible_to_buy(self)

    def use(self, player: "PlayerModel", qty: int = 1) -> str:
        return self._impossible_to_use(self)


class Escape(Item):
    id = ItemId.Escape
    id_short_name = ItemIdShortName.Escape
    name = "🏃 Побег"
    desc = "Позволяет сбежать из игры в блэкджек, потеряв половину своей ставки"
    price = 100

    def buy(self, player: "PlayerModel", qty: int = 1) -> str:
        return self._impossible_to_buy(self)

    def use(self, player: "PlayerModel", qty: int = 1) -> str:
        return self._impossible_to_use(self)


ITEMS: Dict[str, Item] = {
    ItemId.Lootbox: LootBox(),
    ItemId.Calculator: Calculator(),
    ItemId.Insurance: Insurance(),
    ItemId.HotCard: HotCard(),
    ItemId.Escape: Escape(),
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
