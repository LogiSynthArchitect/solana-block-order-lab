"""
Configuration management for Solana Block Order Lab.
Handles environment variables, RPC endpoints, and spend cap safety policies.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import List, Optional
from pydantic import BaseModel, Field

LAMPORTS_PER_SOL: int = 1_000_000_000
DEFAULT_SPEND_CAP_SOL: float = 0.05
MEMO_PROGRAM_ID: str = "MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr"
DEFAULT_RPC_URL: str = "https://api.mainnet-beta.solana.com"


class LabConfig(BaseModel):
    """Configuration settings for the Solana Block Order Lab."""

    rpc_url: str = Field(
        default=DEFAULT_RPC_URL,
        description="Solana JSON-RPC endpoint URL (e.g., QuickNode, Helius, or public).",
    )
    ws_url: Optional[str] = Field(
        default=None,
        description="Optional Solana WebSocket endpoint for live slot subscriptions.",
    )
    dry_run: bool = Field(
        default=True,
        description="Enforces simulation mode without broadcasting transactions or spending real SOL.",
    )
    spend_cap_sol: float = Field(
        default=DEFAULT_SPEND_CAP_SOL,
        ge=0.0,
        le=1.0,
        description="Strict hard safety cap in SOL for experiment transactions (default 0.05 SOL).",
    )
    keypair_path: Optional[str] = Field(
        default=None,
        description="Path to Solana keypair JSON file. Required if dry_run=False.",
    )
    memo_program_id: str = Field(
        default=MEMO_PROGRAM_ID,
        description="SPL Memo program public key for precision timestamping and batch tagging.",
    )
    priority_fee_tiers: List[int] = Field(
        default_factory=lambda: [0, 1000, 5000, 20000],
        description="Controlled test priority fee levels in micro-lamports per compute unit.",
    )
    compute_unit_limits: List[int] = Field(
        default_factory=lambda: [1000, 5000, 50000],
        description="Requested compute unit limits across test transaction batches.",
    )
    experiment_tag_prefix: str = Field(
        default="SBOL",
        description="Unique prefix injected into SPL Memo payloads for tracking.",
    )
    max_slots_scan: int = Field(
        default=256,
        description="Maximum slots to scan or inspect per experiment iteration.",
    )
    output_dir: Path = Field(
        default=Path("./data"),
        description="Directory for persisting raw block JSONs, transaction ledgers, and metrics.",
    )

    @property
    def spend_cap_lamports(self) -> int:
        """Derived spend cap in lamports."""
        return int(self.spend_cap_sol * LAMPORTS_PER_SOL)

    @classmethod
    def from_env(cls) -> LabConfig:
        """Instantiate configuration from environment variables with safe defaults."""
        dry_run_env = os.getenv("SOLANA_DRY_RUN", "true").strip().lower()
        dry_run = dry_run_env in ("1", "true", "yes", "on")

        spend_cap_str = os.getenv("SOLANA_SPEND_CAP_SOL", str(DEFAULT_SPEND_CAP_SOL))
        try:
            spend_cap_sol = float(spend_cap_str)
        except ValueError:
            spend_cap_sol = DEFAULT_SPEND_CAP_SOL

        rpc_url = os.getenv("SOLANA_RPC_URL", DEFAULT_RPC_URL).strip()
        ws_url = os.getenv("SOLANA_WS_URL", None)
        keypair_path = os.getenv("SOLANA_KEYPAIR_PATH", None)

        output_dir = Path(os.getenv("SOLANA_OUTPUT_DIR", "./data"))

        return cls(
            rpc_url=rpc_url,
            ws_url=ws_url,
            dry_run=dry_run,
            spend_cap_sol=spend_cap_sol,
            keypair_path=keypair_path,
            output_dir=output_dir,
        )
