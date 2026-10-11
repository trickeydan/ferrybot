from ferrybot.modules.module import Module

from .ferry import FerryModule
from .pub import PubModule

MODULES = [FerryModule, PubModule]

__all__ = ["MODULES", "Module"]
