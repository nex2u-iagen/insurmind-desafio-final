"""Interface D&O Policy Intelligence — sidebar de configs, chat e orquestra de agentes.

Layout em três divisões: (1) sidebar com configs, (2) chat com o supervisor
(intermediação, gate e resposta) e (3) painel da orquestra semicircular —
supervisor é o maestro, a primeira fila são os agentes e a segunda as tools —
acendendo quadrante por quadrante conforme o grafo executa (telemetria ao vivo).
Abaixo do painel, pills selecionam o quadrante e abrem um cartão mínimo com as
legendas dos ícones (🤖 agente / 🔨 ferramenta) e o status do quadrante.
"""

from __future__ import annotations

import logging
import math
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from seguramente_final.agentes.contrato import ContratoAgente
from seguramente_final.agentes.fluxo import FANOUT, FLUXO
from seguramente_final.agentes.orquestrador import iniciar_analise, retomar_analise
from seguramente_final.agentes.registro import agrupar_por_rotulo, contratos_registrados
from seguramente_final.models import ComparisonRow, PolicyDocument
from seguramente_final.motor_llm import provedores_disponiveis
from seguramente_final.motor_llm.chaves import caminho_env, gravar_chaves, valores_do_provedor
from seguramente_final.motor_llm.google import ProvedorGoogle
from seguramente_final.telemetria import (
    eventos_da_thread,
    guardar_resultado,
    limpar_eventos,
    resultado_da_thread,
)

logger = logging.getLogger(__name__)

