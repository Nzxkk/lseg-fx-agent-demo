---
name: lseg-session-diagnostics
description: LSEG/Refinitiv local session diagnostic workflow. Distinguishes missing Python libraries, closed Workspace/Eikon sessions, desktop proxy failures, entitlement gaps, and empty RIC responses.
category: diagnostics
---

# LSEG Session Diagnostics

Use this skill when the user cannot pull LSEG/Refinitiv data, sees localhost proxy errors, or gets empty market/news responses.

## Diagnostic Scope

- Python package availability: `lseg.data` or `refinitiv.data`.
- Local desktop session: Workspace/Eikon opened and logged in.
- Desktop proxy: localhost service reachable.
- Entitlements: FX, rates, DXY, VIX, and Reuters News permissions.
- RIC validity: configured RICs return usable fields.

## Tool Flow

1. Check whether the Python environment can import the LSEG or Refinitiv data library.
2. Open a session and request a small FX quote such as `EUR=`.
3. If the desktop proxy refuses connection, tell the user to open Workspace/Eikon and log in.
4. If a RIC returns all-empty data, classify it as RIC or entitlement issue.
5. If news fails while market data works, isolate it as Reuters News entitlement or library API-version issue.

## Common Error Mapping

- `ConnectError('[Errno 61] Connection refused')`: Workspace/Eikon desktop proxy is not running.
- `Session is not opened`: session handshake failed before data request.
- Empty `BID`/`ASK`/`TRDPRC_1`: RIC unavailable or account lacks permission.
- News helper missing: installed library version does not expose the expected news API path.

## Output Contract

The Agent should report:

- which layer failed,
- the most likely reason,
- the next user action,
- whether the failure blocks signal generation.

Do not hide diagnostics behind a generic "API failed" message.
