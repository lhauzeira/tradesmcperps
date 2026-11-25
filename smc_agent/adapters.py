"""Leitura de dados: XM/MetaTrader 5 e MyFundedPerps sandbox.

PROIBIDO enviar ordens: nenhuma interface de execução está habilitada.
A API MyFundedPerps está em beta; confirme URL/rotas com a documentação
oficial antes de conectar. Nunca envie chaves ao GitHub ou ao chat.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen
from .engine import Candle


class MT5Adapter:
    """Depende do pacote MetaTrader5 e do terminal MT5 local logado."""
    _TIMEFRAMES = {
        "M1": "TIMEFRAME_M1", "M2": "TIMEFRAME_M2", "M5": "TIMEFRAME_M5",
        "M15": "TIMEFRAME_M15", "H1": "TIMEFRAME_H1",
        "H4": "TIMEFRAME_H4", "D1": "TIMEFRAME_D1"
    }

    def __init__(self, symbol: str):
        try:
            import MetaTrader5 as mt5
        except ImportError as error:
            raise RuntimeError("MetaTrader5 Python indisponível; necessário Windows + terminal") from error
        self.mt5 = mt5
        self.symbol = symbol

    def connect(self):
        if not self.mt5.initialize():
            raise RuntimeError("Falha na inicialização do MetaTrader 5")
        if not self.mt5.symbol_select(self.symbol, True):
            raise RuntimeError("Símbolo indisponível no terminal MT5")
        account = self.mt5.account_info()
        if account is None:
            raise RuntimeError("Conta MT5 não conectada")
        return account

    def bars(self, timeframe: str, count: int = 500) -> list[Candle]:
        if timeframe not in self._TIMEFRAMES:
            raise ValueError("Timeframe inválido")
        if count < 40:
            raise ValueError("Histórico insuficiente")
        # Posição 0 = candle em formação; começar na posição 1.
        rates = self.mt5.copy_rates_from_pos(
            self.symbol, getattr(self.mt5, self._TIMEFRAMES[timeframe]), 1, count
        )
        if rates is None or len(rates) < 40:
            raise RuntimeError("MT5 retornou histórico insuficiente")
        sorted_rates = sorted(rates, key=lambda x: int(x["time"]))
        return [
            Candle(datetime.fromtimestamp(int(r["time"]), timezone.utc),
                   float(r["open"]), float(r["high"]), float(r["low"]),
                   float(r["close"]), float(r["tick_volume"]))
            for r in sorted_rates
        ]

    def quote_history(self, start: datetime, end: datetime, *,
                      timeframe_seconds: int, as_of: datetime, venue: str,
                      max_ticks: int = 500000):
        """Read native MT5 bid/ask tick snapshots and aggregate closed UTC bars.

        Requires an initialized, authenticated terminal. This is READ-ONLY.
        Venue must identify the real broker feed; do not map spot to futures.
        Historical availability and complete quote coverage need manual validation.
        """
        from .lifecycle import _aware
        from .ticks import aggregate_bidask_ticks
        for label, moment in (("start", start), ("end", end), ("as_of", as_of)):
            _aware(moment, label)
        if start >= end or end > as_of:
            raise ValueError("Tick request time range is invalid or in the future")
        if not venue or venue == "MT5-UNVERIFIED":
            raise ValueError("A verified broker-specific venue label is required")
        if max_ticks < 1:
            raise ValueError("Maximum tick count must be positive")
        ticks = self.mt5.copy_ticks_range(
            self.symbol, start.astimezone(timezone.utc),
            end.astimezone(timezone.utc), self.mt5.COPY_TICKS_INFO
        )
        if ticks is None or len(ticks) == 0:
            raise RuntimeError("MT5 did not return native bid/ask tick history")
        return aggregate_bidask_ticks(
            ticks, venue=venue, symbol=self.symbol,
            source="MT5_COPY_TICKS_INFO_UNVERIFIED_COVERAGE",
            timeframe_seconds=timeframe_seconds, as_of=as_of,
            max_ticks=max_ticks,
        )

    def account(self):
        value = self.mt5.account_info()
        if value is None:
            raise RuntimeError("Conta MT5 indisponível")
        return {"equity": float(value.equity), "balance": float(value.balance),
                "currency": str(value.currency), "trade_mode": int(value.trade_mode)}

    def close(self):
        self.mt5.shutdown()

    def send_order(self, *args, **kwargs):
        raise RuntimeError("Envio de ordens BLOQUEADO neste protótipo")


class MyFundedPerpsAdapter:
    """GET somente no sandbox com token de TESTE.

    Rotas experimentais. Se o contrato público mudar, falhar explicitamente
    em vez de desviar para uma URL de produção.
    """
    BASE = "https://sandbox.myfundedperpetuals.com"

    def __init__(self, token: str | None = None):
        token = token if token is not None else os.environ.get("FP_TEST_API_KEY", "")
        if not token.startswith("fp_test_"):
            raise RuntimeError("Somente tokens fp_test_ são aceitos")
        self._token = token

    def _get(self, path: str) -> dict:
        if not path.startswith("/v1/"):
            raise ValueError("Rota não autorizada")
        request = Request(
            self.BASE + path,
            headers={"Authorization": "Bearer " + self._token,
                     "Accept": "application/json", "User-Agent": "SMCAgentResearch/0.1"}
        )
        try:
            with urlopen(request, timeout=12) as response:
                return json.load(response)
        except HTTPError as error:
            # Não registrar response headers ou tokens.
            raise RuntimeError(f"API sandbox HTTP {error.code}") from error
        except URLError as error:
            raise RuntimeError("Sandbox indisponível") from error

    def accounts(self) -> dict:
        return self._get("/v1/accounts")

    def policy(self, account_id: str) -> dict:
        return self._get("/v1/accounts/" + quote(account_id, safe="") + "/trading-policy")

    def markets(self) -> dict:
        return self._get("/v1/markets")

    def send_order(self, *args, **kwargs):
        raise RuntimeError("Envio de ordens BLOQUEADO neste protótipo")
