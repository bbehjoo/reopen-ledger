// Reopen Ledger as a Coinbase AgentKit action (TypeScript, @coinbase/agentkit with customActionProvider).
//
//   import { reopenLedger } from "./reopenLedgerAction";
//   const agentkit = await AgentKit.from({ walletProvider, actionProviders: [reopenLedger] });
//
// The action `reopen_ledger_commit` puts one prediction on the record: a probability per token that it reopens
// higher, for one window (ids and slates: https://bbehjoo.github.io/reopen-ledger/data/form.json). Your Builder
// Codes go first in the ERC-8021 suffix, then the project's, so the transaction counts for both. Use a wallet
// provider that sends ordinary transactions (CdpEvmWalletProvider, ViemWalletProvider): a smart-wallet provider
// wraps the call and the suffix would not sit where Base reads it.
import { customActionProvider, EvmWalletProvider } from "@coinbase/agentkit";
import { z } from "zod";

import { encode, LEDGER } from "./encode";

const Schema = z.object({
  windowId: z.number().int().nonnegative(),
  calls: z.array(z.object({ token: z.string(), p: z.number().min(0).max(1) })).min(1),
  builderCodes: z.array(z.string().regex(/^[^,]+$/)).optional(),
});

export const reopenLedger = customActionProvider<EvmWalletProvider>({
  name: "reopen_ledger_commit",
  description:
    "Put a prediction on the Reopen Ledger record on Base: for one window, the probability each token reopens higher. " +
    "Value 0; the contract holds no funds.",
  schema: Schema,
  invoke: async (wallet, a: z.infer<typeof Schema>) => {
    const data = encode(a.windowId, a.calls, a.builderCodes ?? []);
    const hash = await wallet.sendTransaction({ to: LEDGER, data, value: 0n });
    await wallet.waitForTransactionReceipt(hash);
    return `On the record for window ${a.windowId}: https://basescan.org/tx/${hash}`;
  },
});
