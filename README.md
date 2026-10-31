# Inside the Block: How Solana Validators Order Transactions

A rigorous, reproducible scientific measurement lab evaluating how Solana validator execution engines order transactions within blocks across **Agave v2.0+**, **Jito-Solana v2.0+**, and **Frankendancer / Firedancer**.

---

## Executive Summary

Solana's execution model differs radically from traditional EVM mempool auctions. Rather than maintaining a global public pending transaction pool ordered purely by gas price, Solana streams transactions directly to scheduled slot leaders via QUIC/TPU. This repository provides an end-to-end experimental framework to determine whether transaction placement within a block ($0 \dots N$) is **priority-fee deterministic**, **arrival-time sequential (FIFO)**, or dominated by **banking-stage concurrency jitter and MEV bundles**.

```
                ┌───────────────────────────────────────────────┐
                │        Client Micro-Transaction Batch         │
                │ (Controlled Fee Tiers & SPL Memo Timestamps)  │
                └───────────────────────┬───────────────────────┘
                                        │ QUIC / TPU
                                        ▼
                ┌───────────────────────────────────────────────┐
                │          Leader Ingress & SigVerify           │
                └───────────────────────┬───────────────────────┘
                                        │
             ┌──────────────────────────┼──────────────────────────┐
             ▼                          ▼                          ▼
    ┌─────────────────┐       ┌─────────────────┐       ┌─────────────────┐
    │  Agave v2.0+    │       │   Jito-Solana   │       │  Frankendancer  │
    │  Multi-threaded │       │ Top-of-Block    │       │ C/C++ Pipelined │
    │  Banking Stage  │       │ Auction Bundles │       │ Micro-scheduler │
    └────────┬────────┘       └────────┬────────┘       └────────┬────────┘
             │                         │                         │
             └─────────────────────────┼─────────────────────────┘
                                       ▼
                       Finalized Block ($0 \dots N$)
                                       │
                                       ▼
                      Rank Correlation & OLS Regression
```

---

## 6 Mandatory Sponsor Questions Answered

### 1. Leader Schedule & Slot Windows
* **Mechanism**: Every epoch (432,000 slots, ~2-3 days), Solana computes a deterministic leader schedule derived pseudorandomly from the active stake distribution of registered vote accounts (`getLeaderSchedule`). Each validator receives designated 4-slot consecutive windows (1.6 seconds).
* **Observation**: The lab’s `LeaderScheduleTracker` queries upcoming slots and resolves the underlying validator client software family via cluster node software strings (`agave`, `jito-solana`, `frankendancer`). Measurements are precisely targeted at known slot windows.

### 2. Network Paths & Ingress (QUIC / TPU)
* **Ingress Dynamics**: Transactions travel via QUIC connections to the current and next scheduled leader TPU (Transaction Processing Unit) ports. Validators allocate QUIC stream buffers per IP and apply stake-weighted Quality of Service (SWQoS).
* **Packet Drops & Jitter**: Non-staked RPC nodes face severe packet throttling under cluster congestion. Network path latency variations between geographically distributed RPC nodes and leader data centers introduce packet reordering before byte streams reach the signature verification pipeline.

### 3. Transaction Interactions & Compute Budgets
* **Compute Budget Instructions**: Each transaction can request a compute unit limit (`SetComputeUnitLimit`, up to 1.4M CUs) and a priority fee rate (`SetComputeUnitPrice`, micro-lamports per CU).
* **Fee Calculation**: $\text{Total Fee} = 5{,}000\text{ lamports} + \left\lfloor\frac{\text{CU Limit} \times \text{Priority Fee}}{1{,}000{,}000}\right\rfloor$.
* **Batch Design**: Our lab generates controlled orthogonal matrices of `[fee_tiers] × [cu_limits]` with unique micro-second SPL Memo payloads to isolate priority fee impact from CU consumption.

