"""V9 data preload + polling refresh.

Loads the canonical Polymarket trades + Hyperliquid liquidations parquets
that the V9 gates (B1/B2/B3/A2) consume at fire time.

Per ``SHADOW_DEPLOY_SPEC_V9_AND_VL_2026_05_27.md`` §2.5.

Design notes:

  * Pure stdlib + ``pandas``. No async / IO loops here — the engine lifespan
    spawns ``refresh_loop`` as a background asyncio.Task at boot.
  * ``V9DataStore.load_initial()`` is called ONCE at boot. Missing files are
    logged as a warning but do NOT raise — V9 gates degrade gracefully to
    "no fire" (defensive). This means deploying V9 on a VPS where the
    canonical parquets haven't been written yet is safe (engine boots
    clean; V9 sleeves stay silent until data lands).
  * ``refresh_loop`` re-reads each parquet every ``refresh_s`` seconds.
    Cheap on a per-poll basis; pandas mmap-loads the file. Use a
    conservative cadence (default 5 min) since the canonical writers are
    offline batch jobs.
  * The HL ``hl_short_proxy`` filter is applied once per refresh
    (pre-filtered for fast lookup at gate eval time — see spec §2.5).

CLAUDE.md inv #13 — TV-native data:
  These parquets are STOREDATA artifacts that live under
  ``/opt/tradingvenue/data/v4/canonical/`` on each VPS. They are written
  by separate Storedata jobs, NOT by tv-engine. tv-engine READS them
  read-only for V9 gate evaluation. No write path here.

CLAUDE.md inv #4 — gates pure / closed-bar:
  The data store is mutated only by the refresh loop. Gates read whatever
  the store holds at fire time. Stale reads degrade signal quality
  gracefully (older windows still align with their original trade history).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import structlog

logger = structlog.get_logger(__name__)

#: Per-asset canonical path under the data root.
_TRADES_REL = {
    "btc": "v4/canonical/trades_polymarket/btc.parquet",
    "eth": "v4/canonical/trades_polymarket/eth.parquet",
    "sol": "v4/canonical/trades_polymarket/sol.parquet",
}
_HL_REL = "v4/canonical/hyperliquid_liquidations_full.parquet"


@dataclass
class V9DataStore:
    """In-memory holder for V9 input DataFrames.

    The controller calls ``get_asset_trades("btc")`` etc. at gate-dispatch
    time. ``None`` values are valid (and frequent until first successful
    load) — gates treat ``None`` as "no fire".
    """

    data_root: Path
    asset_trades: dict[str, Any] = field(default_factory=dict)  # str -> pd.DataFrame
    hl_short_proxy: Any = None  # pd.DataFrame | None
    last_refresh_ts: int = 0
    n_refreshes: int = 0
    last_errors: dict[str, str] = field(default_factory=dict)

    def get_asset_trades(self, asset: str) -> Any:
        """Lowercase asset key. Returns None if not loaded."""
        return self.asset_trades.get(asset.lower())

    def get_hl_short_proxy(self) -> Any:
        return self.hl_short_proxy

    def load_initial(self) -> None:
        """One-shot synchronous load at engine boot.

        Missing files are logged but do NOT raise.
        """
        self._load_trades()
        self._load_hl_short_proxy()
        logger.info(
            "sniper_v5_v9_data.initial_load",
            data_root=str(self.data_root),
            n_assets_loaded=len(self.asset_trades),
            assets_loaded=sorted(self.asset_trades.keys()),
            hl_proxy_rows=(
                int(len(self.hl_short_proxy)) if self.hl_short_proxy is not None else 0
            ),
            errors=self.last_errors,
        )

    def _load_trades(self) -> None:
        # Lazy + tolerant pandas import — VPS that hasn't pip-installed
        # pandas/pyarrow yet still boots cleanly with V9 silent.
        try:
            import pandas as pd  # noqa: PLC0415, F401
        except ImportError:
            for asset in _TRADES_REL:
                self.asset_trades[asset] = None
                self.last_errors[f"trades_{asset}"] = "pandas_not_installed"
            logger.warning("sniper_v5_v9_data.pandas_unavailable_trades_skipped")
            return
        for asset, rel in _TRADES_REL.items():
            path = self.data_root / rel
            try:
                df = pd.read_parquet(path)
                self.asset_trades[asset] = df
                self.last_errors.pop(f"trades_{asset}", None)
            except FileNotFoundError:
                self.asset_trades[asset] = None
                self.last_errors[f"trades_{asset}"] = "file_not_found"
                logger.warning(
                    "sniper_v5_v9_data.trades_missing",
                    asset=asset,
                    path=str(path),
                )
            except Exception as exc:  # noqa: BLE001 — defensive, never raise on boot
                self.asset_trades[asset] = None
                self.last_errors[f"trades_{asset}"] = str(exc)
                logger.warning(
                    "sniper_v5_v9_data.trades_load_failed",
                    asset=asset,
                    path=str(path),
                    error=str(exc),
                )

    def _load_hl_short_proxy(self) -> None:
        try:
            import pandas as pd  # noqa: PLC0415, F401
        except ImportError:
            self.hl_short_proxy = None
            self.last_errors["hl_proxy"] = "pandas_not_installed"
            logger.warning("sniper_v5_v9_data.pandas_unavailable_hl_skipped")
            return
        path = self.data_root / _HL_REL
        try:
            raw = pd.read_parquet(path)
            mask = (
                (raw["source"] == "hl-s3-fills")
                & (raw["method"] == "market")
                & (raw["dir"].isin(["Close Short", "Open Long"]))
            )
            proxy = raw.loc[mask].copy()
            proxy["notional"] = proxy["size"] * proxy["price"]
            self.hl_short_proxy = proxy
            self.last_errors.pop("hl_proxy", None)
        except FileNotFoundError:
            self.hl_short_proxy = None
            self.last_errors["hl_proxy"] = "file_not_found"
            logger.warning(
                "sniper_v5_v9_data.hl_missing",
                path=str(path),
            )
        except Exception as exc:  # noqa: BLE001
            self.hl_short_proxy = None
            self.last_errors["hl_proxy"] = str(exc)
            logger.warning(
                "sniper_v5_v9_data.hl_load_failed",
                path=str(path),
                error=str(exc),
            )

    async def refresh_loop(self, refresh_s: int = 300) -> None:
        """Background polling refresh task.

        Cancellation-safe: catches CancelledError at the asyncio.sleep boundary
        and exits cleanly so engine lifespan teardown is graceful.
        """
        import time

        logger.info("sniper_v5_v9_data.refresh_loop_started", refresh_s=refresh_s)
        try:
            while True:
                await asyncio.sleep(refresh_s)
                try:
                    self._load_trades()
                    self._load_hl_short_proxy()
                    self.last_refresh_ts = int(time.time() * 1_000_000)
                    self.n_refreshes += 1
                    logger.info(
                        "sniper_v5_v9_data.refresh_complete",
                        n_refreshes=self.n_refreshes,
                        n_assets_loaded=sum(
                            1 for v in self.asset_trades.values() if v is not None
                        ),
                        hl_proxy_rows=(
                            int(len(self.hl_short_proxy))
                            if self.hl_short_proxy is not None
                            else 0
                        ),
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "sniper_v5_v9_data.refresh_iteration_failed",
                        error=str(exc),
                    )
        except asyncio.CancelledError:
            logger.info("sniper_v5_v9_data.refresh_loop_stopped")
            raise


__all__ = ["V9DataStore"]
