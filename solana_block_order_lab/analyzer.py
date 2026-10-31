"""
Analyzer for Solana Block Order Lab.
Computes Spearman rank correlation, Kendall's Tau, and regression metrics
to determine whether block transaction execution is fee-prioritized, FIFO, or jitter.
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional
import numpy as np
from pydantic import BaseModel, Field
from scipy.stats import spearmanr, kendalltau, linregress

from .validator_registry import ClientFamily
from .block_parser import ParsedBlock, BlockTxRecord

logger = logging.getLogger(__name__)


class OrderingAnalysisResult(BaseModel):
    """Statistical evaluation of transaction landing order within a block or cluster."""
    client_family: ClientFamily = Field(..., description="Validator client family under test.")
    sample_size: int = Field(..., description="Number of analyzed experiment transactions.")
    slots_analyzed: int = Field(..., description="Number of unique blocks/slots analyzed.")
    spearman_fee_corr: float = Field(default=0.0, description="Spearman rank correlation: Fee vs Block Index.")
    spearman_fee_pvalue: float = Field(default=1.0, description="Spearman p-value for fee correlation.")
    kendall_fee_tau: float = Field(default=0.0, description="Kendall's Tau: Fee vs Block Index.")
    kendall_fee_pvalue: float = Field(default=1.0, description="Kendall's Tau p-value for fee.")
    spearman_time_corr: float = Field(default=0.0, description="Spearman rank correlation: Time vs Block Index.")
    spearman_time_pvalue: float = Field(default=1.0, description="Spearman p-value for arrival time.")
    kendall_time_tau: float = Field(default=0.0, description="Kendall's Tau: Time vs Block Index.")
    kendall_time_pvalue: float = Field(default=1.0, description="Kendall's Tau p-value for arrival time.")
    r_squared_fee: float = Field(default=0.0, description="OLS R-squared explaining block order by fee.")
    is_fee_deterministic: bool = Field(default=False, description="Whether fee statistically dictates ordering.")
    dominant_mechanism: str = Field(default="Indeterminate", description="Primary detected ordering mechanism.")
    fee_tier_positions: Dict[int, float] = Field(
        default_factory=dict, description="Mean block index per priority fee tier."
    )
    empirical_insights: List[str] = Field(default_factory=list, description="Key empirical deductions.")


class BlockOrderAnalyzer:
    """Statistical measurement engine evaluating block ordering behaviors."""

    def __init__(self, significance_alpha: float = 0.05):
        self.alpha = significance_alpha

    def analyze_blocks(
        self,
        blocks: List[ParsedBlock],
        family: Optional[ClientFamily] = None,
    ) -> Dict[ClientFamily, OrderingAnalysisResult]:
        """Aggregate transactions across parsed blocks and analyze by validator client family."""
        grouped_txs: Dict[ClientFamily, List[BlockTxRecord]] = {
            ClientFamily.AGAVE: [],
            ClientFamily.JITO: [],
            ClientFamily.FIREDANCER: [],
            ClientFamily.UNKNOWN: [],
        }
        grouped_slots: Dict[ClientFamily, set[int]] = {
            ClientFamily.AGAVE: set(),
            ClientFamily.JITO: set(),
            ClientFamily.FIREDANCER: set(),
            ClientFamily.UNKNOWN: set(),
        }

        for block in blocks:
            fam = block.client_family or ClientFamily.UNKNOWN
            txs = block.experiment_transactions or [
                tx for tx in block.transactions if tx.is_experiment_tx
            ]
            if txs:
                grouped_txs[fam].extend(txs)
                grouped_slots[fam].add(block.slot)

        results: Dict[ClientFamily, OrderingAnalysisResult] = {}
        target_families = [family] if family else list(ClientFamily)

        for fam in target_families:
            tx_list = grouped_txs.get(fam, [])
            slot_count = len(grouped_slots.get(fam, set()))
            if not tx_list:
                continue
            results[fam] = self.analyze_records(tx_list, fam, slot_count)

        return results

    def analyze_records(
        self,
        records: List[BlockTxRecord],
        client_family: ClientFamily = ClientFamily.UNKNOWN,
        slot_count: int = 1,
    ) -> OrderingAnalysisResult:
        """Run rank correlations and linear regression across transaction records."""
        n = len(records)
        if n < 3:
            return OrderingAnalysisResult(
                client_family=client_family,
                sample_size=n,
                slots_analyzed=slot_count,
                dominant_mechanism="Insufficient Data (n < 3)",
                empirical_insights=["Sample size too small for statistical significance testing."],
            )

        indices = np.array([r.block_index for r in records], dtype=float)
        fees = np.array([r.priority_fee_micro_lamports for r in records], dtype=float)

        # Invert fees so higher fee = rank 1 (expected lower block_index if fee prioritized)
        # Note: If high fee lands early (small index), corr(fee, index) should be strongly NEGATIVE.
        spearman_fee, sp_fee_p = spearmanr(fees, indices)
        kendall_fee, kd_fee_p = kendalltau(fees, indices)

        # Time correlation on subset with timestamps
        time_records = [r for r in records if r.memo_timestamp_ns is not None]
        if len(time_records) >= 3:
            t_indices = np.array([r.block_index for r in time_records], dtype=float)
            timestamps = np.array([r.memo_timestamp_ns for r in time_records], dtype=float)
            spearman_time, sp_time_p = spearmanr(timestamps, t_indices)
            kendall_time, kd_time_p = kendalltau(timestamps, t_indices)
        else:
            spearman_time, sp_time_p = 0.0, 1.0
            kendall_time, kd_time_p = 0.0, 1.0

        # OLS regression: index ~ fee
        slope, intercept, r_value, p_value, std_err = linregress(fees, indices)
        r_squared = float(r_value ** 2) if not np.isnan(r_value) else 0.0

        # Mean block position by fee tier
        fee_positions: Dict[int, list[float]] = {}
        for r in records:
            fee_positions.setdefault(r.priority_fee_micro_lamports, []).append(float(r.block_index))
        mean_positions = {k: float(np.mean(v)) for k, v in fee_positions.items()}

        # Evaluate hypothesis: Fee priority vs arrival jitter
        # Strong negative correlation (e.g. corr < -0.6, p < 0.05) indicates fee-driven sorting
        # Positive time correlation (e.g. corr > 0.6, p < 0.05) indicates FIFO queueing
        is_fee_sorted = bool(spearman_fee < -0.4 and sp_fee_p < self.alpha)
        is_time_sorted = bool(spearman_time > 0.4 and sp_time_p < self.alpha)

        insights = []
        if is_fee_sorted:
            mechanism = "Fee-Prioritized Ordering"
            insights.append(
                f"Statistically significant inverse correlation (rho={spearman_fee:.3f}, p={sp_fee_p:.4e}): "
                "Higher priority fees systematically achieve earlier slot positions."
            )
        elif is_time_sorted:
            mechanism = "FIFO / Time-Ordered Arrival"
            insights.append(
                f"Statistically significant arrival correlation (rho={spearman_time:.3f}, p={sp_time_p:.4e}): "
                "Transactions executed in temporal arrival sequence."
            )
        else:
            mechanism = "Continuous Pipelining / Multi-Threaded Jitter"
            insights.append(
                f"Weak correlation to fee (rho={spearman_fee:.3f}, R²={r_squared:.3f}). "
                "Block assembly shows non-deterministic thread contention and banking stage interleaving."
            )

        if client_family == ClientFamily.JITO:
            insights.append("Jito-Solana executes auction bundles at top-of-block; non-bundle txs undergo standard banking.")
        elif client_family == ClientFamily.FIREDANCER:
            insights.append("Frankendancer implements strict C-based micro-pipelined transaction scheduling.")

        return OrderingAnalysisResult(
            client_family=client_family,
            sample_size=n,
            slots_analyzed=slot_count,
            spearman_fee_corr=float(spearman_fee) if not np.isnan(spearman_fee) else 0.0,
            spearman_fee_pvalue=float(sp_fee_p) if not np.isnan(sp_fee_p) else 1.0,
            kendall_fee_tau=float(kendall_fee) if not np.isnan(kendall_fee) else 0.0,
            kendall_fee_pvalue=float(kd_fee_p) if not np.isnan(kd_fee_p) else 1.0,
            spearman_time_corr=float(spearman_time) if not np.isnan(spearman_time) else 0.0,
            spearman_time_pvalue=float(sp_time_p) if not np.isnan(sp_time_p) else 1.0,
            kendall_time_tau=float(kendall_time) if not np.isnan(kendall_time) else 0.0,
            kendall_time_pvalue=float(kd_time_p) if not np.isnan(kd_time_p) else 1.0,
            r_squared_fee=r_squared,
            is_fee_deterministic=is_fee_sorted,
            dominant_mechanism=mechanism,
            fee_tier_positions=mean_positions,
            empirical_insights=insights,
        )
