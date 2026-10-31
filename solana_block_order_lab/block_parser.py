"""
Block Parser for Solana Block Order Lab.
Fetches finalized blocks via JSON-RPC, parses transaction execution order,
extracts ComputeBudget and SPL Memo data, and matches experiment batches.
"""

from __future__ import annotations

import base64
import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import httpx
from pydantic import BaseModel, Field

from .config import MEMO_PROGRAM_ID
from .validator_registry import ClientFamily

logger = logging.getLogger(__name__)

COMPUTE_BUDGET_PROGRAM_ID = "ComputeBudget111111111111111111111111111111"


class BlockTxRecord(BaseModel):
    """Execution metadata for a single transaction inside a Solana block."""
    block_index: int = Field(..., description="0-indexed position within the block.")
    slot: int = Field(..., description="Slot number of the block.")
    signature: str = Field(..., description="Transaction signature.")
    priority_fee_micro_lamports: int = Field(default=0, description="Priority fee in micro-lamports/CU.")
    compute_unit_limit: int = Field(default=200_000, description="Allocated compute unit limit.")
    compute_units_consumed: Optional[int] = Field(default=None, description="Actual CUs consumed.")
    fee_lamports: int = Field(default=5_000, description="Total fee paid in lamports.")
    memo_payload: Optional[str] = Field(default=None, description="Decoded SPL Memo text.")
    memo_timestamp_ns: Optional[int] = Field(default=None, description="Embedded nanosecond timestamp.")
    run_id: Optional[str] = Field(default=None, description="Experiment batch run ID if matched.")
    batch_idx: Optional[int] = Field(default=None, description="Batch index if matched.")
    is_experiment_tx: bool = Field(default=False, description="Whether this is our measurement tx.")
    err: Optional[Any] = Field(default=None, description="Execution error if any.")


class ParsedBlock(BaseModel):
    """Representation of a processed Solana block."""
    slot: int = Field(..., description="Block slot number.")
    blockhash: str = Field(..., description="Blockhash of the block.")
    parent_slot: int = Field(..., description="Parent slot.")
    block_time: Optional[int] = Field(default=None, description="Unix timestamp.")
    leader_pubkey: Optional[str] = Field(default=None, description="Slot leader identity.")
    client_family: ClientFamily = Field(default=ClientFamily.UNKNOWN, description="Leader client family.")
    total_transactions: int = Field(default=0, description="Total transactions in block.")
    transactions: List[BlockTxRecord] = Field(default_factory=list, description="All parsed transactions.")
    experiment_transactions: List[BlockTxRecord] = Field(
        default_factory=list, description="Matched measurement transactions."
    )