# Logs da orquestra no terminal de quem roda o MVP (nível por SEGURAMENTE_LOG_LEVEL).
logging.basicConfig(
    level=os.getenv("SEGURAMENTE_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logging.getLogger("sentence_transformers").setLevel(logging.WARNING)

ROOT = Path(__file__).resolve().parent
load_dotenv(caminho_env())
DEFAULT_A = ROOT / "data" / "policies" / "Apolice_DO_A.pdf"
DEFAULT_B = ROOT / "data" / "policies" / "Apolice_DO_B.pdf"
DADOS_DIR = Path(os.getenv("SEGURAMENTE_DATA_DIR", str(ROOT / "data"))).expanduser()

MODELOS_PADRAO = {
    "openai": "gpt-5-mini",
    "groq": "llama-3.3-70b-versatile",
    "google": ProvedorGoogle.modelo_padrao,  # fonte única: o default vive no provedor
}
ACOES_GATE = ["aprovado", "aprovado com ressalvas", "reprovado", "solicitar ajuste"]

# Mapeamento etapa da telemetria → quadrante nomeado da orquestra.
# Agentes vêm do registro (@agente); só as tools têm lista própria.
MAESTRO = agrupar_por_rotulo("maestro")
FILA_AGENTES = agrupar_por_rotulo("fila")
FILA_TOOLS = [
    ("ingestar_documentos", ["tool:ingestar_documentos"]),
    ("extrair_texto_ocr", ["tool:extrair_texto_ocr"]),
    ("comparar_apolices", ["tool:comparar_apolices"]),
    ("resumir_comparacao", ["tool:resumir_comparacao"]),
]
NOMES_TOOLS = frozenset(nome for nome, _ in FILA_TOOLS)

CORES = {
    "pendente": ("#334155", "#e2e8f0", "#0f172a"),
    "executando": ("#d97706", "#fde68a", "#78350f"),
    "ok": ("#047857", "#a7f3d0", "#064e3b"),
    "pausa": ("#1d4ed8", "#bfdbfe", "#1e3a8a"),
    "falhou": ("#b91c1c", "#fecaca", "#7f1d1d"),
    "fora_do_plano": ("#1e293b", "#334155", "#64748b"),
}

ROTULOS_STATUS = {
    "pendente": "pronto",
    "executando": "executando",
    "ok": "ok",
    "pausa": "pausa",
    "falhou": "falhou",
    "fora_do_plano": "fora do plano",
}

LARGURA, ALTURA = 700, 500
CX, CY = LARGURA // 2, 440
RAIO_AGENTES, RAIO_TOOLS = 310, 168
LIMITE_ANGULO_AGENTES = (-78.0, 78.0)

# Polling da execução em background: uma única fonte de rerun (o script principal).
# Um @st.fragment(run_every=...) concorrente com o rerun disparado pelo HITL
# corrompia a árvore de deltas do frontend ("Cannot set a node at a delta path"
# → tela branca). Ver tests/test_app_front.py::test_app_nao_usa_fragment_com_run_every.
INTERVALO_POLL = 0.5
LIMITE_ESPERA_RODANDO = 900.0  # 15 min sem retorno da worker → encerra na interface


def _carregar_contratos() -> dict[str, ContratoAgente]:
    """Catálogo etapa → contrato de todos os agentes registrados (para o front)."""
    return contratos_registrados()


CONTRATOS_POR_ETAPA = _carregar_contratos()

st.set_page_config(page_title="D&O Policy Intelligence", page_icon="", layout="wide")


# ───────────────────────────── estado da sessão ─────────────────────────────


def _sessao_padrao() -> None:
    st.session_state.setdefault("chat", [])
    st.session_state.setdefault("modo", "ocioso")  # ocioso | rodando | gate | fim
    st.session_state.setdefault("thread_id", None)
    st.session_state.setdefault("resultado", None)
    st.session_state.setdefault("resolvido", None)
    st.session_state.setdefault("pedido_atual", "")
    st.session_state.setdefault("inicio_rodando", None)
    if not st.session_state["chat"]:
        st.session_state["chat"].append(
            {
                "role": "assistant",
                "content": (
                    "Olá! Sou o **supervisor** da orquestra de agentes D&O. Envie seu pedido "
                    "(ex.: *compare os limites e as coberturas das duas apólices*) e eu organizo "
                    "a análise com os especialistas e as tools — você acompanha os quadrantes "
                    "acendendo ao lado."
                ),
            }
        )


def _adicionar_chat(role: str, content: str) -> None:
    st.session_state["chat"].append({"role": role, "content": content})


def _iniciar_analise(pedido: str) -> None:
    """Dispara a execução do grafo em background (worker thread)."""
    ctx = st.session_state["configs"]
    thread_id = uuid.uuid4().hex[:12]
    limpar_eventos(thread_id)
    st.session_state["thread_id"] = thread_id
    st.session_state["modo"] = "rodando"
    st.session_state["inicio_rodando"] = time.time()
    st.session_state["resultado"] = None
    st.session_state["resolvido"] = None
    st.session_state["pedido_atual"] = pedido

    caminhos = st.session_state["caminhos"]
    nomes = st.session_state["nomes"]
    simular_ocr = bool(st.session_state.get("simular_ocr", False))

    def trabalhar() -> None:
        try:
            resultado = iniciar_analise(
                caminhos,
                nomes=nomes,
                pedido_usuario=pedido,
                provider_mode=ctx["provider_mode"],
                modelo=ctx["modelo"],
                api_key=ctx["api_key"],
                thread_id=thread_id,
                diretorio=DADOS_DIR,
                simular_ocr=simular_ocr,
            )
            guardar_resultado(thread_id, "gate" if resultado.interrompido else "fim", resultado)
        except Exception as exc:
            logger.exception("Falha na análise em background")
            guardar_resultado(thread_id, "erro", str(exc))

    threading.Thread(target=trabalhar, daemon=True).start()


def _retomar_analise(decisao: dict[str, Any]) -> None:
    """Retoma a thread interrompida pelo gate em background."""
    ctx = st.session_state["configs"]
    thread_id = st.session_state["thread_id"]
    st.session_state["modo"] = "rodando"
    st.session_state["inicio_rodando"] = time.time()

    def trabalhar() -> None:
        try:
            final = retomar_analise(
                thread_id=thread_id,
                decisao=decisao,
                provider_mode=ctx["provider_mode"],
                modelo=ctx["modelo"],
                api_key=ctx["api_key"],
                diretorio=DADOS_DIR,
            )
            guardar_resultado(thread_id, "fim", final)
        except Exception as exc:
            logger.exception("Falha ao retomar o grafo")
            guardar_resultado(thread_id, "erro", str(exc))

    threading.Thread(target=trabalhar, daemon=True).start()


def _motivo_degradacao(estado: dict[str, Any]) -> str:
    """Causa rastreável do fallback (ex.: cota do Google), sem a URL da requisição."""
    motivo = str(estado.get("motivo_degradacao") or "").strip()
    if not motivo:
        return ""
    if " — " in motivo:  # provedores acrescentam o trecho acionável após o em dash
        motivo = motivo.rsplit(" — ", 1)[-1]
    return f"\n\n_Motivo:_ {motivo[:300]}"


def _aviso_degradacao(estado: dict[str, Any]) -> str:
    """Nota no chat quando parte da análise rodou offline (LLM indisponível).

    Sem isto o front parece avançar "com sucesso" mesmo com 503/429 em cascata.
    """
    motivos: list[str] = []
    if estado.get("fallback_extrator"):
        motivos.append("extração por LLM indisponível — os fatos vieram das regras offline")
    if estado.get("fallback_resumo"):
        motivos.append("resumo por LLM indisponível — resumo gerado por regras")
    indexacao = estado.get("indexacao_documental")
    if indexacao and not indexacao.get("available"):
        motivos.append("epochDB indisponível — os especialistas não recuperaram páginas vetorizadas")
    if not motivos:
        return ""
    return (
        "\n\n⚠️ **Modo degradado:** " + "; ".join(motivos) + ". "
        "A comparação determinística e o gate seguem disponíveis." + _motivo_degradacao(estado)
    )


def _consumir_resultado() -> bool:
    """Lê o desfecho da worker e publica a fala do supervisor no chat.

    Roda no script principal (nunca dentro de um fragment): o estado lido aqui
    alimenta o chat e o painel renderizados logo abaixo, sem rerun extra.

    Returns:
        ``True`` quando um desfecho foi consumido nesta execução.
    """
    thread_id = st.session_state["thread_id"]
    pacote = resultado_da_thread(thread_id)
    if pacote is None:
        return False
    chave, valor = pacote
    if st.session_state["resolvido"] == (thread_id, chave):
        return False
    st.session_state["resolvido"] = (thread_id, chave)
    if chave == "gate":
        st.session_state["modo"] = "gate"
        st.session_state["resultado"] = valor
        pontos = "\n".join(f"- **{p.get('titulo')}** — {p.get('detalhe')}" for p in valor.pontos)
        _adicionar_chat(
            "assistant",
            f"⚖️ **Gate humano acionado.** {valor.mensagem}\n\n{pontos}{_aviso_degradacao(valor.estado)}\n\n"
            "Registre sua decisão abaixo para eu concluir a análise.",
        )
    elif chave == "fim":
        st.session_state["modo"] = "fim"
        st.session_state["resultado"] = valor
        estado = valor.estado
        diferencas = sum(1 for r in estado.get("comparacao", []) if r.get("status") not in {"igual", "ambos_ausentes"})
        st.session_state["chat"].append(
            {
                "role": "assistant",
                "content": (
                    f"🎼 **{valor.mensagem}**\n\n{estado.get('resumo', '')}\n\n"
                    f"_{len(estado.get('documentos', []))} documentos · {len(estado.get('comparacao', []))} campos · "
                    f"{diferencas} diferenças/lacunas · {len(estado.get('achados', []))} achados dos especialistas._"
                    f"{_aviso_degradacao(estado)}"
                ),
                "com_tabela": estado,
            }
        )
    else:  # erro
        st.session_state["modo"] = "fim"
        _adicionar_chat("assistant", f"⚠️ A análise falhou: **{valor}**")
    return True


# ───────────────────────────── sidebar (configs) ─────────────────────────────


with st.sidebar:
    st.title("🎵 D&O Orquestra")
    st.caption("Configs da sessão")
    st.header("Documentos")
    use_demo = st.checkbox("Usar corpus sintético incluso", value=True)
    st.checkbox(
        "Acionar OCR nas páginas (simulação)",
        key="simular_ocr",
        help=(
            "Roda o OCR mesmo em páginas com texto nativo para exibir a ferramenta "
            "no painel de Orquestração; o texto nativo é preservado na análise."
        ),
    )
    if use_demo:
        st.info("Corpus autoral sintético para demonstração acadêmica.")
        st.session_state["caminhos"] = [DEFAULT_A, DEFAULT_B]
        st.session_state["nomes"] = ["Apólice A", "Apólice B"]
    else:
        upload_a = st.file_uploader("Apólice A", type=["pdf", "png", "jpg", "jpeg", "tif", "tiff"], key="a")
        upload_b = st.file_uploader("Apólice B", type=["pdf", "png", "jpg", "jpeg", "tif", "tiff"], key="b")
        caminhos: list[Path] = []
        nomes: list[str] = []
        if upload_a and upload_b:
            temp_dir = Path(tempfile.mkdtemp(prefix="seguramente-do-"))
            for upload, rotulo in ((upload_a, "Apólice A"), (upload_b, "Apólice B")):
                destino = temp_dir / upload.name
                destino.write_bytes(upload.getbuffer())
                caminhos.append(destino)
                nomes.append(rotulo)
        st.session_state["caminhos"] = caminhos
        st.session_state["nomes"] = nomes

    st.header("Motor de IA")
    provider = st.selectbox(
        "Provedor",
        ["offline", *provedores_disponiveis()],
        help="Offline usa regras determinísticas; openai/groq/google usam LLM (JSON estruturado).",
    )
    salvas = valores_do_provedor(provider) if provider != "offline" else {"api_key": "", "modelo": ""}
    modelo = st.text_input(
        "Modelo",
        value=salvas["modelo"] or MODELOS_PADRAO.get(provider, ""),
        placeholder=MODELOS_PADRAO.get(provider, "default do provedor"),
        disabled=provider == "offline",
        key=f"modelo_{provider}",
    )
    api_key = st.text_input(
        "API key",
        value=salvas["api_key"],
        type="password",
        disabled=provider == "offline",
        key=f"api_key_{provider}",
        help="Persistida no .env (fora do git); nunca vai para o estado do grafo nem para o checkpoint.",
    )
    if provider != "offline":
        if st.button(
            "💾 Salvar no .env",
            key="botao_salvar_env",
            help="Grava modelo e chave no .env (fora do git, permissão 0600).",
        ):
            gravar_chaves(provider, modelo.strip() or None, api_key.strip() or None)
            st.success("💾 Chave e modelo gravados no `.env`.")
        if api_key.strip() or modelo.strip():
            gravar_chaves(provider, modelo.strip() or None, api_key.strip() or None)
            st.caption("🔐 Chave e modelo persistidos em `.env` (fora do git).")
        situacao = valores_do_provedor(provider)
        chave_status = "presente (••••)" if situacao["api_key"] else "ausente"
        st.caption(f"Status do `.env` — modelo: {situacao['modelo'] or 'default do provedor'} · chave: {chave_status}")
    st.session_state["configs"] = {
        "provider_mode": provider,
        "modelo": modelo.strip() or None,
        "api_key": api_key.strip() or None,
    }
    st.divider()
    st.caption("A saída é apoio à análise. Não constitui parecer jurídico, subscrição ou decisão de cobertura.")


# ───────────────────────────── colunas: chat + orquestra ─────────────────────


col_chat, col_orquestra = st.columns([7, 5], gap="large")

_sessao_padrao()
# Desfecho da worker (gate/fim/erro) é consumido AQUI, antes do chat — o aviso
# entra na mesma execução, sem rerun vindo de dentro de um fragment.
_consumir_resultado()


def _estado_atual() -> dict[str, Any] | None:
    """Estado do grafo do último resultado (gate ou fim), quando disponível."""
    estado = getattr(st.session_state.get("resultado"), "estado", None)
    return estado if isinstance(estado, dict) else None


def _plano_atual() -> list[str] | None:
    """Plano de especialistas do supervisor (None enquanto a análise roda)."""
    estado = _estado_atual()
    return (estado.get("plano") or None) if estado else None


def _mapa_quadrantes() -> dict[str, list[str]]:
    """Mapa nome do quadrante → etapas da telemetria que o acendem."""
    return {nome: etapas for nome, etapas in (*MAESTRO, *FILA_AGENTES, *FILA_TOOLS)}


def _ferramentas_do_quadrante(nome: str) -> tuple[str, ...]:
    """União das ferramentas do contrato das etapas do quadrante (só agentes)."""
    etapas = _mapa_quadrantes().get(nome, [])
    ferramentas = {
        ferramenta
        for etapa in etapas
        if etapa in CONTRATOS_POR_ETAPA
        for ferramenta in CONTRATOS_POR_ETAPA[etapa].ferramentas
    }
    return tuple(sorted(ferramentas))


def _rotulo_cartao(nome: str) -> str:
    """Legenda do cartão: ícone do tipo (🤖 agente / 🔨 ferramenta) + badge ⚡n."""
    ferramentas = _ferramentas_do_quadrante(nome)
    icone = "🔨" if nome in NOMES_TOOLS else "🤖"
    sufixo = f" ⚡{len(ferramentas)}" if ferramentas else ""
    return f"{icone} {nome}{sufixo}"


def _status_quadrantes(eventos: list[dict[str, Any]]) -> dict[str, str]:
    """Deriva o status final de cada quadrante a partir da fila de eventos.

    Especialistas fora do plano do supervisor ganham ``fora_do_plano``
    (esmaecido) assim que o plano é conhecido (resultado disponível).
    """
    status: dict[str, str] = {}
    for nome, etapas in [*MAESTRO, *FILA_AGENTES, *FILA_TOOLS]:
        status[nome] = "pendente"
        for evento in eventos:
            if evento["etapa"] in etapas:
                status[nome] = evento["status"]
    plano = _plano_atual()
    if plano is not None:
        planejados = {f"especialista_{especialista}" for especialista in plano}
        for nome, etapas in FILA_AGENTES:
            if etapas[0].startswith("especialista_") and etapas[0] not in planejados:
                status[nome] = "fora_do_plano"
    return status


def _cartao(label: str, x: float, y: float, status: str, largura: int, altura: int) -> str:
    """Cartão posicionado de um quadrante (glow forte executando, esmaecido fora do plano)."""
    fundo, borda, texto = CORES.get(status, CORES["pendente"])
    if status == "executando":
        estilo = "animation:quadrante-pulso 1.1s ease-in-out infinite;box-shadow:0 0 16px 4px rgba(251,191,36,.7);"
    elif status == "fora_do_plano":
        estilo = "opacity:.6;"
    else:
        estilo = ""
    return (
        f'<div style="position:absolute;left:{x - largura / 2:.0f}px;top:{y - altura / 2:.0f}px;'
        f"width:{largura}px;height:{altura}px;border-radius:12px;background:{fundo};"
        f"border:2px solid {borda};color:{texto};display:flex;align-items:center;justify-content:center;"
        f'text-align:center;font-size:10.5px;font-weight:600;line-height:1.15;padding:4px;{estilo}">'
        f"<span>{label}</span></div>"
    )


def _posicao(raio: float, graus: float) -> tuple[float, float]:
    rad = math.radians(graus)
    return CX + raio * math.sin(rad), CY - raio * math.cos(rad)


def _posicoes() -> dict[str, tuple[float, float]]:
    """Centro de cada quadrante — cartões e arestas compartilham as posições."""
    supervisor, gate = MAESTRO[0][0], MAESTRO[1][0]
    posicoes = {supervisor: (float(CX), float(CY)), gate: (float(CX + 160), float(CY))}
    passo = (LIMITE_ANGULO_AGENTES[1] - LIMITE_ANGULO_AGENTES[0]) / (len(FILA_AGENTES) - 1)
    for indice, (nome, _) in enumerate(FILA_AGENTES):
        posicoes[nome] = _posicao(RAIO_AGENTES, LIMITE_ANGULO_AGENTES[0] + indice * passo)
    for (nome, _), angulo in zip(FILA_TOOLS, (-62, -21, 21, 62), strict=True):
        posicoes[nome] = _posicao(RAIO_TOOLS, angulo)
    return posicoes


def _arestas_do_fluxo() -> list[tuple[str, str]]:
    """Arestas entre quadrantes seguindo o FLUXO (com fan-out dos especialistas)."""
    mapa = {etapa: quadrante for quadrante, etapas in _mapa_quadrantes().items() for etapa in etapas}
    especialistas = [nome for nome, etapas in FILA_AGENTES if etapas[0].startswith("especialista_")]
    arestas: list[tuple[str, str]] = []
    pendentes: list[str] = []
    for item in FLUXO:
        if item is FANOUT:
            origem = pendentes[-1]
            arestas.extend((origem, destino) for destino in especialistas if origem != destino)
            pendentes = list(especialistas)
            continue
        quadrante = mapa[item]
        arestas.extend((origem, quadrante) for origem in pendentes if origem != quadrante)
        pendentes = [quadrante]
    return arestas


def _arestas_de_ferramentas() -> list[tuple[str, str]]:
    """Ramos agente → tool (ferramentas do contrato presentes na fila de tools)."""
    ferramentas = {nome for nome, _ in FILA_TOOLS}
    return [
        (nome, ferramenta)
        for nome, _ in FILA_AGENTES
        for ferramenta in _ferramentas_do_quadrante(nome)
        if ferramenta in ferramentas
    ]


ARESTAS_CORES = {
    "base": "#475569",
    "ativo": "#f59e0b",
    "ok": "#059669",
    "pausa": "#3b82f6",
    "falhou": "#dc2626",
    "ignorado": "#334155",
}


def _estilo_aresta(origem: str, destino: str) -> tuple[str, str]:
    """Cor e marcador da aresta a partir do status dos dois quadrantes."""
    par = (origem, destino)
    if "executando" in par:
        return ARESTAS_CORES["ativo"], "ativo"
    if "falhou" in par:
        return ARESTAS_CORES["falhou"], "falhou"
    if "pausa" in par:
        return ARESTAS_CORES["pausa"], "pausa"
    if "fora_do_plano" in par:
        return ARESTAS_CORES["ignorado"], "ignorado"
    if origem == "ok" and destino == "ok":
        return ARESTAS_CORES["ok"], "ok"
    return ARESTAS_CORES["base"], "base"


def _svg_arestas(posicoes: dict[str, tuple[float, float]], status: dict[str, str]) -> str:
    """Camada SVG com o grafo: arestas do caminho (com seta) e ramos até as tools."""
    marcadores = "".join(
        f'<marker id="seta-{slug}" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="6" markerHeight="6" '
        f'orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="{cor}"/></marker>'
        for slug, cor in ARESTAS_CORES.items()
    )
    linhas: list[str] = []
    for origem, destino in _arestas_do_fluxo():
        x1, y1 = posicoes[origem]
        x2, y2 = posicoes[destino]
        cor, slug = _estilo_aresta(status.get(origem, "pendente"), status.get(destino, "pendente"))
        anim = "stroke-dasharray:8 6;animation:aresta-fluxo .7s linear infinite;" if slug == "ativo" else ""
        linhas.append(
            f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="{cor}" '
            f'stroke-width="2" marker-end="url(#seta-{slug})" style="{anim}"/>'
        )
    for origem, destino in _arestas_de_ferramentas():
        x1, y1 = posicoes[origem]
        x2, y2 = posicoes[destino]
        linhas.append(
            f'<line x1="{x1:.0f}" y1="{y1:.0f}" x2="{x2:.0f}" y2="{y2:.0f}" stroke="#334155" '
            'stroke-width="1.5" stroke-dasharray="4 5" opacity=".9"/>'
        )
    return (
        f'<svg style="position:absolute;inset:0;width:100%;height:100%;pointer-events:none" '
        f'viewBox="0 0 {LARGURA} {ALTURA}"><defs>{marcadores}</defs>{"".join(linhas)}</svg>'
    )


def _render_orquestra() -> None:
    """Painel semicircular ao vivo: maestro, fila de agentes, fila de tools e grafo."""
    thread_id = st.session_state["thread_id"]
    eventos = eventos_da_thread(thread_id)
    status = _status_quadrantes(eventos)
    concluidos = sum(1 for s in status.values() if s == "ok")
    progresso = f" · {concluidos}/{len(status)} ✓"
    executando = next((e for e in reversed(eventos) if e["status"] == "executando"), None)
    if executando:
        status_atual = f"🎵 executando: **{executando['etapa']}**{progresso}"
    elif st.session_state["modo"] == "fim":
        status_atual = f"🏁 análise concluída{progresso}"
    elif st.session_state["modo"] == "gate":
        status_atual = f"⚖️ aguardando decisão humana{progresso}"
    else:
        status_atual = f"🎼 orquestra pronta{progresso}"

    supervisor, gate = MAESTRO[0][0], MAESTRO[1][0]
    posicoes = _posicoes()
    cartoes = [
        _cartao(_rotulo_cartao(supervisor), *posicoes[supervisor], status.get(supervisor, "pendente"), 128, 46),
        _cartao(_rotulo_cartao(gate), *posicoes[gate], status.get(gate, "pendente"), 104, 44),
    ]
    for nome, _ in FILA_AGENTES:
        x, y = posicoes[nome]
        cartoes.append(_cartao(_rotulo_cartao(nome), x, y, status.get(nome, "pendente"), 76, 46))
    for nome, _ in FILA_TOOLS:
        x, y = posicoes[nome]
        cartoes.append(_cartao(_rotulo_cartao(nome), x, y, status.get(nome, "pendente"), 96, 46))

    legenda = " ".join(
        f'<span style="color:{CORES[c][1]};font-size:10px">■ {rotulo}</span>'
        for c, rotulo in (
            ("pendente", "pronto"),
            ("executando", "executando"),
            ("ok", "ok"),
            ("pausa", "pausa"),
            ("fora_do_plano", "fora do plano"),
        )
    )
    legenda += (
        ' <span style="color:#475569;font-size:10px">→ caminho do grafo</span>'
        ' <span style="color:#334155;font-size:10px">⋯ ferramentas</span>'
    )
    html = (
        "<style>@keyframes quadrante-pulso{0%{transform:scale(1);opacity:.88}"
        "50%{transform:scale(1.05);opacity:1}100%{transform:scale(1);opacity:.88}}"
        "@keyframes aresta-fluxo{to{stroke-dashoffset:-28}}</style>"
        f'<div style="position:relative;width:{LARGURA}px;height:{ALTURA}px;margin:0 auto">'
        + _svg_arestas(posicoes, status)
        + f'<div style="position:absolute;left:0;right:0;top:2px;text-align:center;color:#94a3b8;'
        f'font-size:11px">{status_atual}</div>'
        f'<div style="position:absolute;left:0;right:0;top:88px;text-align:center;color:#64748b;'
        'font-size:9.5px;letter-spacing:2px">PRIMEIRA FILA · AGENTES</div>'
        f'<div style="position:absolute;left:0;right:0;top:{CY - 42}px;text-align:center;color:#64748b;'
        'font-size:9.5px;letter-spacing:2px">SEGUNDA FILA · TOOLS</div>'
        + "".join(cartoes)
        + f'<div style="position:absolute;left:0;right:0;bottom:0;text-align:center">{legenda}</div>'
        "</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def _render_detalhe() -> None:
    """Pills de seleção de quadrante + legendas mínimas: tipo do nó (ícone) e status."""
    mapa = _mapa_quadrantes()
    opcoes = list(mapa)
    escolhido = st.pills("Detalhe do quadrante", opcoes, default=opcoes[0], key="pills_quadrante", wrap=True)
    if not escolhido:
        return
    eventos = eventos_da_thread(st.session_state["thread_id"])
    etapas = mapa[escolhido]
    tipo = "🔨 ferramenta" if etapas[0].startswith("tool:") else "🤖 agente"
    status = _status_quadrantes(eventos).get(escolhido, "pendente")
    st.markdown(f"#### 🔍 {escolhido}")
    st.markdown(f"**{tipo}**")
    st.caption(f"Status: {ROTULOS_STATUS.get(status, status)}")


def _render_form_gate() -> None:
    """Formulário de decisão dentro do chat (retoma o grafo)."""
    with st.chat_message("assistant", avatar="⚖️"):
        st.markdown("**Registro de decisão do gate humano**")
        with st.form("form_gate", clear_on_submit=False):
            acao = st.selectbox("Decisão", ACOES_GATE)
            comentario = st.text_area("Comentário do revisor", placeholder="Justificativa ou ressalvas")
            enviado = st.form_submit_button("Enviar decisão e concluir", type="primary")
        if enviado:
            _adicionar_chat("user", f"Decisão: **{acao}** — {comentario or 'sem comentário'}")
            _retomar_analise({"acao": acao, "comentario": comentario})
            st.rerun()


def _render_tabela(estado: dict[str, Any]) -> None:
    """Tabela comparativa completa em expander do chat."""
    linhas = [ComparisonRow(**r) for r in estado.get("comparacao") or []]
    df = pd.DataFrame(
        [
            {
                "Campo": row.label,
                "Apólice A": row.policy_a or "Não localizado",
                "Apólice B": row.policy_b or "Não localizado",
                "Status": row.status,
                "Páginas": f"A:{row.page_a or '-'} | B:{row.page_b or '-'}",
            }
            for row in linhas
        ]
    )
    with st.expander("📄 Tabela comparativa completa (19 campos)"):
        st.dataframe(df, width="stretch", hide_index=True)
    documentos = [PolicyDocument.from_dict(d) for d in estado.get("documentos") or []]
    with st.expander("🔎 Evidências por página (linhas divergentes)"):
        for row in linhas:
            if row.status == "igual":
                continue
            st.markdown(f"**{row.label}** — `{row.status}`")
            c1, c2 = st.columns(2)
            c1.markdown(f"A · p. {row.page_a or '-'}")
            c1.write(row.evidence_a)
            c2.markdown(f"B · p. {row.page_b or '-'}")
            c2.write(row.evidence_b)
    if documentos:
        with st.expander("🗂️ Documentos e extração"):
            for doc in documentos:
                metodos = pd.Series([p.extraction_method for p in doc.pages]).value_counts().to_dict()
                st.write(f"**{doc.name}** — `{doc.document_id}` · {len(doc.pages)} pág. · {metodos}")


with col_chat:
    st.subheader("💬 Chat com o supervisor")
    for mensagem in st.session_state["chat"]:
        avatar = "🎩" if mensagem["role"] == "assistant" else None
        with st.chat_message(mensagem["role"], avatar=avatar):
            st.markdown(mensagem["content"])
            if mensagem.get("com_tabela"):
                _render_tabela(mensagem["com_tabela"])

    if st.session_state["modo"] == "rodando":
        with st.chat_message("assistant", avatar="🎩"):
            st.markdown("🎼 *Orquestrando a análise — acompanhe os quadrantes acendendo ao lado…*")
    elif st.session_state["modo"] == "gate":
        _render_form_gate()

    pedido = st.chat_input(
        "Descreva o pedido ao supervisor (ex.: compare os limites e as coberturas)",
        disabled=st.session_state["modo"] in {"rodando"},
    )
    if pedido:
        caminhos = st.session_state.get("caminhos") or []
        if len(caminhos) < 2:
            st.error("Envie duas apólices (use o corpus sintético ou faça upload das duas).")
            st.stop()
        _adicionar_chat("user", pedido)
        _iniciar_analise(pedido)
        st.rerun()


with col_orquestra:
    st.subheader("🎼 Orquestra de agentes")
    st.caption("Maestro = supervisor · 1ª fila = agentes · 2ª fila = tools")
    _render_orquestra()
    _render_detalhe()


# ───────────────────────────── polling da worker ─────────────────────────────
if st.session_state["modo"] == "rodando":
    inicio = st.session_state.get("inicio_rodando") or time.time()
    if time.time() - inicio > LIMITE_ESPERA_RODANDO:
        st.session_state["modo"] = "fim"
        st.session_state["inicio_rodando"] = None
        _adicionar_chat(
            "assistant",
            f"⚠️ A execução não retornou em {int(LIMITE_ESPERA_RODANDO // 60)} minutos; "
            "verifique os logs do terminal e recarregue a página para uma nova tentativa.",
        )
        st.rerun()
    time.sleep(INTERVALO_POLL)
    st.rerun()
