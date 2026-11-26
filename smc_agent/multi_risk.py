"""Synthetic risk sizing + portfolio guards for FUTURE XM demo automation.

NO MetaTrader5 import, no account request, no orders, no broker calls.
The values passed in are caller-supplied RESEARCH examples. It MUST NOT
be treated as executable authority, even when a size is returned.

Tick value, account currency, margin, fees, slippage, execution, trade
mode, broker sessions and actual existing positions must be independently
verified on XM DEMO before future trade permission can be considered.
A stop-loss is not a guaranteed maximum loss (gaps/slippage).
"""
from __future__ import annotations
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_FLOOR
from typing import Any


def dec(value: Any, name: str, *, nonnegative: bool = False) -> Decimal:
    if isinstance(value, bool):
        raise ValueError(f"{name}: boolean not allowed")
    try:
        result = Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        raise ValueError(f"{name}: invalid number") from None
    if not result.is_finite() or (result < 0 if nonnegative else result <= 0):
        raise ValueError(f"{name}: out of range")
    return result


@dataclass(frozen=True)
class ResearchContract:
    symbol: str
    currency_for_tick_value: str
    tick_size: Decimal
    tick_value_loss_per_lot: Decimal
    volume_min: Decimal
    volume_max: Decimal
    volume_step: Decimal

    def __post_init__(self):
        if not isinstance(self.symbol, str) or not self.symbol:
            raise ValueError("Instrument symbol required")
        if not isinstance(self.currency_for_tick_value, str) or len(self.currency_for_tick_value) != 3 or not self.currency_for_tick_value.isupper():
            raise ValueError("Verified tick-value currency required")
        for field in ("tick_size", "tick_value_loss_per_lot",
                      "volume_min", "volume_max", "volume_step"):
            dec(getattr(self, field), field)
        if dec(self.volume_min, "volume_min") > dec(self.volume_max, "volume_max"):
            raise ValueError("Invalid instrument volume range")


@dataclass(frozen=True)
class HypotheticalLimits:
    """Fictional money limits; this does NOT inspect account equity."""
    equity: Decimal
    currency: str
    risk_fraction_per_trade: Decimal = Decimal("0.005")    # 0.5% hypothetical
    daily_loss_fraction: Decimal = Decimal("0.02")          # 2% hypothetical
    max_trade_amount: Decimal = Decimal("25")
    max_portfolio_reserved: Decimal = Decimal("60")
    max_positions: int = 2
    max_positions_per_symbol: int = 1
    fixed_cost_reserve: Decimal = Decimal("1")
    extra_cost_reserve_per_lot: Decimal = Decimal("3")

    def __post_init__(self):
        if not isinstance(self.currency, str) or len(self.currency) != 3 or not self.currency.isupper():
            raise ValueError("Hypothetical account currency required")
        for field in ("equity", "risk_fraction_per_trade", "daily_loss_fraction",
                      "max_trade_amount", "max_portfolio_reserved"):
            dec(getattr(self, field), field)
        for field in ("fixed_cost_reserve", "extra_cost_reserve_per_lot"):
            dec(getattr(self, field), field, nonnegative=True)
        for field in ("risk_fraction_per_trade", "daily_loss_fraction"):
            if dec(getattr(self, field), field) > 1:
                raise ValueError("Risk percentage cannot exceed 100%")
        if type(self.max_positions) is not int or not 1 <= self.max_positions <= 20:
            raise ValueError("Invalid maximum simultaneous positions")
        if type(self.max_positions_per_symbol) is not int or not 1 <= self.max_positions_per_symbol <= self.max_positions:
            raise ValueError("Invalid per-symbol position maximum")


@dataclass(frozen=True)
class HypotheticalPortfolio:
    """Caller-supplied state; NOT live positions and NOT persistent yet."""
    realized_loss_today: Decimal = Decimal("0")
    reserved_estimated_loss: Decimal = Decimal("0")
    active_symbols: tuple[str, ...] = ()
    seen_signal_ids: frozenset[str] = frozenset()
    emergency_stop: bool = False
    connection_healthy: bool = True

    def __post_init__(self):
        dec(self.realized_loss_today, "realized_loss_today", nonnegative=True)
        dec(self.reserved_estimated_loss, "reserved_estimated_loss", nonnegative=True)
        if (type(self.emergency_stop) is not bool or
                type(self.connection_healthy) is not bool):
            raise ValueError("Invalid safety flags")
        if not isinstance(self.active_symbols, tuple) or any(not s or not isinstance(s, str) for s in self.active_symbols):
            raise ValueError("Invalid active symbols")
        if not isinstance(self.seen_signal_ids, frozenset):
            raise ValueError("Signal IDs must be immutable set")