class BlockParser:
    """Parses Solana blocks to extract transaction ordering, fees, and timestamps."""

    def __init__(self, rpc_url: Optional[str] = None, timeout: float = 30.0):
        self.rpc_url = rpc_url
        self.timeout = timeout

    def fetch_block(self, slot: int) -> Dict[str, Any]:
        """Fetch block data from JSON-RPC using maxSupportedTransactionVersion: 0."""
        if not self.rpc_url:
            raise ValueError("RPC URL required to fetch blocks from network.")
        payload = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "getBlock",
            "params": [
                slot,
                {
                    "encoding": "jsonParsed",
                    "transactionDetails": "full",
                    "rewards": False,
                    "maxSupportedTransactionVersion": 0,
                    "commitment": "finalized",
                },
            ],
        }
        resp = httpx.post(self.rpc_url, json=payload, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise RuntimeError(f"RPC getBlock error for slot {slot}: {data['error']}")
        return data.get("result") or {}

    def parse_block_data(
        self,
        raw_block: Dict[str, Any],
        slot: int,
        leader_pubkey: Optional[str] = None,
        client_family: ClientFamily = ClientFamily.UNKNOWN,
        experiment_signatures: Optional[set[str]] = None,
        tag_prefix: str = "SBOL",
    ) -> ParsedBlock:
        """Parse raw block JSON into structured ParsedBlock with transaction order indexing."""
        blockhash = raw_block.get("blockhash", "")
        parent_slot = raw_block.get("parentSlot", slot - 1)
        block_time = raw_block.get("blockTime")
        raw_txs = raw_block.get("transactions", [])

        parsed_records: List[BlockTxRecord] = []
        experiment_records: List[BlockTxRecord] = []
        target_sigs = experiment_signatures or set()

        for idx, item in enumerate(raw_txs):
            rec = self._parse_single_tx(idx, slot, item, target_sigs, tag_prefix)
            parsed_records.append(rec)
            if rec.is_experiment_tx:
                experiment_records.append(rec)

        return ParsedBlock(
            slot=slot,
            blockhash=blockhash,
            parent_slot=parent_slot,
            block_time=block_time,
            leader_pubkey=leader_pubkey,
            client_family=client_family,
            total_transactions=len(parsed_records),
            transactions=parsed_records,
            experiment_transactions=experiment_records,
        )

    def _parse_single_tx(
        self,
        index: int,
        slot: int,
        tx_item: Dict[str, Any],
        target_sigs: set[str],
        tag_prefix: str,
    ) -> BlockTxRecord:
        """Parse one transaction item from the block's transaction array."""
        meta = tx_item.get("meta") or {}
        tx_data = tx_item.get("transaction") or {}
        sigs = tx_data.get("signatures", [])
        sig = sigs[0] if sigs else f"unknown_sig_{slot}_{index}"

        fee = meta.get("fee", 5000)
        cu_consumed = meta.get("computeUnitsConsumed")
        err = meta.get("err")

        cu_limit = 200_000
        priority_fee = 0
        memo_str: Optional[str] = None
        memo_ts: Optional[int] = None
        run_id: Optional[str] = None
        batch_idx: Optional[int] = None

        message = tx_data.get("message") or {}
        instructions = message.get("instructions", [])

        for ix in instructions:
            program_id = ix.get("programId", "")
            program_name = ix.get("program", "")

            # Parse Compute Budget instructions
            if program_id == COMPUTE_BUDGET_PROGRAM_ID or program_name == "compute-budget":
                parsed_ix = ix.get("parsed")
                if isinstance(parsed_ix, dict):
                    ix_type = parsed_ix.get("type")
                    info = parsed_ix.get("info", {})
                    if ix_type == "setComputeUnitPrice":
                        priority_fee = int(info.get("microLamports", 0))
                    elif ix_type == "setComputeUnitLimit":
                        cu_limit = int(info.get("units", 200_000))

            # Parse SPL Memo instructions
            if program_id == MEMO_PROGRAM_ID or program_name == "spl-memo":
                memo_parsed = ix.get("parsed")
                if isinstance(memo_parsed, str):
                    memo_str = memo_parsed
                elif isinstance(memo_parsed, dict) and "memo" in memo_parsed:
                    memo_str = str(memo_parsed["memo"])

        # Check for experiment batch tagging (SBOL:run_id:batch_idx:fee:timestamp_ns)
        is_exp = sig in target_sigs
        if memo_str and memo_str.startswith(f"{tag_prefix}:"):
            parts = memo_str.split(":")
            if len(parts) >= 5:
                run_id = parts[1]
                try:
                    batch_idx = int(parts[2])
                    priority_fee = int(parts[3])
                    memo_ts = int(parts[4])
                    is_exp = True
                except ValueError:
                    pass

        return BlockTxRecord(
            block_index=index,
            slot=slot,
            signature=sig,
            priority_fee_micro_lamports=priority_fee,
            compute_unit_limit=cu_limit,
            compute_units_consumed=cu_consumed,
            fee_lamports=fee,
            memo_payload=memo_str,
            memo_timestamp_ns=memo_ts,
            run_id=run_id,
            batch_idx=batch_idx,
            is_experiment_tx=is_exp,
            err=err,
        )

    def save_parsed_block(self, parsed: ParsedBlock, dest_dir: Path) -> Path:
        """Persist parsed block data to JSON file for offline analysis."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        file_path = dest_dir / f"block_{parsed.slot}.json"
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(parsed.model_dump_json(indent=2))
        logger.info("Saved parsed block %d to %s", parsed.slot, file_path)
        return file_path

    def load_parsed_block(self, file_path: Path) -> ParsedBlock:
        """Load previously saved parsed block JSON."""
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return ParsedBlock.model_validate(data)
