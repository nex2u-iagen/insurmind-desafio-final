"""Supervisor — intermediário entre usuário e sub-agentes especialistas.

Roteamento dinâmico do plano: com cliente LLM (planos ``openai``/``groq``/
``google``) o supervisor pede ao modelo os especialistas relevantes e uma
instrução individual por especialista; offline (ou quando o LLM falha/retorna
algo inválido) o plano cai para keywords determinísticas sem acento-sensível
(sem match → todos os especialistas do catálogo).
"""

from __future__ import annotations

import logging
import unicodedata
from typing import Any

from ..motor_llm.base import ChatJson
from .contrato import ContratoAgente
from .especialistas import NOMES_ESPECIALISTAS
from .estado import novo_status
from .registro import agente

logger = logging.getLogger(__name__)

ESPECIALISTAS = list(NOMES_ESPECIALISTAS)

PEDIDO_PADRAO = "Comparação padrão das duas apólices D&O (limites, coberturas, exclusões e condições)."

MAPA_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("limite", "limites"),
    ("franquia", "limites"),
    ("reten", "limites"),
    ("cobertura", "coberturas"),
    ("custo", "coberturas"),
    ("defesa", "coberturas"),
    ("exclus", "exclusoes"),
    ("ressalva", "exclusoes"),
    ("extens", "extensoes"),
    ("endosso", "extensoes"),
    ("condic", "condicoes"),
    ("dever", "condicoes"),
    ("obrigacao", "condicoes"),
    ("identific", "identificacao"),
    ("seguradora", "identificacao"),
    ("segurado", "identificacao"),
    ("vigencia", "identificacao"),
)


def _normalizar(texto: str) -> str:
    """Minúsculas sem acentos (``compare as retenções`` → ``compare as retencoes``)."""
    decomposto = unicodedata.normalize("NFD", texto.casefold())
    return "".join(caractere for caractere in decomposto if unicodedata.category(caractere) != "Mn")