@dataclass(frozen=True)
class ResearchIntent:
    signal_id: str
    symbol: str
    side: str
    bid: Decimal
    ask: Decimal
    stop: Decimal

    def __post_init__(self):
        if not self.signal_id or not self.symbol or self.side not in ("buy", "sell"):
            raise ValueError("Research signal identity or direction invalid")
        bid, ask, stop = (
            dec(self.bid, "bid"), dec(self.ask, "ask"), dec(self.stop, "stop")
        )
        if ask < bid:
            raise ValueError("Crossed quotes")
        entry = ask if self.side == "buy" else bid
        if self.side == "buy" and stop >= entry:
            raise ValueError("BUY stop must be below Ask entry")
        if self.side == "sell" and stop <= entry:
            raise ValueError("SELL stop must be above Bid entry")


@dataclass(frozen=True)
class ResearchRiskDecision:
    status: str
    block_codes: tuple[str, ...]
    symbol: str
    signal_id: str
    research_lots: Decimal | None
    theoretical_loss_to_stop: Decimal | None
    illustrative_cost_reserve: Decimal | None
    illustrative_total: Decimal | None
    available_budget: Decimal
    currency: str
    can_submit_orders: bool = False

    def __post_init__(self):
        if self.can_submit_orders:
            raise ValueError("v0.14 never authorizes broker orders")


