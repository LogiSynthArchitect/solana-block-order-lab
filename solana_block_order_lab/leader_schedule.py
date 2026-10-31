"""
Leader Schedule tracker for Solana Block Order Lab.
Interrogates Solana JSON-RPC endpoints to identify epoch slot boundaries,
fetch leader schedules, and map upcoming slots to target validator client families.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import httpx
from pydantic import BaseModel, Field

from .validator_registry import ValidatorRegistry, ValidatorIdentity, ClientFamily

logger = logging.getLogger(__name__)


class EpochInfo(BaseModel):
    """Snapshot of current Solana epoch progress."""
    epoch: int = Field(..., description="Current epoch index.")
    slot_index: int = Field(..., description="Current slot index within this epoch.")
    slots_in_epoch: int = Field(..., description="Total slots per epoch.")
    absolute_slot: int = Field(..., description="Global absolute slot number.")
    block_height: int = Field(..., description="Current block height.")
    transaction_count: Optional[int] = Field(default=None, description="Total cluster transactions.")


class LeaderSlotAssignment(BaseModel):
    """Mapping of a specific slot to its scheduled leader validator."""
    slot: int = Field(..., description="Absolute slot number.")
    leader_pubkey: str = Field(..., description="Node identity public key of the slot leader.")
    client_family: ClientFamily = Field(
        default=ClientFamily.UNKNOWN,
        description="Identified client family of the leader.",
    )
    validator_name: str = Field(default="", description="Operator name if registered.")


class LeaderScheduleTracker:
    """Fetches and tracks Solana leader schedules and slot assignments."""

    def __init__(
        self,
        rpc_url: str,
        registry: Optional[ValidatorRegistry] = None,
        timeout: float = 15.0,
    ):
        self.rpc_url = rpc_url
        self.registry = registry or ValidatorRegistry()
        self.timeout = timeout
        self._cached_epoch_info: Optional[EpochInfo] = None
        self._cached_schedule: Dict[str, List[int]] = {}  # pubkey -> relative slot offsets

    def _rpc_call(self, method: str, params: Optional[List[Any]] = None) -> Any:
        """Issue a JSON-RPC request to the configured Solana endpoint."""
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": method,
            "params": params or [],
        }
        with httpx.Client(timeout=self.timeout) as client:
            resp = client.post(self.rpc_url, json=payload)
            resp.raise_for_status()
            data = resp.json()
            if "error" in data:
                raise RuntimeError(f"Solana RPC Error ({method}): {data['error']}")
            return data.get("result")

    def get_epoch_info(self) -> EpochInfo:
        """Fetch real-time cluster epoch information."""
        res = self._rpc_call("getEpochInfo")
        self._cached_epoch_info = EpochInfo(
            epoch=res["epoch"],
            slot_index=res["slotIndex"],
            slots_in_epoch=res["slotsInEpoch"],
            absolute_slot=res["absoluteSlot"],
            block_height=res["blockHeight"],
            transaction_count=res.get("transactionCount"),
        )
        return self._cached_epoch_info

    def get_slot_leaders(self, start_slot: int, limit: int = 128) -> List[LeaderSlotAssignment]:
        """Fetch slot leaders directly via getSlotLeaders RPC method."""
        raw_leaders = self._rpc_call("getSlotLeaders", [start_slot, limit])
        assignments: List[LeaderSlotAssignment] = []

        for offset, leader_pubkey in enumerate(raw_leaders):
            slot = start_slot + offset
            val = self.registry.get(leader_pubkey)
            family = val.client_family if val else ClientFamily.UNKNOWN
            name = val.name if val else ""

            assignments.append(
                LeaderSlotAssignment(
                    slot=slot,
                    leader_pubkey=leader_pubkey,
                    client_family=family,
                    validator_name=name,
                )
            )
        return assignments

    def refresh_leader_schedule(self, target_slot: Optional[int] = None) -> Dict[str, List[int]]:
        """Fetch complete epoch leader schedule (pubkey -> relative slot offset list)."""
        params = [target_slot] if target_slot is not None else []
        schedule = self._rpc_call("getLeaderSchedule", params) or {}
        self._cached_schedule = schedule
        return schedule

    def find_upcoming_target_slots(
        self,
        target_families: Optional[List[ClientFamily]] = None,
        max_slots_ahead: int = 256,
    ) -> List[LeaderSlotAssignment]:
        """
        Scan upcoming slots from current absolute slot and return slots matching
        the requested target client families (Agave, Jito, Firedancer).
        """
        epoch_info = self.get_epoch_info()
        current_slot = epoch_info.absolute_slot
        upcoming = self.get_slot_leaders(start_slot=current_slot, limit=max_slots_ahead)

        if not target_families:
            return upcoming

        filtered = [s for s in upcoming if s.client_family in target_families]
        return filtered

    def get_cluster_nodes(self) -> List[Dict[str, Any]]:
        """Interrogate cluster nodes for dynamic client version and gossip metadata."""
        return self._rpc_call("getClusterNodes")
