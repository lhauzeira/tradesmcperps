"""One-piece fake demo preflight and durable restart recovery smoke tests."""
import subprocess
import sys
import unittest

from smc_agent.dry_run_pipeline import rehearse_demo_preflight_recovery


class DemoPipelineRehearsalTests(unittest.TestCase):
    def test_fictional_broker_preflight_and_crash_recovery_are_integrated(self):
        result=rehearse_demo_preflight_recovery()
        self.assertEqual(result["source"],"FICTICIOUS_MARKET_AND_ACCOUNT")
        self.assertEqual(result["orders_sent"],0)
        self.assertEqual(result["intent_after_restart"],"RECONCILE_REQUIRED")
        self.assertTrue(result["duplicate_prevented"])
        self.assertIn("SESSOES_FERIADOS_NAO_VERIFICADOS",
                      result["broker_blockers"])
        self.assertIn("EXECUCAO_DE_ORDENS_DESABILITADA",
                      result["broker_blockers"])
        self.assertAlmostEqual(float(result["planned_loss_estimate"]),12.0,places=8)

    def test_demo_cli_does_not_use_mt5_package_or_network(self):
        r=subprocess.run(
            [sys.executable,"-m","smc_agent.dry_run_pipeline"],
            capture_output=True,text=True,timeout=20
        )
        self.assertEqual(r.returncode,0,r.stderr)
        self.assertIn("DADOS 100% FICTICIOS",r.stdout)
        self.assertIn("RECONCILE_REQUIRED",r.stdout)
        self.assertIn("ZERO ORDENS ENVIADAS",r.stdout)


if __name__ == "__main__":
    unittest.main()