def calculate_hypothetical_size(
    intent: ResearchIntent,
    contract: ResearchContract,
    limits: HypotheticalLimits,
    portfolio: HypotheticalPortfolio = HypotheticalPortfolio(),
) -> ResearchRiskDecision:
    """Fail closed. Return only a research size, never executable permission.

    BUY entry is Ask, SELL entry is Bid. A planned stop is assumed to be
    touched at its quoted price, which is NOT a guaranteed actual fill.
    An illustrative reserve must be supplied for additional costs, but
    cannot bound real gap/slippage losses.
    """
    blockers = []
    if intent.symbol != contract.symbol:
        blockers.append("SIMBOLO_DIVERGENTE")
    if limits.currency != contract.currency_for_tick_value:
        blockers.append("MOEDA_VALOR_TICK_NAO_COMPATIVEL")
    if portfolio.emergency_stop:
        blockers.append("PARADA_EMERGENCIA_ATIVA")
    if not portfolio.connection_healthy:
        blockers.append("CONEXAO_NAO_CONFIAVEL")
    if intent.signal_id in portfolio.seen_signal_ids:
        blockers.append("SINAL_DUPLICADO")
    if len(portfolio.active_symbols) >= limits.max_positions:
        blockers.append("LIMITE_POSICOES_SIMULTANEAS")
    if portfolio.active_symbols.count(intent.symbol) >= limits.max_positions_per_symbol:
        blockers.append("LIMITE_POSICOES_POR_ATIVO")

    eq = dec(limits.equity, "equity")
    realized = dec(portfolio.realized_loss_today, "realized_loss_today", nonnegative=True)
    reserved = dec(portfolio.reserved_estimated_loss, "reserved_estimated_loss", nonnegative=True)
    daily_room = eq * dec(limits.daily_loss_fraction, "daily_loss_fraction") - realized - reserved
    total_room = dec(limits.max_portfolio_reserved, "max_portfolio_reserved") - reserved
    individual_room = min(
        eq * dec(limits.risk_fraction_per_trade, "risk_fraction_per_trade"),
        dec(limits.max_trade_amount, "max_trade_amount"),
    )
    if daily_room <= 0:
        blockers.append("PERDA_DIARIA_OU_RESERVAS_NO_LIMITE")
    if total_room <= 0:
        blockers.append("EXPOSICAO_RESERVADA_NO_LIMITE")
    budget = max(Decimal("0"), min(daily_room, total_room, individual_room))

    def blocked(codes: list[str]) -> ResearchRiskDecision:
        return ResearchRiskDecision(
            "BLOQUEADO", tuple(codes), intent.symbol, intent.signal_id,
            None, None, None, None, budget, limits.currency
        )

    if blockers:
        return blocked(blockers)

    entry = dec(intent.ask if intent.side == "buy" else intent.bid, "entry")
    stop = dec(intent.stop, "stop")
    tick = dec(contract.tick_size, "tick_size")
    # Validate independent bid/ask and stop against the instrument's own
    # tick grid; never round a hypothetical executable quote silently.
    if any(q / tick != (q / tick).to_integral_value() for q in (
            dec(intent.bid, "bid"), dec(intent.ask, "ask"))):
        return blocked(["COTACAO_FORA_TICK_SIZE"])
    if stop / tick != (stop / tick).to_integral_value():
        return blocked(["STOP_FORA_TICK_SIZE"])
    stop_distance = abs(entry - stop)
    loss_per_lot = stop_distance / tick * dec(
        contract.tick_value_loss_per_lot, "tick_value_loss_per_lot"
    )
    extra_per_lot = dec(
        limits.extra_cost_reserve_per_lot, "extra_cost_reserve_per_lot",
        nonnegative=True
    )
    fixed = dec(limits.fixed_cost_reserve, "fixed_cost_reserve", nonnegative=True)
    if budget <= fixed:
        return blocked(["ORCAMENTO_NAO_COBRE_RESERVA"])

    volume_min = dec(contract.volume_min, "volume_min")
    volume_max = dec(contract.volume_max, "volume_max")
    volume_step = dec(contract.volume_step, "volume_step")
    theoretical_max = (budget - fixed) / (loss_per_lot + extra_per_lot)
    cap = min(volume_max, theoretical_max)
    # MT5 instruments may define min=.01, step=.003: compute from min
    # + n*step rather than assuming min itself is a multiple of step.
    if cap < volume_min:
        return blocked(["LOTE_MINIMO_EXCEDE_ORCAMENTO"])
    steps = ((cap - volume_min) / volume_step).to_integral_value(rounding=ROUND_FLOOR)
    volume = volume_min + volume_step * steps
    planned_loss = loss_per_lot * volume
    reserved_cost = fixed + extra_per_lot * volume
    total = planned_loss + reserved_cost
    if total > budget:
        raise AssertionError("Risk budget invariant violated")
    return ResearchRiskDecision(
        "PESQUISA_APENAS", (), intent.symbol, intent.signal_id,
        volume, planned_loss, reserved_cost, total, budget, limits.currency
    )


def fabricated_example() -> str:
    """Entirely fictional: NO account balance fetched and NO orders sent."""
    contract = ResearchContract(
        symbol="EXEMPLO", currency_for_tick_value="USD",
        tick_size=Decimal("0.01"), tick_value_loss_per_lot=Decimal("1"),
        volume_min=Decimal("0.01"), volume_max=Decimal("20"),
        volume_step=Decimal("0.001"),
    )
    limits = HypotheticalLimits(equity=Decimal("10000"), currency="USD")
    intent = ResearchIntent(
        "FICTICIO-001", "EXEMPLO", "buy",
        bid=Decimal("100.00"), ask=Decimal("100.20"),
        stop=Decimal("99.00"),
    )
    result = calculate_hypothetical_size(intent, contract, limits)
    return (
        "RISCOS HIPOTETICOS — DADOS INVENTADOS, NENHUMA CONTA CONSULTADA\n"
        f"Status: {result.status}\n"
        f"Lotes APENAS para pesquisa: {result.research_lots}\n"
        f"Perda teorica ate stop: {result.theoretical_loss_to_stop} {result.currency}\n"
        f"Reserva ilustrativa: {result.illustrative_cost_reserve} {result.currency}\n"
        f"Total orcado (nao perda maxima garantida): {result.illustrative_total} {result.currency}\n"
        f"Budget ficticio: {result.available_budget} {result.currency}\n"
        "Execucao automatica: BLOQUEADA. Ordens enviadas: 0."
    )


if __name__ == "__main__":
    print(fabricated_example())
