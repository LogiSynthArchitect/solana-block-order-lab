"""
Transaction Builder for Solana Block Order Lab.
Constructs controlled micro-transaction batches with parameterized priority fees,
compute unit limits, and precision SPL Memo timestamps for landing order analysis.
"""

from __future__ import annotations

import time
import uuid
from typing import List, Optional
from pydantic import BaseModel, Field

from solders.keypair import Keypair
from solders.pubkey import Pubkey
from solders.instruction import Instruction, AccountMeta
from solders.message import MessageV0
from solders.transaction import VersionedTransaction
from solders.hash import Hash
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price

from .spend_guard import SpendGuard
from .config import MEMO_PROGRAM_ID


class MicroTxRecord(BaseModel):
    """Metadata representing a single controlled measurement transaction."""
    tx_id: str = Field(..., description="Unique client-side transaction identifier.")
    run_id: str = Field(..., description="Experiment run batch identifier.")
    priority_fee_micro_lamports: int = Field(..., description="Compute budget priority fee rate.")
    compute_unit_limit: int = Field(..., description="Requested compute unit limit.")
    timestamp_ns: int = Field(..., description="Local timestamp in nanoseconds when built.")
    memo_payload: str = Field(..., description="Exact SPL Memo string injected.")
    estimated_fee_lamports: int = Field(..., description="Estimated cost in lamports.")
    signature: Optional[str] = Field(default=None, description="Transaction signature once signed.")
    wire_transaction_b64: Optional[str] = Field(default=None, description="Base64 wire payload.")


class MicroTxBatchBuilder:
    """Builds batches of controlled micro-transactions across fee and compute tiers."""

    def __init__(
        self,
        spend_guard: SpendGuard,
        memo_program_id: str = MEMO_PROGRAM_ID,
        signer_keypair: Optional[Keypair] = None,
    ):
        self.spend_guard = spend_guard
        self.memo_pubkey = Pubkey.from_string(memo_program_id)
        self.signer = signer_keypair or Keypair()  # Generates ephemeral keypair for dry-runs if None

    def create_memo_instruction(self, memo_text: str) -> Instruction:
        """Create an SPL Memo v2 instruction."""
        data = memo_text.encode("utf-8")
        accounts = [AccountMeta(pubkey=self.signer.pubkey(), is_signer=True, is_writable=True)]
        return Instruction(
            program_id=self.memo_pubkey,
            accounts=accounts,
            data=data,
        )

    def estimate_fee_lamports(self, priority_fee_micro_lamports: int, cu_limit: int) -> int:
        """
        Estimate the total transaction fee in lamports:
        Base signature fee (5,000 lamports) + (cu_limit * priority_fee / 1,000,000)
        """
        base_fee = 5_000
        priority_fee_lamports = (cu_limit * priority_fee_micro_lamports) // 1_000_000
        return base_fee + priority_fee_lamports

    def build_transaction(
        self,
        run_id: str,
        batch_idx: int,
        priority_fee_micro_lamports: int,
        compute_unit_limit: int,
        recent_blockhash: Hash,
    ) -> tuple[VersionedTransaction, MicroTxRecord]:
        """
        Assemble and sign a versioned transaction containing:
        1. SetComputeUnitLimit instruction
        2. SetComputeUnitPrice instruction (if > 0)
        3. SPL Memo instruction with precise timestamp
        """
        timestamp_ns = time.time_ns()
        memo_payload = f"SBOL:{run_id}:{batch_idx}:{priority_fee_micro_lamports}:{timestamp_ns}"

        estimated_fee = self.estimate_fee_lamports(priority_fee_micro_lamports, compute_unit_limit)

        # Enforce mechanical spend guard before signing
        self.spend_guard.check_can_spend(estimated_fee)

        instructions: List[Instruction] = [
            set_compute_unit_limit(compute_unit_limit),
        ]
        if priority_fee_micro_lamports > 0:
            instructions.append(set_compute_unit_price(priority_fee_micro_lamports))

        instructions.append(self.create_memo_instruction(memo_payload))

        # Build V0 transaction message
        msg = MessageV0.try_compile(
            payer=self.signer.pubkey(),
            instructions=instructions,
            address_lookup_table_accounts=[],
            recent_blockhash=recent_blockhash,
        )
        tx = VersionedTransaction(msg, [self.signer])
        sig = str(tx.signatures[0])

        record = MicroTxRecord(
            tx_id=str(uuid.uuid4()),
            run_id=run_id,
            priority_fee_micro_lamports=priority_fee_micro_lamports,
            compute_unit_limit=compute_unit_limit,
            timestamp_ns=timestamp_ns,
            memo_payload=memo_payload,
            estimated_fee_lamports=estimated_fee,
            signature=sig,
        )

        return tx, record

    def build_batch(
        self,
        fee_tiers: List[int],
        cu_limits: List[int],
        recent_blockhash: Hash,
        run_id: Optional[str] = None,
    ) -> List[tuple[VersionedTransaction, MicroTxRecord]]:
        """Generate a complete test suite batch across all permutations of fee and CU limits."""
        batch_run_id = run_id or uuid.uuid4().hex[:8]
        tx_pairs: List[tuple[VersionedTransaction, MicroTxRecord]] = []
        idx = 0

        for fee in fee_tiers:
            for cu in cu_limits:
                tx, record = self.build_transaction(
                    run_id=batch_run_id,
                    batch_idx=idx,
                    priority_fee_micro_lamports=fee,
                    compute_unit_limit=cu,
                    recent_blockhash=recent_blockhash,
                )
                tx_pairs.append((tx, record))
                idx += 1

        return tx_pairs
