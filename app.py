"""Painel de Investimentos - ponto de entrada.

Uso:
    python app.py                 abre o painel no navegador
    python app.py --porta 8080    escolhe a porta
    python app.py --sem-navegador nao abre o navegador (util para servidor)
"""

from __future__ import annotations

import argparse
import logging
import socket
import sys
import threading
import webbrowser
from pathlib import Path

from painel.api import criar_app

# No .exe gerado pelo PyInstaller (modo onefile), __file__ aponta para a pasta
# temporaria de extracao (apagada ao fechar) - usar sys.executable para que
# a pasta "dados" fique ao lado do .exe de verdade e persista entre execucoes.
RAIZ = (Path(sys.executable).resolve().parent if getattr(sys, "frozen", False)
        else Path(__file__).resolve().parent)


def porta_livre(preferida: int) -> int:
    """Usa a porta pedida; se estiver ocupada, pega a proxima livre."""
    for porta in range(preferida, preferida + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("127.0.0.1", porta))
                return porta
            except OSError:
                continue
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> int:
    p = argparse.ArgumentParser(description="Painel de Investimentos")
    p.add_argument("--porta", type=int, default=5000)
    p.add_argument("--sem-navegador", action="store_true")
    p.add_argument("--debug", action="store_true")
    p.add_argument("--producao", action="store_true",
                    help="usa o Waitress em vez do servidor de desenvolvimento")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(asctime)s  %(levelname)-7s %(message)s",
        datefmt="%H:%M:%S",
    )
    logging.getLogger("werkzeug").setLevel(logging.WARNING)

    porta = porta_livre(args.porta)
    url = f"http://127.0.0.1:{porta}"

    app = criar_app(RAIZ / "dados")

    print()
    print("  PAINEL DE INVESTIMENTOS")
    print("  " + "-" * 46)
    print(f"  Endereco : {url}")
    print(f"  Dados    : {RAIZ / 'dados' / 'investimentos.db'}")
    print("  Taxas    : API publica do Banco Central (SGS + Focus)")
    print("  Encerrar : Ctrl+C")
    print()

    if not args.sem_navegador:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()

    try:
        if args.producao:
            from waitress import serve
            serve(app, host="127.0.0.1", port=porta)
        else:
            app.run(host="127.0.0.1", port=porta, debug=args.debug, use_reloader=False,
                    threaded=True)
    except KeyboardInterrupt:
        print("\n  Painel encerrado.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
