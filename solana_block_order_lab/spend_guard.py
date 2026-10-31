"""
Spend Guard for Solana Block Order Lab.
Strict mechanical circuit breaker that prevents cumulative transaction fee spending
from exceeding the user's hard cap (0.05 SOL by default).
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Dict, Any, Optional

from .config import LAMPORTS_PER_SOL, DEFAULT_SPEND_CAP_SOL

logger = logging.getLogger(__name__)


class SpendLimitExceededError(RuntimeError):
    """Raised when an operation would violate the cumulative spend cap."""
    pass


class SpendGuard:
    """Mechanical spend limiter and persistent ledger for experiment transactions."""

    def __init__(
        self,
        spend_cap_lamports: int = int(DEFAULT_SPEND_CAP_SOL * LAMPORTS_PER_SOL),
        ledger_path: Optional[Path] = None,
        dry_run: bool = True,
    ):
        self.spend_cap_lamports = spend_cap_lamports
        self.ledger_path = ledger_path or Path("./data/spend_ledger.json")
        self.dry_run = dry_run

        self._committed_lamports: int = 0
        self._confirmed_lamports: int = 0
        self._tx_records: list[Dict[str, Any]] = []

        self._load_ledger()

    @property
    def total_reserved_lamports(self) -> int:
        """Total lamports either committed (in-flight) or confirmed."""
        return self._confirmed_lamports + self._committed_lamports

    @property
    def remaining_lamports(self) -> int:
        """Remaining lamports allowance under the hard cap."""
        remaining = self.spend_cap_lamports - self.total_reserved_lamports
        return max(0, remaining)

    @property
    def remaining_sol(self) -> float:
        """Remaining SOL allowance under the hard cap."""
        return self.remaining_lamports / LAMPORTS_PER_SOL

    @property
    def confirmed_sol(self) -> float:
        """Total confirmed SOL spent so far."""
        return self._confirmed_lamports / LAMPORTS_PER_SOL

    def check_can_spend(self, estimated_lamports: int) -> None:
        """Validate whether the requested spend would breach the limit without committing it."""
        if estimated_lamports < 0:
            raise ValueError(f"Cannot spend negative lamports: {estimated_lamports}")

        potential_total = self.total_reserved_lamports + estimated_lamports
        if potential_total > self.spend_cap_lamports:
            raise SpendLimitExceededError(
                f"Spend limit breached! Current reserved: {self.total_reserved_lamports} lamports "
                f"({self.total_reserved_lamports / LAMPORTS_PER_SOL:.6f} SOL), "
                f"Requested: {estimated_lamports} lamports, "
                f"Hard cap: {self.spend_cap_lamports} lamports "
                f"({self.spend_cap_lamports / LAMPORTS_PER_SOL:.6f} SOL)."
            )

    def reserve(self, estimated_lamports: int, reason: str = "tx_intent") -> None:
        """Reserve lamports before in-flight transaction broadcast."""
        self.check_can_spend(estimated_lamports)
        self._committed_lamports += estimated_lamports
        logger.debug(
            "Reserved %d lamports for '%s'. In-flight total: %d lamports.",
            estimated_lamports,
            reason,
            self._committed_lamports,
        )

    def confirm(self, actual_lamports: int, estimated_lamports: int, tx_signature: str) -> None:
        """Confirm actual spent lamports after transaction execution."""
        self._committed_lamports = max(0, self._committed_lamports - estimated_lamports)
        self._confirmed_lamports += actual_lamports

        record = {
            "signature": tx_signature,
            "actual_lamports": actual_lamports,
            "actual_sol": actual_lamports / LAMPORTS_PER_SOL,
            "cumulative_confirmed_lamports": self._confirmed_lamports,
            "dry_run": self.dry_run,
        }
        self._tx_records.append(record)
        self._save_ledger()

        logger.info(
            "Confirmed spend: %d lamports for tx %s. Cumulative spent: %d lamports (%.6f SOL).",
            actual_lamports,
            tx_signature,
            self._confirmed_lamports,
            self.confirmed_sol,
        )

    def release(self, estimated_lamports: int, reason: str = "tx_failed") -> None:
        """Release reserved lamports if a transaction fails before inclusion."""
        self._committed_lamports = max(0, self._committed_lamports - estimated_lamports)
        logger.debug("Released %d reserved lamports due to: %s", estimated_lamports, reason)

    def _load_ledger(self) -> None:
        """Load persistent spend ledger from disk if present."""
        if not self.ledger_path.exists():
            return

        try:
            with open(self.ledger_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._confirmed_lamports = data.get("confirmed_lamports", 0)
            self._tx_records = data.get("transactions", [])
            logger.info(
                "Loaded spend ledger from %s. Total spent: %d lamports (%.6f SOL).",
                self.ledger_path,
                self._confirmed_lamports,
                self.confirmed_sol,
            )
        except Exception as e:
            logger.warning("Could not read spend ledger at %s: %s", self.ledger_path, e)

    def _save_ledger(self) -> None:
        """Persist current spend status to disk."""
        try:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            data = {
                "spend_cap_lamports": self.spend_cap_lamports,
                "spend_cap_sol": self.spend_cap_lamports / LAMPORTS_PER_SOL,
                "confirmed_lamports": self._confirmed_lamports,
                "confirmed_sol": self.confirmed_sol,
                "transactions_count": len(self._tx_records),
                "transactions": self._tx_records,
            }
            with open(self.ledger_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error("Failed to persist spend ledger to %s: %s", self.ledger_path, e)
