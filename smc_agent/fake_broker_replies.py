"""Classify hypothetical broker response paths without submitting orders.

No MT5 SDK import and no claimed real broker fill. Unknown, partial and
contradictory responses NEVER trigger automatic retry or an assumption
that a position was closed. They require external account reconciliation.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation


def _lots(x: object) -> Decimal:
    if isinstance(x, bool):
        raise ValueError("Volume inválido")
    try:
        result=Decimal(str(x))
    except (InvalidOperation, ValueError, TypeError):
        raise ValueError("Volume inválido") from None
    if not result.is_finite() or result < 0:
        raise ValueError("Volume inválido")
    return result


@dataclass(frozen=True)
class FakeBrokerReply:
    """Test-fixture only. Any reference is a made-up response code."""
    signal_id: str
    symbol: str
    requested_lots: Decimal
    status: str
    acknowledged_lots: Decimal | None = None
    synthetic_ticket: str | None = None

    def __post_init__(self):
        if (not isinstance(self.signal_id,str) or not self.signal_id
                or not isinstance(self.symbol,str) or not self.symbol):
            raise ValueError("Identidade inválida")
        if _lots(self.requested_lots)<=0:
            raise ValueError("Solicitação de volume inválida")
        if self.status not in ("FAKE_FILLED","FAKE_PARTIAL",
                               "FAKE_REJECTED","FAKE_TIMEOUT","FAKE_UNKNOWN"):
            raise ValueError("Status de resposta simulada inválido")
        if self.acknowledged_lots is not None:
            _lots(self.acknowledged_lots)


@dataclass(frozen=True)
class ReplyDisposition:
    signal_id: str
    state: str
    reason: str
    requires_position_reconciliation: bool
    automatic_retry_allowed: bool = False
    can_submit_orders: bool = False

    def __post_init__(self):
        if self.automatic_retry_allowed or self.can_submit_orders:
            raise ValueError("Mock response cannot authorize any broker action")


def classify_fake_broker_reply(reply: FakeBrokerReply, *,
                               expected_symbol: str,
                               expected_signal_id: str) -> ReplyDisposition:
    """Never trust a response as proof of account position without reconcile."""
    def output(state, reason, reconcile):
        return ReplyDisposition(
            reply.signal_id, state, reason, reconcile
        )

    if reply.signal_id!=expected_signal_id or reply.symbol!=expected_symbol:
        return output("QUARENTENA","Identidade ou símbolo divergente",True)
    lots=reply.acknowledged_lots
    if lots is not None and lots>reply.requested_lots:
        return output("QUARENTENA","Volume informado excede solicitado",True)

    if reply.status in ("FAKE_TIMEOUT","FAKE_UNKNOWN"):
        return output(
            "QUARENTENA","Resposta ausente/indeterminada; NÃO repetir solicitação",True
        )
    if reply.status=="FAKE_REJECTED":
        if lots is not None and lots!=0:
            return output(
                "QUARENTENA","Resposta contraditória: rejeição com volume",True
            )
        return output("REJEICAO_FICTICIA","Solicitação fictícia rejeitada",False)
    if reply.status=="FAKE_PARTIAL":
        if lots is None or lots<=0 or lots>=reply.requested_lots:
            return output(
                "QUARENTENA","Quantidade parcial inconsistente",True
            )
        return output(
            "PARCIAL_FICTICIA_EXIGE_CONFERENCIA",
            "Exposição fictícia parcial; conferir posição antes de qualquer ação",True
        )
    # FAKE_FILLED, but no real brokerage evidence.
    if lots is None or lots!=reply.requested_lots or not reply.synthetic_ticket:
        return output("QUARENTENA","Confirmação fictícia incompleta",True)
    return output(
        "PREENCHIDA_FICTICIAMENTE_EXIGE_CONFERENCIA",
        "Simulação de fill: apenas reconciliação da conta provaria posição",True
    )
