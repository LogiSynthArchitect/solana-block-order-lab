"""
solana_block_order_lab
Inside the Block: How Solana Validators Order Transactions
A scientific measurement lab for transaction ordering across Agave, Jito, and Firedancer clients.
"""

__version__ = "0.1.0"

from .config import LabConfig
from .spend_guard import SpendGuard, SpendLimitExceededError
from .validator_registry import ClientFamily, ValidatorIdentity, ValidatorRegistry
from .leader_schedule import LeaderScheduleTracker
from .tx_builder import MicroTxBatchBuilder, MicroTxRecord
from .block_parser import BlockParser, BlockTxRecord, ParsedBlock
from .analyzer import BlockOrderAnalyzer, OrderingAnalysisResult

__all__ = [
    "LabConfig",
    "SpendGuard",
    "SpendLimitExceededError",
    "ClientFamily",
    "ValidatorIdentity",
    "ValidatorRegistry",
    "LeaderScheduleTracker",
    "MicroTxBatchBuilder",
    "MicroTxRecord",
    "BlockParser",
    "BlockTxRecord",
    "ParsedBlock",
    "BlockOrderAnalyzer",
    "OrderingAnalysisResult",
]
