"""SMC Trading Agent — single Windows entry point for integrated research.

This RELEASE CANDIDATE deliberately NEVER sends orders. Integrated
tests, risk math and paper replay use fictional inputs; live XM DEMO
monitoring is read-only. The presence of a signal is not permission
to trade.

The --validar-tudo command exercises all local tests, synthetic
entry/exit, and synthetic risk examples in one user action.
"""
from __future__ import annotations

import argparse
from pathlib import Path
import subprocess
import sys


def validate_all(*, root: Path | None = None) -> int:
    """Run the complete offline suite, then both fabricated examples."""
    root = root or Path(__file__).resolve().parents[1]
    print("=" * 67, flush=True)
    print("SMC TRADING AGENT — VALIDACAO UNIFICADA / SOMENTE OFFLINE", flush=True)
    print("Zero conexoes MT5, zero ordens. Exemplos usam dados ficticios.", flush=True)
    print("=" * 67, flush=True)
    commands = (
        ("TESTES AUTOMATICOS", [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"]),
        ("CICLO FICTICIO DE ABERTURA/FECHAMENTO", [sys.executable, "-m", "smc_agent.paper_execution"]),
        ("ORCAMENTO FICTICIO DE RISCO", [sys.executable, "-m", "smc_agent.multi_risk"]),
        ("PREFLIGHT E REINICIO SIMULADOS", [sys.executable, "-m", "smc_agent.dry_run_pipeline"]),
    )
    for label, argv in commands:
        print(f"\n--- {label} ---", flush=True)
        result = subprocess.run(argv, cwd=str(root), check=False)
        if result.returncode != 0:
            print(f"\nFALHOU: {label}. Nenhum monitor foi iniciado.", flush=True)
            return result.returncode
    print("\n" + "=" * 67, flush=True)
    print("VALIDACAO OFFLINE CONCLUIDA: TESTES E TRES ENSAIOS FICTICIOS OK.", flush=True)
    print("Isso NAO comprova lucro, execucao na corretora ou sistema final.", flush=True)
    print("Nenhuma ordem enviada.", flush=True)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="SMC Agent unificado: XM DEMO monitor read-only + testes offline"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--validar-tudo", action="store_true",
                      help="Executar TODOS os testes e simulações fictícias")
    mode.add_argument("--monitor-demo", action="store_true",
                      help="Abrir o leitor SMC/Fibonacci multiativos XM DEMO SEM ORDENS")
    mode.add_argument("--status", action="store_true",
                      help="Mostrar capacidades e restrições verificáveis")
    parser.add_argument("--intervalo",type=int,default=30,
                        help="Segundos entre atualizações no modo monitor")
    args = parser.parse_args(argv)
    if args.validar_tudo:
        return validate_all()
    if args.status:
        print(
            "SMC AGENT — RELEASE CANDIDATE UNIFICADA\n"
            "SMC H1/M5: gatilho experimental original preservado\n"
            "Estrutura H4/H1/M30/M15/M5: contexto adicional, nao filtra sinais\n"
            "Fibonacci: contexto OTE, nao obrigatorio para sinais\n"
            "Monitor multiativos XMGlobal-MT5 5: somente conta DEMO\n"
            "Diagnostico de cotacao/spread: somente leitura\n"
            "Preflight XM DEMO: order_calc_profit/margin, posicoes/ordens (read-only)\n"
            "Preflight EXIGE evidencias recentes de preco, sessao continua bloqueada\n"
            "Intencoes em SQLite: deduplicacao e quarentena apos reinicio\n"
            "Ciclo paper e orcamento de risco: dados ficticios\n"
            "MFP: adaptador preliminar nao homologado\n"
            "Enviar/fechar ordens: NAO IMPLEMENTADO NESTA CANDIDATA\n"
            "Lucratividade: NAO DEMONSTRADA\n"
        )
        return 0
    # Connection takes place exclusively inside the older read-only monitor
    # which rejects real and unknown accounts before it reads any market.
    from .multi_monitor import monitor_many
    monitor_many(interval=args.intervalo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
