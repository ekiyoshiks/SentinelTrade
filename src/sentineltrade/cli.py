"""Linha de comando: criar o banco, popular dados de exemplo e subir o servidor.

    python -m sentineltrade.cli init-db --seed
    python -m sentineltrade.cli run --port 8000
"""
from __future__ import annotations

import argparse
import logging

from .config import Configuracoes
from .servicos.sistema import Sistema


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="sentineltrade")
    sub = parser.add_subparsers(dest="comando", required=True)

    init = sub.add_parser("init-db", help="cria as tabelas (e opcionalmente popula dados de exemplo)")
    init.add_argument("--seed", action="store_true", help="popula investidores, ativos e usuários de exemplo")
    init.add_argument("--reset", action="store_true", help="apaga tudo antes de criar (CUIDADO)")

    esq = sub.add_parser("export-schema", help="imprime o DDL SQL (sqlite ou postgresql)")
    esq.add_argument("--dialeto", choices=["sqlite", "postgresql"], default="sqlite")

    run = sub.add_parser("run", help="sobe a API e o dashboard")
    run.add_argument("--host", default="127.0.0.1")
    run.add_argument("--port", type=int, default=8000)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    if args.comando == "export-schema":
        from .persistencia.banco import gerar_ddl
        print(gerar_ddl(args.dialeto), end="")
    elif args.comando == "init-db":
        sistema = Sistema(Configuracoes.de_ambiente())
        if args.reset:
            sistema.banco.apagar_tudo()
        sistema.banco.criar_tabelas()
        print("Tabelas criadas.")
        if args.seed:
            from .seed import popular, senha_demo
            resultado = popular(sistema)
            print(f"Dados de exemplo: {resultado['usuarios_criados']} (senha de demonstração: {senha_demo()})")
    else:
        import uvicorn
        uvicorn.run("sentineltrade.api.app:app_padrao", factory=True, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