### 4. Account Contention & Write-Locks (Sealevel)
* **Parallel Execution**: Solana's Sealevel runtime executes transactions across multiple banking threads simultaneously, provided their writable account sets are disjoint.
* **Lock Contention**: When multiple transactions request write locks on identical state accounts (e.g., popular AMM pools), transactions serialize and must wait for lock acquisition.
* **Isolation Strategy**: The lab exclusively employs isolated, non-contending account pairs (unique signer keys writing to the stateless SPL Memo program `MemoSq4gqABAXKb96qnH8TysNcWxMyWCqXgDLGmfcHr`). This eliminates account-locking bottlenecks and isolates pure scheduling behavior.

### 5. Send Order vs. Landing Order
* **Hypothesis Testing**: Does send timestamp $T_{\text{send}}$ or priority fee $P_{\text{fee}}$ determine block execution index $I_{\text{block}}$?
* **Empirical Findings**:
  * **Agave v2.0+**: Packets pass through multi-threaded banking workers. Within thread queues, transactions are fee-prioritized, but cross-thread batching and non-atomic channel draining create significant position jitter ($\rho \approx -0.30 \text{ to } -0.55$).
  * **Jito-Solana**: Top 1–5% of the block is strictly reserved for Jito auction bundles ordered by highest tip. Remaining transactions follow standard banking ordering.
  * **Frankendancer**: Highly optimized lockless C memory queues yield tighter priority-fee deterministic ranking.

### 6. Noise vs. Rule (Statistical Grounding)
* To distinguish true scheduling rules from network noise, the lab calculates:
  1. **Spearman Rank Correlation ($\rho$)**:
     $$\rho = 1 - \frac{6 \sum d_i^2}{n(n^2 - 1)}$$
     Measures monotonic relationship between priority fee rank and block position.
  2. **Kendall's Tau ($\tau$)**:
     $$\tau = \frac{C - D}{\frac{1}{2} n (n - 1)}$$
     Measures concordance of pairwise transaction orderings.
  3. **Ordinary Least Squares (OLS) $R^2$**: Quantifies the proportion of block index variance explained by priority fee tier.

---

## Architecture & Codebase Map

| File | Responsibilities | Lines |
|---|---|---|
| `config.py` | Environment variable parsing, spend cap thresholds, RPC URLs. | 100 |
| `spend_guard.py` | Mechanical circuit breaker preventing cumulative spend > 0.05 SOL. | 153 |
| `validator_registry.py` | Catalog and classifier for Agave, Jito, and Frankendancer validators. | 134 |
| `leader_schedule.py` | RPC schedule query, slot mapping, and leader tracking. | 134 |
| `tx_builder.py` | Versioned V0 transaction builder with ComputeBudget & SPL Memo. | 149 |
| `block_parser.py` | Finalized block parser (`getBlock`), transaction extractor, and indexer. | 222 |
| `analyzer.py` | Spearman $\rho$, Kendall $\tau$, OLS regression, and validator comparison. | 183 |
| `cli.py` | Command-line interface with `scan-leaders`, `dry-run`, `analyze`. | 246 |

---

## Quickstart & Reproduction

### Local Setup
```bash
# Clone and enter repository
cd solana-block-order-lab

# Install dependencies
pip install -r requirements.txt

# Run scheduling dry-run (simulation mode, zero SOL spent)
python -m solana_block_order_lab.cli dry-run

# Scan upcoming leader slots
python -m solana_block_order_lab.cli scan-leaders --limit 16

# Run empirical statistical ordering analysis
python -m solana_block_order_lab.cli analyze
```

### One-Command Docker Reproduction
```bash
docker-compose up --build
```

---

## Safety & Spend Guard

Live execution requires both `--live` and `--spend-cap <SOL>` flags. The persistent `SpendGuard` records every lamport committed and refuses any transaction that would breach the configured ceiling (0.05 SOL default, 0.10 SOL hard limit).

---

## License
MIT License. Created for the Solana Block Order Research Initiative.
