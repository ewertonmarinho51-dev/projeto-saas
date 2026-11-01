"""
Motor de IA falso para o E2E: fala `POST /v1/chat/completions`, como a OpenAI.

    python tests_rls/motor_falso.py --porta 8099

O worker do CI chega aqui pela URL de gateway que o produto já tem
(`OMNIROUTE_BASE_URL`), então nada no código de produção sabe que existe teste:
prompt, fila, gravação e RLS rodam de verdade, e só a resposta do modelo é
fixa. Demora um pouco de propósito, para o E2E ver o progresso e recarregar a
página com a geração em curso. Prompt com `FALHA-MOTOR-E2E` recebe 400 na
primeira vez e resposta na segunda: é a prova de "Tentar novamente".
"""

from __future__ import annotations

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MARCA_DE_FALHA = "FALHA-MOTOR-E2E"
TEXTO = ("# Documento de Formalização da Demanda\n\n"
         "## 1. Necessidade\n\nTexto redigido pelo motor falso do E2E.\n\n[[TABELA_ITENS]]\n")
_ja_falhou = {"sim": False}


class Motor(BaseHTTPRequestHandler):
    def _responder(self, status: int, corpo: dict) -> None:
        dados = json.dumps(corpo).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(dados)))
        self.end_headers()
        self.wfile.write(dados)

    def do_POST(self) -> None:  # noqa: N802 — nome da stdlib
        pedido = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
        prompt = json.dumps(pedido.get("messages") or [], ensure_ascii=False)
        if MARCA_DE_FALHA in prompt and not _ja_falhou["sim"]:
            _ja_falhou["sim"] = True
            self._responder(400, {"error": {"message": "pedido recusado", "type": "invalid_request_error"}})
            return
        time.sleep(4)
        self._responder(200, {
            "id": "resp-falsa", "object": "chat.completion", "created": int(time.time()),
            "model": pedido.get("model") or "modelo-falso",
            "choices": [{"index": 0, "finish_reason": "stop",
                         "message": {"role": "assistant", "content": TEXTO}}],
            "usage": {"prompt_tokens": 10, "completion_tokens": 10, "total_tokens": 20}})

    def log_message(self, *_args) -> None:
        pass


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--porta", type=int, default=8099)
    ThreadingHTTPServer(("127.0.0.1", parser.parse_args().porta), Motor).serve_forever()
