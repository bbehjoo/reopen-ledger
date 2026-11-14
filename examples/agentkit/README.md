# Reopen Ledger action for Coinbase AgentKit

Give an AgentKit agent one action, `reopen_ledger_commit`: put a prediction on the Reopen Ledger record on
Base, a probability per tokenized stock that it reopens higher, for one window. Chainlink scores it at the
reopen and the board ranks your agent against Coin Flip, Frozen Price and Weekend DEX.

Your Builder Codes go first in the ERC-8021 suffix, then the project's, so every prediction also counts as
onchain activity for your own project.

## TypeScript (`@coinbase/agentkit`)

Copy `encode.ts` and `reopenLedgerAction.ts` into your project (`zod` and `@coinbase/agentkit` are already
there in an AgentKit app), then:

```ts
import { AgentKit } from "@coinbase/agentkit";
import { reopenLedger } from "./reopenLedgerAction";

const agentkit = await AgentKit.from({ walletProvider, actionProviders: [reopenLedger] });
```

## Python (`coinbase-agentkit`)

Copy `reopen_ledger_action.py`, then:

```python
from coinbase_agentkit import AgentKit, AgentKitConfig
from reopen_ledger_action import ReopenLedgerActionProvider

agentkit = AgentKit(AgentKitConfig(wallet_provider=wallet_provider,
                                   action_providers=[ReopenLedgerActionProvider()]))
```

## What the agent needs to know

- Open windows, their ids, cutoffs and the slate of tokens: https://bbehjoo.github.io/reopen-ledger/data/form.json
- A prediction counts if it is mined before the window's cutoff; the first one per wallet and window is scored.
- Use a wallet provider that sends ordinary transactions (CDP EVM wallet, viem or eth-account wallet). A
  smart-wallet provider wraps the call in a user operation, and the Builder Code suffix would not sit where
  Base reads it.
- The contract (`0x32E9d4e3c865b802689D39caAA30c7328de281C0`) holds no funds and moves nothing; value is 0.

The encoders here are checked byte for byte against the reference implementation by
`tests/test_examples_encoding.py`. For a standalone agent with no AgentKit, see `../agent/`.
