# Confirmed source drift and selected strategy

The user chose the earlier audited source **with SMA10 exits** on October 13, 2026. That exact version is saved as `source_snapshot/main.cpp` under `backtesting/`. The current production file remains untouched. `source_selection.json` records the explicit selection; the original preservation baseline and source hash pins remain unchanged.

The current `traderBot/main.cpp` differs from the original audit by exactly four added bytes: `/*` at line203 and `*/` at line227. These delimiters comment out the entire SMA10 exit-order block. The current production source therefore no longer submits those SMA10 exit orders or sets `closeOrderExecuted` in that block. This is a material strategy change.

| Evidence | Selected original audited source | Current production source |
|---|---|---|
| Bytes | 11567 | 11571 |
| SHA-256 | `2a175ea48702370024aa59dc0ef2a93a22d849bdf5cd60fcc674291288fad05d` | `00b08c2c48a1991ac099214ee9510299e2e56826bd3d6f72152185cccf13e5e0` |

Current source modification time reported by the filesystem: 2026-10-12T16:43:41.782963+03:00 (Asia/Jerusalem). Filesystem metadata alone does not identify who made the change.

Verification read the current bytes and removed only those two delimiters in memory. The resulting SHA-256 exactly matched the pinned original hash before those verified bytes were saved under `backtesting/source_snapshot/`. No original source file was edited. Machine-readable evidence is in `source_drift.json`.

Normal builds now resolve `main.cpp` to the user-selected snapshot and compile the other original strategy sources directly. Generation checks every initial source pin and also confirms that the current production file still matches its observed post-change hash. It refuses further drift. `build/adapter_manifest.json` records actual source paths and the explicit selection so results cannot be confused with the current commented-out-exit version.

Initial-to-current preservation verification must continue to report the production main file difference. A separate check that production stayed unchanged **after this source selection** is a different statement, and does not erase that initial drift. The selected version still contains no break-even implementation; historical replay additionally requires actual market data and validated coverage.
