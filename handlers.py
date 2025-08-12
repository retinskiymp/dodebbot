from dataclasses import dataclass
from typing import Iterable, List, Optional, Tuple, Union

ShortType = Union[str, Tuple[str, ...]]


@dataclass(frozen=True)
class CommandAliases:
    long: str
    short: ShortType

    def __iter__(self) -> Iterable[str]:
        yield self.long
        if self.short:
            if isinstance(self.short, tuple):
                for s in self.short:
                    yield s
            else:
                yield self.short

    def as_list(self) -> List[str]:
        return list(self)


HandlerBlackJack = CommandAliases(long="blackjack", short="bj")
HandlerStatus = CommandAliases(long="status", short="st")
HandlerTop = CommandAliases(long="top", short="t")
HandlerHelp = CommandAliases(long="help", short="h")
HandlerShop = CommandAliases(long="shop", short="sh")
HandlerBuy = CommandAliases(long="buy", short="b")
HandlerUse = CommandAliases(long="use", short="u")
HandlerWiki = CommandAliases(long="wiki", short=("w"))
