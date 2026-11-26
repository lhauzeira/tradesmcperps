"""Pre-execution broker probe on XMGlobal-MT5 5 DEMO — READ ONLY.

This module explicitly NEVER calls order_send/order_check, never changes
orders or positions, and never permits execution. It queries account,
symbol specifications, quotes, current exposure, and estimates a proposed
stop-loss and margin *in the actual account currency* with MT5's read-only
order_calc_profit and order_calc_margin functions.

Preflight is not order execution, not a guarantee of fill at the stop,
not a broker holiday/session verifier, and not a profitability test.

No account IDs, secrets or raw positions are returned.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from .monitor_local import EXPECTED_SERVER, check_demo_account


def _decimal(value: Any, name: str, *, allow_zero: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name}: boolean não permitido")
    try:
        d = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError(f"{name}: valor numérico inválido") from None
    if not d.is_finite() or d < 0 or (not allow_zero and d == 0):
        raise ValueError(f"{name}: valor fora dos limites")
    return d


def _aware_now(now: datetime) -> datetime:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("Horário UTC com fuso é obrigatório")
    return now.astimezone(timezone.utc)


@dataclass(frozen=True)
class DemoOrderHypothesis:
    signal_id: str
    symbol: str
    side: str
    volume: Decimal
    stop: Decimal
    target: Decimal

    def __post_init__(self):
        if not isinstance(self.signal_id, str) or not self.signal_id.strip():
            raise ValueError("ID de sinal obrigatório")
        if not isinstance(self.symbol, str) or not self.symbol.strip():
            raise ValueError("Símbolo obrigatório")
        if self.side not in ("buy", "sell"):
            raise ValueError("Direção inválida")
        for key in ("volume", "stop", "target"):
            _decimal(getattr(self, key), key)


@dataclass(frozen=True)
class BrokerSafetyLimits:
    """Independent safety guard; numbers are policy examples, not advice."""
    max_risk_equity_fraction: Decimal = Decimal("0.005")
    max_margin_free_fraction: Decimal = Decimal("0.20")
    fixed_slippage_fee_reserve: Decimal = Decimal("1")

    def __post_init__(self):
        for key in ("max_risk_equity_fraction", "max_margin_free_fraction"):
            value = _decimal(getattr(self, key), key)
            if value > 1:
                raise ValueError("Limite percentual inválido")
        _decimal(self.fixed_slippage_fee_reserve, "reserve", allow_zero=True)


@dataclass(frozen=True)
class BrokerPreflightReport:
    symbol: str
    signal_id: str
    status: str
    blockers: tuple[str, ...]
    account_currency: str | None
    entry_bid: Decimal | None
    entry_ask: Decimal | None
    theoretical_loss_account_currency: Decimal | None
    estimated_margin_account_currency: Decimal | None
    assumed_cost_reserve_account_currency: Decimal | None
    max_risk_budget_account_currency: Decimal | None
    number_open_positions: int | None
    number_pending_orders: int | None
    can_submit_orders: bool = False

    def __post_init__(self):
        if self.can_submit_orders:
            raise ValueError("Preflight jamais autoriza enviar ordens")


def _valid_spec(spec: Any, volume: Decimal) -> tuple[str, ...]:
    if spec is None:
        return ("CONTRATO_INDISPONIVEL",)
    try:
        mn = _decimal(getattr(spec, "volume_min", None), "volume_min")
        mx = _decimal(getattr(spec, "volume_max", None), "volume_max")
        step = _decimal(getattr(spec, "volume_step", None), "volume_step")
        tick = _decimal(getattr(spec, "trade_tick_size", None), "trade_tick_size")
        _decimal(getattr(spec, "point", None), "point")
        if mx < mn or volume < mn or volume > mx:
            return ("VOLUME_FORA_DA_FAIXA",)
        # Broker volume grids may have a non-step-multiple minimum.
        if (volume - mn) / step != ((volume - mn) / step).to_integral_value():
            return ("VOLUME_FORA_DO_PASSO",)
        return ()
    except ValueError:
        return ("ESPECIFICACOES_INVALIDAS",)


def _parse_stop_target(intent: DemoOrderHypothesis, *,
                       bid: Decimal, ask: Decimal, spec: Any) -> tuple[str, ...]:
    blocks: list[str] = []
    stop = _decimal(intent.stop, "stop")
    target = _decimal(intent.target, "target")
    if intent.side == "buy" and not (stop < bid and target > ask):
        blocks.append("STOP_ALVO_INCOMPATIVEIS_COMPRA")
    if intent.side == "sell" and not (stop > ask and target < bid):
        blocks.append("STOP_ALVO_INCOMPATIVEIS_VENDA")
    try:
        tick = _decimal(getattr(spec, "trade_tick_size", None), "tick_size")
        if any(p / tick != (p / tick).to_integral_value() for p in (stop, target)):
            blocks.append("STOP_ALVO_DESALINHADOS_TICK")
        point = _decimal(getattr(spec, "point", None), "point")
        raw_level = getattr(spec, "trade_stops_level", None)
        if type(raw_level) is not int or raw_level < 0:
            blocks.append("NIVEL_MINIMO_STOP_DESCONHECIDO")
        else:
            minimum = point * raw_level
            if intent.side == "buy":
                if bid - stop < minimum or target - bid < minimum:
                    blocks.append("STOP_ALVO_MUITO_PROXIMOS")
            else:
                if stop - ask < minimum or ask - target < minimum:
                    blocks.append("STOP_ALVO_MUITO_PROXIMOS")
    except ValueError:
        blocks.append("INSTRUMENTO_TICK_POINT_INVALIDO")
    return tuple(blocks)


def _verify_observed_tick(evidence: Any, *, symbol: str,
                          now: datetime, bid: Decimal, ask: Decimal,
                          spec: Any) -> tuple[str, ...]:
    """Cross-check recent reconciled live-clock evidence from capture().

    A stale prior snapshot or changed quote must not be mistaken for
    the same planned entry. Nothing here authorizes execution.
    """
    if evidence is None:
        return ("COTACAO_RECENTE_NAO_CONCILIADA",)
    if getattr(evidence, "symbol", None) != symbol or getattr(
            evidence, "connected_to_demo", False) is not True:
        return ("EVIDENCIA_ATIVO_OU_CONTA_INCOERENTE",)
    label = getattr(evidence, "clock_offset_label", None)
    if not isinstance(label, str) or "observado agora, provisório" not in label:
        return ("RELOGIO_AO_VIVO_NAO_VALIDADO",)
    try:
        stamp = datetime.fromisoformat(getattr(evidence, "quote_time_utc"))
        generated = datetime.fromisoformat(getattr(evidence, "generated_utc"))
        if (stamp.tzinfo is None or stamp.utcoffset() is None or
                generated.tzinfo is None or generated.utcoffset() is None):
            raise ValueError("naive timestamp")
    except (ValueError, TypeError, AttributeError):
        return ("HORARIOS_DA_EVIDENCIA_INVALIDOS",)
    now = _aware_now(now)
    age = (now - stamp.astimezone(timezone.utc)).total_seconds()
    created_age = (now - generated.astimezone(timezone.utc)).total_seconds()
    if not (0 <= age <= 15 and -3 <= created_age <= 15):
        return ("COTACAO_OU_ANALISE_DESATUALIZADA",)
    try:
        old_bid = _decimal(getattr(evidence, "quote_bid", None), "old_bid")
        old_ask = _decimal(getattr(evidence, "quote_ask", None), "old_ask")
        tick_size = _decimal(getattr(spec, "trade_tick_size", None), "tick_size")
        tolerance = max(5 * tick_size, (ask - bid) * 2)
    except ValueError:
        return ("EVIDENCIA_DE_PRECO_INVALIDA",)
    if old_ask < old_bid or abs(bid - old_bid) > tolerance or abs(ask - old_ask) > tolerance:
        return ("PRECO_MUDOU_DESDE_ANALISE",)
    # Reject abnormal spread relative to the SAME asset's closed-M5 ATR.
    # 25% is experimental and does not establish an optimal threshold.
    try:
        atr = _decimal(getattr(evidence, "m5_atr_price", None), "atr_m5")
    except ValueError:
        return ("ATR_M5_NAO_CONFIRMADO",)
    if (ask - bid) / atr > Decimal("0.25"):
        return ("SPREAD_ELEVADO_RELATIVO_ATR",)
    return ()


def estimate_demo_order(
    mt5: Any, intent: DemoOrderHypothesis, *,
    now: datetime,
    limits: BrokerSafetyLimits = BrokerSafetyLimits(),
    expected_server: str = EXPECTED_SERVER,
    market_evidence: Any = None,
) -> BrokerPreflightReport:
    """Safe broker-provided hypothetical loss/margin in account currency.

    A caller MUST NOT reinterpret status as order permission. This module
    never performs execution and always reports can_submit_orders=False.
    On failure to verify account identity: STOP, without reading symbols.
    """
    now = _aware_now(now)
    account = mt5.account_info()
    check_demo_account(account, mt5, expected_server=expected_server)

    def report(blocks=(), **kwargs):
        base = dict(
            symbol=intent.symbol, signal_id=intent.signal_id,
            status="BLOQUEADO_PARA_ORDENS",
            blockers=tuple(blocks),
            account_currency=None,
            entry_bid=None, entry_ask=None,
            theoretical_loss_account_currency=None,
            estimated_margin_account_currency=None,
            assumed_cost_reserve_account_currency=None,
            max_risk_budget_account_currency=None,
            number_open_positions=None, number_pending_orders=None,
            can_submit_orders=False,
        )
        base.update(kwargs)
        return BrokerPreflightReport(**base)

    blockers: list[str] = [
        "SESSOES_FERIADOS_NAO_VERIFICADOS",
        "CUSTOS_REAIS_E_SLIPPAGE_NAO_VERIFICADOS",
        "PERDA_DIARIA_REAL_NAO_RECONCILIADA",
        "EXECUCAO_DE_ORDENS_DESABILITADA",
    ]
    currency = getattr(account, "currency", None)
    if type(currency) is not str or len(currency) != 3 or not currency.isupper():
        blockers.append("MOEDA_DA_CONTA_NAO_CONFIRMADA")
        currency = None
    try:
        equity = _decimal(getattr(account, "equity", None), "equity")
        free_margin = _decimal(getattr(account, "margin_free", None), "margin_free")
    except ValueError:
        return report(
            blockers + ["EQUITY_OU_MARGEM_INDISPONIVEIS"], account_currency=currency
        )

    budget = equity * _decimal(limits.max_risk_equity_fraction, "max_risk")
    reserve = _decimal(limits.fixed_slippage_fee_reserve, "reserve", allow_zero=True)

    if getattr(account, "trade_allowed", None) is not True:
        blockers.append("CONTA_SEM_NEGOCIACAO_AUTORIZADA")
    if getattr(account, "trade_expert", None) is not True:
        blockers.append("AUTOTRADING_DESATIVADO")

    positions = mt5.positions_get()
    orders = mt5.orders_get()
    npos = None if positions is None else len(positions)
    norders = None if orders is None else len(orders)
    if positions is None or orders is None:
        blockers.append("POSICOES_OU_ORDENS_NAO_CONSULTAVEIS")
    elif positions or orders:
        # Phase 1 intentionally refuses to rely on unverified portfolio
        # reservations or on the assumed ownership of existing positions.
        blockers.append("EXPOSICAO_EXISTENTE_REQUER_RECONCILIACAO")

    if not mt5.symbol_select(intent.symbol, True):
        return report(blockers + ["ATIVO_NAO_SELECIONAVEL"],
                      account_currency=currency,
                      max_risk_budget_account_currency=budget,
                      assumed_cost_reserve_account_currency=reserve,
                      number_open_positions=npos, number_pending_orders=norders)

    spec = mt5.symbol_info(intent.symbol)
    blockers.extend(_valid_spec(spec, _decimal(intent.volume, "volume")))
    if spec is None:
        return report(blockers, account_currency=currency,
                      max_risk_budget_account_currency=budget,
                      assumed_cost_reserve_account_currency=reserve,
                      number_open_positions=npos, number_pending_orders=norders)
    mode_full = getattr(mt5, "SYMBOL_TRADE_MODE_FULL", None)
    if type(mode_full) is not int or getattr(spec, "trade_mode", None) != mode_full:
        blockers.append("MODO_ATIVO_NAO_NEGOCIAVEL")

    tick = mt5.symbol_info_tick(intent.symbol)
    if tick is None:
        return report(blockers + ["COTACAO_NAO_DISPONIVEL"],
                      account_currency=currency,
                      max_risk_budget_account_currency=budget,
                      assumed_cost_reserve_account_currency=reserve,
                      number_open_positions=npos, number_pending_orders=norders)
    try:
        bid = _decimal(getattr(tick, "bid", None), "bid")
        ask = _decimal(getattr(tick, "ask", None), "ask")
    except ValueError:
        return report(blockers + ["BID_ASK_INVALIDO"],
                      account_currency=currency,
                      max_risk_budget_account_currency=budget,
                      assumed_cost_reserve_account_currency=reserve,
                      number_open_positions=npos, number_pending_orders=norders)
    if ask < bid:
        blockers.append("SPREAD_INVERTIDO")
    blockers.extend(_parse_stop_target(intent, bid=bid, ask=ask, spec=spec))
    blockers.extend(_verify_observed_tick(
        market_evidence, symbol=intent.symbol, now=now, bid=bid, ask=ask,
        spec=spec
    ))

    side_code = getattr(
        mt5, "ORDER_TYPE_BUY" if intent.side == "buy" else "ORDER_TYPE_SELL", None
    )
    if type(side_code) is not int:
        blockers.append("CODIGO_LADO_MT5_INDISPONIVEL")
    planned_entry = ask if intent.side == "buy" else bid
    loss = margin = None
    if "CODIGO_LADO_MT5_INDISPONIVEL" not in blockers:
        # Broker calculates P&L in account currency, including any
        # live currency conversion. It is NOT a worst-case guaranteed loss.
        try:
            raw_profit = mt5.order_calc_profit(
                side_code, intent.symbol, float(intent.volume),
                float(planned_entry), float(intent.stop)
            )
            if raw_profit is None or isinstance(raw_profit, bool):
                raise ValueError("No result")
            profit = Decimal(str(raw_profit))
            if not profit.is_finite() or profit >= 0:
                raise ValueError("Stop P&L not negative")
            loss = -profit
        except (ValueError, TypeError, ArithmeticError, AttributeError, RuntimeError, OSError):
            blockers.append("CALCULO_PERDA_MT5_INDISPONIVEL")
        try:
            raw_margin = mt5.order_calc_margin(
                side_code, intent.symbol, float(intent.volume),
                float(planned_entry)
            )
            margin = _decimal(raw_margin, "margin")
        except (ValueError, TypeError, ArithmeticError, AttributeError):
            blockers.append("CALCULO_MARGEM_MT5_INDISPONIVEL")

    if loss is not None and loss + reserve > budget:
        blockers.append("RISCO_TEORICO_MAIS_RESERVA_EXCEDE_LIMITE")
    if margin is not None and margin > free_margin * limits.max_margin_free_fraction:
        blockers.append("MARGEM_ESTIMADA_EXCEDE_LIMITE")
    # Not a verified fee/swap schedule or fill simulation; no order_send.
    return report(
        blockers, account_currency=currency,
        entry_bid=bid, entry_ask=ask,
        theoretical_loss_account_currency=loss,
        estimated_margin_account_currency=margin,
        assumed_cost_reserve_account_currency=reserve,
        max_risk_budget_account_currency=budget,
        number_open_positions=npos, number_pending_orders=norders
    )
