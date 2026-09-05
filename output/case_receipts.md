# Case Notes

These notes are manually written from `output/case_receipts.json` and the local target-pool Swap dataset. The purpose is to separate plain large swaps from more interesting cross-pool candidates.

## 0x611bd37d...2ecfd349

This transaction is a clean large target-pool sell. The receipt contains one Uniswap v3 Swap log in the target WETH/USDC 0.05% pool:

- sold 72.60229143 WETH
- received 179,740.858012 USDC
- block `50867835`
- gas used `303,190`

In the local metrics this was the largest economic outlier: estimated extra slippage of 35.040 bps, about $629.82. It is useful as an execution-risk anchor. It is not, by itself, evidence of arbitrage because the receipt does not show cross-pool routing.

## 0x1a2915ed...886dbaf7

This is another clean large target-pool sell. The receipt contains one Uniswap v3 Swap log in the target WETH/USDC 0.05% pool:

- sold 57.74181688 WETH
- received 143,597.940675 USDC
- block `50867834`
- gas used `264,998`

The estimated extra slippage was 27.882 bps, about $400.38. Like the previous case, this is best treated as a large-flow execution-risk event rather than an arbitrage case.

## 0x27573ac3...530ed72d

This transaction is more interesting. The receipt shows five Uniswap v3 Swap logs. It sold WETH in a WETH/USDC 0.30% pool, bought WETH in the target WETH/USDC 0.05% pool, routed through SOL/cbBTC and JitoSOL/cbBTC, and then touched the target pool again in the opposite direction.

Relevant logs:

- WETH/USDC 0.30% pool: sold 37.76775779 WETH for 93,944.044279 USDC.
- Target WETH/USDC 0.05% pool: bought 37.83902586 WETH for 93,944.044279 USDC.
- Target WETH/USDC 0.05% pool again: sold 0.60491969 WETH for 1,503.045036 USDC.

This looks like a cross-pool route or arbitrage candidate because it uses different WETH/USDC fee tiers in opposite directions inside the same transaction. It still needs full trace and balance accounting before making any profit claim.

## 0xc0998372...a231a369

This is the richest case in the sample. The receipt contains eight Uniswap v3 Swap logs and uses multiple pools:

- WETH/USDC 0.30%
- target WETH/USDC 0.05%
- SOL/cbBTC
- JitoSOL/cbBTC
- WETH/cbBTC
- USDC/cbBTC
- another WETH/USDC 0.01% pool

The WETH/USDC legs are the key part:

- WETH/USDC 0.30% pool: sold 36.40144260 WETH for 90,505.164198 USDC.
- Target WETH/USDC 0.05% pool: bought 36.46764196 WETH for 90,505.164198 USDC.
- Target WETH/USDC 0.05% pool later: sold 8.24000034 WETH for 20,457.352612 USDC.
- WETH/USDC 0.01% pool: sold 2.22383211 WETH for 5,520.838810 USDC.

This is a stronger MEV/arbitrage candidate than a simple post-swap reversal because the same receipt shows cross-pool and cross-fee-tier behavior. The next check would be a full transaction trace: token balance changes, gas cost, router/caller identity, and whether the WETH/USDC price differences covered all fees.

## Takeaway

The large single-pool sells explain execution risk. The multi-pool same-transaction cases are the better candidates for arbitrage or MEV review. Keeping those categories separate makes the analysis much cleaner.
