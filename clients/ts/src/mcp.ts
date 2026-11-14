#!/usr/bin/env node
/**
 * MCP server (stdio) over the published data of Reopen Ledger. Read-only, holds no keys.
 *
 * Tools:
 *   open_windows      windows open for records, with cutoffs and slates
 *   token_feed        the per-token record (tier, flags, depth, staleness, coverage) for a symbol
 *   encode_commit     calldata for commit(windowId, 1, data) from probabilities; the agent's own wallet sends it
 *   is_official_token whether an address is on Coinbase's official list
 *
 * Config: CALLREC_DATA_URL, the base URL of the site's data/ directory (or a local path served over http).
 */
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";
import { encodeFunctionData, type Address, type Hex } from "viem";
import { attributionSuffix, encodeCalls, LEDGER_ABI, SCHEMA_CALLS } from "./index.js";
import { isOfficialToken, OFFICIAL_TOKENS } from "./tokens.js";

const BASE = (process.env.CALLREC_DATA_URL ?? "").replace(/\/$/, "");

async function getJson(path: string): Promise<any> {
  if (!BASE) throw new Error("CALLREC_DATA_URL is not set");
  const r = await fetch(`${BASE}/${path}`);
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

function text(obj: unknown) {
  return { content: [{ type: "text" as const, text: JSON.stringify(obj, null, 1) }] };
}

const server = new McpServer({ name: "callrec-placeholder", version: "0.1.0" });

server.tool("open_windows", "Windows open for records: id, label, cutoff (a record counts only if mined by then), slate tokens.",
  {}, async () => {
    const f = await getJson("form.json");
    return text({ ledger: f.ledger, windows: f.windows, slate: f.slate, builder_codes: f.builder_codes });
  });

server.tool("token_feed", "The published per-token record: tier, flags with evidence, depth, reference staleness, coverage.",
  { symbol: z.string().describe("official symbol, e.g. NVDAc") }, async ({ symbol }) => text(await getJson(`feed/${symbol}.json`)));

server.tool("is_official_token", "Whether an address is on Coinbase's official tokenized-stock list (track by address, not symbol).",
  { address: z.string() }, async ({ address }) =>
    text({ address, official: isOfficialToken(address), symbol: OFFICIAL_TOKENS[address.toLowerCase()] ?? null }));

server.tool("encode_commit",
  "Calldata for a record: commit(windowId, 1, data). Send it from your own wallet to the ledger address; this tool signs nothing.",
  {
    windowId: z.number().int(),
    calls: z.array(z.object({ token: z.string(), pUp: z.number().min(0).max(1), retBps: z.number().optional() })),
    builderCodes: z.array(z.string()).optional(),
  },
  async ({ windowId, calls, builderCodes }) => {
    for (const c of calls) if (!isOfficialToken(c.token)) throw new Error(`not an official token: ${c.token}`);
    const data = encodeCalls(calls.map((c) => ({ token: c.token as Address, pUp: c.pUp, retBps: c.retBps })));
    let cd: Hex = encodeFunctionData({ abi: LEDGER_ABI, functionName: "commit", args: [windowId, SCHEMA_CALLS, data] });
    if (builderCodes?.length) cd = (cd + attributionSuffix(builderCodes).slice(2)) as Hex;
    return text({ to_note: "the ledger address from open_windows", data: cd, value: "0x0" });
  });

await server.connect(new StdioServerTransport());