@agente(rotulo="🎩 Supervisor", ordem=0, grupo="maestro")
class SupervisorAbertura:
    """Nó inicial: valida o pedido, roteia o plano e despacha os especialistas."""

    contrato = ContratoAgente(
        nome="supervisor_abertura",
        papel="Intermedia o usuário e a orquestra: valida o pedido, planeja e despacha os especialistas.",
        prompt_sistema=(
            "Você é o supervisor da orquestra de análise de apólices D&O. Valide o pedido do usuário, "
            "selecione os especialistas relevantes, redija uma instrução individual para cada um e "
            'responda SOMENTE JSON: {"especialistas": ["nome"], "instrucoes": {"nome": "instrução"}}. '
            f"Especialistas válidos (use exatamente, minúsculas e sem acentos): {', '.join(NOMES_ESPECIALISTAS)}."
        ),
        ferramentas=frozenset(),
    )

    def __init__(self, cliente: ChatJson | None = None, memoria: Any = None) -> None:
        """Recebe o cliente LLM opcional e a memória de análises anteriores.

        Args:
            cliente: Cliente do plano (``None`` → keywords offline).
            memoria: Fonte de memória (``None`` → sem contexto de histórico).
        """
        self.cliente = cliente
        self.memoria = memoria

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        caminhos = state.get("caminhos") or []
        if len(caminhos) < 2:
            raise ValueError("A comparação exige pelo menos duas apólices.")
        pedido = (state.get("pedido_usuario") or "").strip() or PEDIDO_PADRAO
        contexto = self._lembrancas(pedido)
        plano, instrucoes = self._planejar(pedido)
        logger.info(
            "Plano do supervisor provider=%s especialistas=%s lembrancas=%s",
            "llm" if self.cliente is not None else "regras",
            plano,
            len(contexto),
        )
        mensagem = (
            f"Supervisor: recebi o pedido '{pedido}' para {len(caminhos)} apólices. "
            f"Despachando especialistas em paralelo: {', '.join(plano)}."
        )
        return {
            "plano": plano,
            "pedido_usuario": pedido,
            "instrucoes": instrucoes,
            "memoria_contexto": contexto,
            "mensagem_supervisor": mensagem,
            "live_status": [novo_status("supervisor_abertura", "supervisor", mensagem)],
        }

    def _lembrancas(self, pedido: str) -> list[str]:
        """Consulta a memória de análises anteriores (melhor esforço)."""
        if self.memoria is None:
            return []
        try:
            return [str(texto) for texto in self.memoria.query(pedido, k=3)]
        except Exception as exc:  # noqa: BLE001 — memória nunca derruba a abertura.
            logger.warning("Consulta de memória no supervisor falhou (%s); seguindo sem contexto.", exc)
            return []

    def _planejar(self, pedido: str) -> tuple[list[str], dict[str, str]]:
        """Roteia o plano: LLM primeiro, keywords como fallback determinístico."""
        if self.cliente is not None:
            try:
                plano, instrucoes = self._planejar_llm(pedido)
                if plano:
                    return plano, instrucoes
                logger.warning("Roteamento LLM não devolveu plano válido; usando keywords.")
            except Exception as exc:  # noqa: BLE001 — roteamento nunca derruba a abertura.
                logger.warning("Roteamento por LLM falhou (%s); usando keywords.", exc)
        return self._planejar_keywords(pedido)

    def _planejar_llm(self, pedido: str) -> tuple[list[str], dict[str, str]]:
        """Pede ao modelo especialistas + instruções; nomes fora do catálogo são descartados.

        O casamento tolera acento/caixa (``Identificação`` → ``identificacao``) e
        aceita nomes descritivos que contenham exatamente um nome do catálogo
        (``Limites de responsabilidade`` → ``limites``).
        """
        resposta = self.cliente.chat_json(
            [
                {"role": "system", "content": self.contrato.prompt_sistema},
                {"role": "user", "content": pedido},
            ]
        )
        brutos = self._extrair_especialistas(resposta)
        if not brutos:
            chaves = sorted(resposta) if isinstance(resposta, dict) else type(resposta).__name__
            logger.warning("Roteamento LLM sem lista de especialistas (chaves=%s); usando keywords.", chaves)
            return [], {}
        selecionados: set[str] = set()
        for item in brutos:
            casado = self._casar_catalogo(str(item))
            if casado:
                selecionados.add(casado)
        if not selecionados:
            logger.warning("Roteamento LLM sem lista de especialistas (recebidos=%s); usando keywords.", brutos)
            return [], {}
        plano = [nome for nome in NOMES_ESPECIALISTAS if nome in selecionados]
        instrucoes_brutas = resposta.get("instrucoes") if isinstance(resposta, dict) else None
        if not isinstance(instrucoes_brutas, dict):
            instrucoes_brutas = {}
        instrucoes_norm = {_normalizar(str(chave)): valor for chave, valor in instrucoes_brutas.items()}
        instrucoes = {nome: str(instrucoes_norm.get(nome) or pedido) for nome in plano}
        return plano, instrucoes

    @staticmethod
    def _casar_catalogo(item: str) -> str | None:
        """Casa um nome vindo do LLM com o catálogo (normalizado ou por contenção única)."""
        normalizado = _normalizar(item.strip())
        if normalizado in NOMES_ESPECIALISTAS:
            return normalizado
        candidatos = [nome for nome in NOMES_ESPECIALISTAS if nome in normalizado]
        if len(candidatos) == 1:
            return candidatos[0]
        return None

    @staticmethod
    def _extrair_especialistas(resposta: Any) -> list[str] | None:
        """Normaliza a lista vinda do LLM (chaves ``especialistas``/``plan``/``plano``; string ou lista)."""
        if not isinstance(resposta, dict):
            return None
        for chave in ("especialistas", "plan", "plano"):
            valor = resposta.get(chave)
            if isinstance(valor, list):
                return [str(item) for item in valor]
            if isinstance(valor, str):
                return [parte.strip() for parte in valor.replace(";", ",").split(",") if parte.strip()]
        return None

    def _planejar_keywords(self, pedido: str) -> tuple[list[str], dict[str, str]]:
        """Roteamento offline: keywords do pedido (sem match → todos do catálogo)."""
        texto = _normalizar(pedido)
        selecionados = {nome for marca, nome in MAPA_KEYWORDS if marca in texto}
        plano = [nome for nome in NOMES_ESPECIALISTAS if nome in selecionados] or list(NOMES_ESPECIALISTAS)
        return plano, {nome: pedido for nome in plano}


@agente(rotulo="🎩 Supervisor", ordem=1, grupo="maestro")
class SupervisorEncerramento:
    """Nó final: consolida contagens e a decisão humana em mensagem ao usuário."""

    contrato = ContratoAgente(
        nome="supervisor_encerramento",
        papel="Consolida contagens, diferenças e a decisão humana na mensagem final ao usuário.",
        prompt_sistema=(
            "Você consolida documentos comparados, diferenças e a decisão humana em uma mensagem "
            "objetiva e técnica ao usuário. Nunca emita parecer jurídico."
        ),
        ferramentas=frozenset(),
    )

    def __call__(self, state: dict[str, Any]) -> dict[str, Any]:
        documentos = state.get("documentos") or []
        comparacao = state.get("comparacao") or []
        diferencas = [row for row in comparacao if row.get("status") not in {"igual", "ambos_ausentes"}]
        pontos = state.get("pontos") or []
        decisao = state.get("decisao_humana")
        parte_decisao = f" Decisão humana: {decisao.get('acao')}" if decisao else ""
        mensagem = (
            f"Supervisor: análise concluída — {len(documentos)} documento(s), "
            f"{len(comparacao)} campo(s) comparado(s), {len(diferencas)} diferença(s) ou lacuna(s), "
            f"{len(pontos)} ponto(s) crítico(s) revisado(s).{parte_decisao}"
        )
        logger.info(
            "Encerramento documentos=%s campos=%s diferencas=%s pontos_revisados=%s decisao=%s",
            len(documentos),
            len(comparacao),
            len(diferencas),
            len(pontos),
            decisao.get("acao", "nenhuma") if decisao else "nenhuma",
        )
        return {
            "mensagem_supervisor": mensagem,
            "live_status": [novo_status("supervisor_encerramento", "supervisor", mensagem)],
        }
