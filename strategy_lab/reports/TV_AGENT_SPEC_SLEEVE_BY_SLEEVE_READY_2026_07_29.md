# TV RUST AGENT — "READY STATE": per-sleeve live controls, wallet panel, shadow-cost report, final restart
**2026-07-29 · TVRUST · vps_ireland. Goal: after this spec the box sits in READY STATE — operator funds the wallet, then arms ANY individual sleeve from its own button, sleeve by sleeve, whenever we choose. ⏱️ HARD CONSTRAINT: the same-hours latency capture runs 21:36→09:36Z — NO box builds, deploys, or restarts inside that window. Build locally; everything lands in ONE deploy after 09:36Z.**

## §R — rulings on your last report
1. Dual fill-model display (walk + level-0) — APPROVED, right call; the 2.8× ETH gap is exactly what live fills will arbitrate. Keep both until then.
2. Strip refusing a summed fleet total — ENDORSED (same-window competing arms; naive sum = 4× fiction). One-arm-per-(asset,tf) with arms named inline is the standard now.
3. The binance-feed gating catch (empty roster would have blinded ladder pricing + sumpair signal) — this alone justified the staged-not-applied discipline. Consumer-named gating accepted.
4. The ::float8 panic + psql-shows-values-not-types lesson — accepted; same class as benchmark-with-literals; the pinned tests are the right closure.

## 1. Per-sleeve live controls (UI future-proofing — the API is already per-sleeve)
- Live page becomes a **card per live-capable sleeve** (today: `poly_ladder_btc_5m_v3_live` only), each card: own START/STOP button, own caps (per-side/day/loss), own precondition checklist, own armed-since + session PnL. The layout must make "arm ONE sleeve" the only possible gesture — no global start. Global KILL stays, clearly separated + labeled "flattens EVERYTHING".
- Registry: a small `live_capable` list (code or table) drives which cards render, so future live sleeves (c2-sizing knobs on the same sleeve, later sumpair-btc-live) appear as cards without UI rework. Document how a new live sleeve gets added (checklist: live branch code + caps env + arm_state row + drills).

## 2. Wallet panel (operator request — funds visible at all times)
- Live page + compact header chip when any sleeve armed: **pUSD balance · POL (gas) balance · allowance status (CTF/exchange approved: yes/no per approval) · open live exposure vs balance**. Source: the same cached on-chain reads the arm preconditions use (≤60s cache); surface last-refresh age.
- Alert badges: POL below ~0.5 (gas floor), pUSD below active caps sum, allowance missing. These are display-only — the arm preconditions already enforce.

## 3. Shadow-mode resource report (operator question: "can we stop shadows when live?")
- Measure and report: engine CPU% + RSS attributable to the paper fleet (approximate is fine: compare 10-min CPU/RSS with roster as-is vs the twins-retired roster after the restart; per-loop tick rates already known). Publish numbers in the report + a Health-page line ("paper fleet cost: X% CPU / Y MB").
- **Ruling to implement, not debate: the paper twin `poly_ladder_btc_5m_v3` NEVER pauses while its live sibling is armed** — live-vs-paper same-window comparison IS the capture ratio. Other paper arms may get a "pause paper arm" control ONLY if your measurements show real contention (>25% of a core total); expectation: they won't, and we keep the A/B evidence engine running. State the numbers either way.

## 4. The pending restart (execute AFTER 09:36Z, one boot)
Carries, together: twins retirement per `PENDING_ENGINE_RESTART_RETIRE_TWINS_2026_07_28.md` (verify post-boot sleeve list in the log — ladder fleet + sumpair + live sleeve ONLY, no 120-sleeve accident) + anything else queued engine-side. After boot: confirm boot_reset row, cadence healthy on /health/tick-cadence, strip shows the rewired families, twins absent.

## 5. READY-STATE checklist (deliver as the final section of your report)
- [ ] Latency after-table delivered (say plainly if pinning is neutral)
- [ ] Restart done; roster = ladder fleet + sumpair + live sleeve; boot_reset verified
- [ ] Per-sleeve Live cards rendering; arm-refusal shows wallet_funded FAIL (screenshot)
- [ ] Wallet panel showing $0.00 / 0 POL / allowances NO (it should look "red and honest" pre-funding)
- [ ] Operator password rotated + delivered out-of-band (STILL OPEN from before — this blocks everything; if already done, say where the operator finds it)
- [ ] Phone screenshot (§3.3, still owed)
- [ ] Then: operator funds → approvals → you verify allowances on-chain → STOP → operator triggers drills → dry-arm → session-1 via the sleeve's own button
Remaining after ready-state (unchanged queue): Tape/Health pages, PWA.
