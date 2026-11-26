"""Purely observational multi-timeframe signal research labels."""
from dataclasses import replace
import unittest

from smc_agent.multi_timeframe import (
    FrameObservation, MultiTimeframeContext
)
from smc_agent.mtf_research import classify_signal_context


LABELS = ("H4","H1","M30","M15","M5")


def context(biases, *, unavailable=()):
    frames=[]
    for tf, bias in zip(LABELS, biases):
        missing=tf in unavailable
        frames.append(FrameObservation(
            tf, "NÃO AVALIADO" if missing else bias,
            None, None, "INDISPONIVEL" if missing else "OK"
        ))
    return MultiTimeframeContext(tuple(frames))


class MTFSignalContextTests(unittest.TestCase):
    def test_full_buy_confluence_is_only_a_research_tag(self):
        item=classify_signal_context(
            "buy",context(("ALTA","ALTA","ALTA","ALTA","BAIXA"))
        )
        self.assertEqual(item.label,"CONFLUENCIA_COMPLETA_OBSERVADA")
        self.assertEqual(item.higher_tf,"H4_A_FAVOR")
        self.assertEqual(item.intermediates,"AMBOS_A_FAVOR")
        self.assertEqual(item.opposed,("M5",))
        self.assertFalse(item.can_submit_orders)

    def test_full_sell_confluence_is_only_a_research_tag(self):
        item=classify_signal_context(
            "sell",context(("BAIXA","BAIXA","BAIXA","BAIXA","ALTA"))
        )
        self.assertEqual(item.label,"CONFLUENCIA_COMPLETA_OBSERVADA")
        self.assertEqual(item.matched,("H4","H1","M30","M15"))

    def test_h4_opposes_signal_regardless_of_intermediates(self):
        item=classify_signal_context(
            "buy",context(("BAIXA","ALTA","ALTA","ALTA","ALTA"))
        )
        self.assertEqual(item.label,"CONTRA_FLUXO_H4")
        self.assertEqual(item.higher_tf,"H4_CONTRA")
        self.assertFalse(item.can_submit_orders)

    def test_missing_h4_is_not_assumed_to_be_neutral(self):
        item=classify_signal_context(
            "buy",context(("ALTA","ALTA","ALTA","ALTA","ALTA"),
                          unavailable=("H4",))
        )
        self.assertEqual(item.label,"COBERTURA_INSUFICIENTE")
        self.assertEqual(item.higher_tf,"H4_INDISPONIVEL")
        self.assertEqual(item.unavailable,("H4",))
        self.assertNotIn("H4",item.neutral)

    def test_missing_intermediate_prevents_full_confluence_tag(self):
        item=classify_signal_context(
            "buy",context(("ALTA","ALTA","ALTA","ALTA","ALTA"),
                          unavailable=("M15",))
        )
        self.assertEqual(item.intermediates,"INTERMEDIARIOS_INCOMPLETOS")
        self.assertEqual(item.label,"COBERTURA_INSUFICIENTE")

    def test_intermediates_both_against_signal(self):
        item=classify_signal_context(
            "buy",context(("ALTA","ALTA","BAIXA","BAIXA","ALTA"))
        )
        self.assertEqual(item.intermediates,"AMBOS_CONTRA")
        self.assertEqual(item.label,"CONFLUENCIA_NAO_CONFIRMADA")

    def test_one_intermediate_in_favor_other_neutral(self):
        item=classify_signal_context(
            "sell",context(("BAIXA","BAIXA","BAIXA","NEUTRO","BAIXA"))
        )
        self.assertEqual(item.intermediates,"MAIS_A_FAVOR")
        self.assertEqual(item.label,"CONFLUENCIA_COMPLETA_OBSERVADA")

    def test_h4_neutral_is_not_countertrend(self):
        item=classify_signal_context(
            "buy",context(("NEUTRO","ALTA","ALTA","ALTA","ALTA"))
        )
        self.assertEqual(item.higher_tf,"H4_NEUTRO")
        self.assertEqual(item.label,"CONFLUENCIA_NAO_CONFIRMADA")

    def test_invalid_side_or_context_rejected(self):
        with self.assertRaises(ValueError):
            classify_signal_context("hold",context(("ALTA",)*5))
        with self.assertRaises(TypeError):
            classify_signal_context("buy",None)

    def test_never_authorizes_broker_orders_even_if_full_confluence(self):
        item=classify_signal_context(
            "buy",context(("ALTA",)*5)
        )
        with self.assertRaisesRegex(ValueError,"never authorizes"):
            replace(item,can_submit_orders=True)
        self.assertIs(item.to_log()["orders_authorized"],False)
        self.assertEqual(item.to_log()["label"],"CONFLUENCIA_COMPLETA_OBSERVADA")


if __name__ == "__main__":
    unittest.main()
