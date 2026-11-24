"""Dimensionamento conservador: recusar operações impossíveis de proteger."""
from dataclasses import dataclass


@dataclass(frozen=True)
class RiskRules:
    risk_percent: float = 1.0
    max_trade_usd: float = 5.0
    reserve_usd: float = 0.15

    def __post_init__(self):
        if not 0 < self.risk_percent <= 5 or self.max_trade_usd <= 0 or self.reserve_usd < 0:
            raise ValueError("Limites de risco inválidos")


def allowed_loss(equity_usd: float, rules: RiskRules = RiskRules()) -> float:
    if equity_usd <= 0:
        return 0.0
    return max(0.0, min(equity_usd * rules.risk_percent / 100, rules.max_trade_usd) - rules.reserve_usd)


def authorize_minimum_lot(equity_usd: float, worst_case_loss_usd: float,
                          rules: RiskRules = RiskRules()) -> bool:
    """worst_case_loss inclui risco até stop, custos e margem de deslizamento."""
    return worst_case_loss_usd > 0 and worst_case_loss_usd <= allowed_loss(equity_usd, rules)
