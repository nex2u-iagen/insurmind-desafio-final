# SDD — Software Design Document

## D&O Policy Intelligence com Grafo de Agentes (LangGraph + epochDB)

> Status: implementação · Revisão: 2026-10-04 · Projeto Final InsurMinds

---

## 1. Visão e escopo

Sistema de agentes de IA que **intermedia o usuário** (supervisor) e delega a
comparação de duas apólices D&O a **sub-agentes especialistas**, um por domínio
do schema, com **gate humano** para pontos críticos. O fluxo clássico
(`analyze_policies`) permanece disponível em paralelo.

Requisitos funcionais:

| # | Requisito | Satisfeito por |
|---|---|---|
| R1 | Ler PDF ou imagem (foto/digitalizado) | `ingest.py` + `tools/ocr.py` (Tesseract) |
| R2 | Extrair conteúdo automaticamente | Extrator offline (`rules.py`) ou LLM |
| R3 | Estruturar informações (19 campos) | `schema.py` + `models.PolicyFact` |
| R4 | Armazenar dados | SQLite (`storage.py`) + memória epochDB |
| R5 | Comparar duas apólices | `compare.py` (tool reutilizada pelos agentes) |
| R6 | Apresentar diferenças com evidências | Streamlit + `ComparisonRow` |
| R7 | Utilizar IA generativa | `motor_llm/` (openai, groq, google) |
| R8 | Interface demonstrável | `app.py` (modo agentes + gate) |
| R9 | Supervisor intermediando usuário/sub-agentes | `agentes/supervisor.py` |
| R10 | Gate humano com pontos críticos | `agentes/gate.py` (`interrupt`) |
| R11 | Persistência/retomada de execução | `EpochDBCheckpointer` (vendorizado) |

Não requisitos: parecer jurídico, subscrição, decisão de cobertura (saída é
apoio à análise documental).

## 2. Arquitetura

```
Usuário (Streamlit)
   │  pedido + provedor(modelo, apikey)
   ▼
Supervisor (abertura) ──────────────► intermedia e monta o plano
   ▼
ingestar (tool: load_document) ─────► documentos com páginas/OCR
   ▼
extrair (ExtratorFatos) ────────────► 19 fatos por apólice (offline ou LLM)
   ▼
Especialistas (6, paralelos) ───────► achados por domínio, escrevem no blackboard
   │   identificação · limites · coberturas · extensões · exclusões · condições
   ▼
comparar (tool: compare_documents) ─► linhas comparativas com evidências
   ▼
Revisor ────────────────────────────► pontos críticos (regras determinísticas)
   ▼
Gate humano ── interrupt ───────────► Streamlit: Aprovar / Devolver / Editar
   ▼
sintetizar (ResumidorLLM/offline) ──► resumo executivo
   ▼
Supervisor (encerramento) ──────────► mensagem final ao usuário
   ▼
persistir ──────────────────────────► SQLite + memória epochDB (remember)
```

Padrões (skill graph-patterns): estado tipado e serializável; node = classe com
`__call__(state) -> partial`; DI leve no composition root
(`orquestrador.py`/`grafo.py`); gate humano audito; `live_status` em lote
(1 entrada por etapa, não por token).

Observabilidade: `telemetria.py` (raiz) publica eventos `início/fim` por
`thread_id` (contextvar setado no `invoke`); nodes são envolvidos por
`com_evento` e tools publicam automaticamente via `evento_ferramenta` no
decorator. O front acende os quadrantes da orquestra em tempo real por
**polling no script principal** (`modo == "rodando"` → `time.sleep(0.5)` +
`st.rerun()`, teto de 15 min) — sem `@st.fragment(run_every=...)`, porque o
auto-rerun do fragment competindo com o rerun do HITL corrompia a árvore de
deltas do frontend (tela branca: `Cannot set a node at a delta path`).

## 3. Estrutura de pastas

```text
seguramente_final/
├── agentes/                    # grafo de agentes (novo)
│   ├── checkpoint_epoch.py     # EpochDBCheckpointer vendorizado (MIT, filesystem)
│   ├── contrato.py             # ContratoAgente (nome/papel/prompt/ferramentas)
│   ├── registro.py             # registry + decorator @agente (fonte única grafo/front)
│   ├── fluxo.py                # FLUXO declarativo + Contexto + construir + FANOUT
│   ├── estado.py               # EstadoAnalise (TypedDict) + serialização + live_status
│   ├── supervisor.py           # abertura/encerramento — intermediação com o usuário
│   ├── especialistas/          # pacote: um módulo por especialidade
│   │   ├── base.py             # EspecialistaNode (ABC) — fatia, veredito, achado
│   │   ├── identificacao.py · limites.py · coberturas.py
│   │   ├── extensoes.py · exclusoes.py · condicoes.py
│   │   └── __init__.py         # re-exports + CLASSES/NOMES + criar_especialistas
│   ├── nodes.py                # Ingestor/Extrator/Comparador/Revisor/Sintetizador/Persistidor
│   ├── gate.py                 # pontos críticos + interrupt + auditoria JSONL
│   ├── memoria.py              # Protocol Memoria + MemoriaLocal/EpochDb/Composta
│   ├── grafo.py                # montagem do StateGraph + com_evento + compile
│   └── orquestrador.py         # iniciar_analise / retomar_analise (composition root)
├── motor_llm/                  # APENAS transporte/provedores de LLM
│   ├── base.py                 # ChatJson, LLMError, ProvedorLLM ABC, registry, fábrica
│   ├── openai_groq.py          # ProvedorOpenAI + ProvedorGroq (REST OpenAI-compatible)
│   └── google.py               # ProvedorGoogle (Gemini generateContent)
├── tools/                      # ferramentas dos agentes (estratégias sobre o motor)
│   ├── registry.py             # @registrar_ferramenta + allowlist + telemetria automática
│   ├── documento.py            # ingestar_documentos, comparar_apolices, resumir_comparacao
│   ├── extrator.py             # ExtratorLLM (extração JSON + fallback offline)
│   ├── resumidor.py            # ResumidorLLM (síntese via ChatJson)
│   └── ocr.py                  # OcrEngine + tool extrair_texto_ocr (Tesseract)
├── telemetria.py               # bus de eventos por thread (nodes + tools → front)
├── compare.py · ingest.py · rules.py · schema.py · models.py · storage.py · pipeline.py
```

Princípios: **alta coesão** (um módulo = um motivo para mudar), **baixo
acoplamento** (dependência de `Protocol`/registry; concreto só no composition
root), `from __future__ import annotations`, docstring de módulo + Google style,
`logger = logging.getLogger(__name__)`, identificadores em português, ruff.

## 4. Especificação

### 4.1 Estado do grafo (`agentes/estado.py`)

```python
class EstadoAnalise(TypedDict, total=False):
    thread_id: str  # id da sessão (checkpointer)
    caminhos: list[str]  # duas apólices
    nomes: list[str]
    pedido_usuario: str  # intermediação do supervisor
    provedor: str  # openai | groq | google | offline
    modelo: str
    plano: list[str]  # especialistas despachados
    instrucoes: dict[str, str]  # instrução por especialista (intermediação)
    documentos: list[dict]  # PolicyDocument.to_dict() — JSON-safe
    fatos: list[dict]  # PolicyFact por documento
    comparacao: list[dict]  # ComparisonRow.to_dict()
    pontos: list[dict]  # pontos críticos p/ o humano
    decisao_humana: dict | None  # {acao, comentario, ...} vinda do interrupt
    resumo: str
    mensagem_supervisor: str
    fallback_extrator: bool  # sinal do ExtratorLLM p/ o revisor
    live_status: Annotated[list[dict], operator.add]  # reducer: steps em lote
    achados: Annotated[list[dict], operator.add]  # reducer: 1 por especialista
```

Regra: tudo JSON-safe (o checkpointer serializa com `JsonPlusSerializer`).
**Credenciais nunca entram no estado** (ficam na injeção de dependência do
orquestrador) — evita vazamento em arquivos de checkpoint.

### 4.2 Motor LLM (`motor_llm/`)

Contrato único de saída JSON:

```python
class ChatJson(Protocol):
    def chat_json(self, messages, *, temperature=0.1) -> dict: ...
```

- Registry de provedores (`PROVEDORES` + `@registrar_provedor`); fábrica
  `criar_cliente(provedor, model=None, api_key=None, base_url=None, timeout=None)`.
- `ProvedorLLM(ABC)` com `chat_json` abstrato; transporte HTTP testável por
  injeção do callable `post` (TDD sem rede).
- Defaults: openai `https://api.openai.com/v1` · groq `https://api.groq.com/openai/v1`
  · google `https://generativelanguage.googleapis.com/v1beta`.
- Chaves: params do front sobrepõem env (`OPENAI_API_KEY`, `GROQ_API_KEY`,
  `GOOGLE_API_KEY`/`GEMINI_API_KEY`).
- **Retry transitório** (`base.enviar_post`): até 5 tentativas com backoff
  exponencial `1·2ⁿ` (cap em `ESPERA_MAX=8s`) + jitter proporcional de 15%,
  honrando `Retry-After` (teto `RETRY_AFTER_MAX=30s`), somente para
  `Timeout`/`ConnectionError` e status `{429, 500, 502, 503, 504}`; erros
  permanentes (ex.: 400) saem na primeira chamada. O **fan-out de
  especialistas atravessa um semáforo global** (`SEGURAMENTE_LLM_CONCORRENCIA`,
  default 2) — só a requisição ocupa vaga, as esperas de backoff não. Um
  predicado `nao_repetir` desiste na 1ª resposta quando o provedor sinaliza
  espera longa (cota gratuita do Google zera e pede ~11h: repetir só atrasaria
  o fallback offline). A mensagem crua da exceção nunca é logada no helper (a
  URL do google carrega a key); o provedor formata/redige o erro final —
  `google` encadeia `LLMError from requests.HTTPError(texto_redigido)`
  (traceback sem credencial) e anexa o trecho acionável da cota
  (`cota gratuita ... troque GOOGLE_MODEL`).
- `max_completion_tokens` somente para `gpt-5*`; demais `max_tokens`.
- Erros → `LLMError` (nunca chave no log).
- `ResumidorLLM.summarize(rows, memoria_contexto=None)` consome `ChatJson` —
  portável entre os 3 provedores; o bloco de memória (se houver) entra no user
  content. A extração (`ExtratorLLM`) vive em `tools/extrator.py` e também
  consome `ChatJson`: fallback offline quando o modelo falha/retorna JSON vazio,
  sinalizando `fallback_aplicado` para o revisor (regra 6 do gate).

### 4.3 Ferramentas (`tools/`)

Registry + decorator (padrão do AGENTS.md):

```python
@registrar_ferramenta("ingestar_documentos", descricao="...")
def ingestar_documentos(caminhos: list[str]) -> list[dict]: ...
```

Allowlist imposta em código: `ingestar_documentos`, `comparar_apolices`,
`resumir_comparacao`, `extrair_texto_ocr`. Ferramentas delegam aos módulos de
domínio já testados (`ingest`, `compare`, `motor_llm.resumidor`) — sem
duplicação de regra. `ExtratorLLM` e `OcrEngine` vivem em `tools/` (estratégia
de extração e motor OCR, injetados por DI no pipeline e no grafo); o OCR entra
na allowlist como melhor esforço (``""`` em falha, logada). `ingest.py` importa
`tools.ocr` de forma lazy para quebrar o ciclo real `tools.documento → ingest
→ tools.ocr`.

Contrato de execução: `executar_ferramenta(agente, nome, *args, **kwargs)`
impõe o `Protocol AgenteFerramentas` (duck typing `.nome`/`.ferramentas`) —
PermissionError fora do contrato → `obter_ferramenta` (allowlist checada antes
do registro → `RuntimeError`) → execução sob `origem_agente(agente.nome)`,
publicando `evento_ferramenta` com a origem na telemetria. Nós do grafo só
falam com tools por esse dispatcher (nunca importam função de tool direto).

### 4.4 Agentes

Especialistas: **um módulo individual por área** em `agentes/especialistas/`
(`identificacao.py`, `limites.py`, `coberturas.py`, `extensoes.py`,
`exclusoes.py`, `condicoes.py`) sobre a base `EspecialistaNode`
(`especialistas/base.py`), que valida `nome`/`categorias`/`foco` e oferece o
hook `veredito_dominio()` — comportamento específico da área cresce isolado na
própria classe. `__init__.py` re-exporta e expõe `CLASSES_ESPECIALISTAS`,
`NOMES_ESPECIALISTAS` e `criar_especialistas` (fonte única; o plano do
supervisor deriva dela).

**Contrato** (`agentes/contrato.py`): `ContratoAgente` (frozen dataclass)
agrega `nome`, `papel`, `prompt_sistema` e `ferramentas` — valida campos não
vazios e `ferramentas ⊆ ALLOWLIST` (ValueError cita "allowlist"), coerindo para
`frozenset`. Todos os 9 nós (supervisor ×2, Ingestor, Extrator, Comparador,
Revisor, Sintetizador, Persistidor, Gate) expõem `contrato` como atributo de
classe com `nome` = etapa da telemetria; especialistas derivam da base
(`f"especialista_{nome}"`), que valida `nome`/`categorias`/`foco`/`prompt_sistema`
e publica a constante `PROMPT_SISTEMA` (contém o `foco` literalmente) usada
também como system message do veredito.

**Roteamento dinâmico** (`supervisor.py`): `SupervisorAbertura.__init__`
recebe o `ChatJson` opcional e a `memoria` opcional; antes de planejar,
`_lembrancas(pedido)` consulta `memoria.query(pedido, k=3)` e publica
`estado.memoria_contexto` (melhor esforço — falha vira `[]` com warning).
`_planejar` pergunta ao LLM (system = `contrato.prompt_sistema`) e valida a
resposta com `_extrair_especialistas`: aceita chaves `especialistas`/`plan`/
`plano` em lista **ou** string separada por `,`/`;` — sem lista utilizável,
loga as chaves recebidas e cai para `_planejar_keywords` (`MAPA_KEYWORDS` +
`_normalizar` sem acento/stemas — offline ou falha do LLM); sem match, todos do
catálogo; o plano é sempre reordenado na ordem de `NOMES_ESPECIALISTAS`.
Instruções por especialista vão para `estado.instrucoes` — a base lê
`instrucoes.get(nome) or pedido_usuario` e monta o user content do veredito
como `bloco_memoria(memoria_contexto)` + `"Instrução do supervisor: ..."` +
JSON dos fatos (`prompting.bloco_memoria`: no máximo 3 lembranças × 500
caracteres; consumido também pelo `ResumidorLLM`).

Ferramentas por agente (proposta funcional): Ingestor
`{ingestar_documentos, extrair_texto_ocr}` · Extrator `{extrair_texto_ocr}` ·
Comparador `{comparar_apolices}` · Sintetizador `{resumir_comparacao}` ·
demais `∅`.

**Registro e fluxo** (`agentes/registro.py`, `agentes/fluxo.py`): o decorator
`@agente(rotulo=..., ordem=..., grupo=...)` valida o `contrato` da classe e a
registra em `AGENTES`; `montar_grafo` itera o `FLUXO` declarativo
(`FANOUT` = fan-out dos especialistas pelo plano) e o `app.py` deriva
`MAESTRO`/`FILA_AGENTES`/`CONTRATOS_POR_ETAPA` de `agrupar_por_rotulo`/
`contratos_registrados` — sem listas duplicadas.

**Receita — novo agente** (1 classe + 1 linha):

```python
# agentes/meu_agente.py
@agente(rotulo="Meu Agente", ordem=130)          # registra no grafo e no front
class MeuAgente:
    contrato = ContratoAgente(nome="minha_etapa", ...)  # etapa da telemetria
    def __call__(self, state: dict) -> dict: ...
```

1) classe decorada (se tiver dependência, fábrica em `fluxo.FABRICAS`);
2) linha em `FLUXO` (só se entrar na linha principal — especialistas não);
3) teste em `tests/`. Telemetria, allowlist, pills e cartão de detalhe vêm
automaticamente do registro.

| Agente | Domínio/schema | Implementação |
|---|---|---|
| `SupervisorAbertura` | — | valida entrada, monta `plano`, redige mensagem |
| `SupervisorEncerramento` | — | consolida contagens/decisão em mensagem |
| `IngestorNode` | — | tool `ingestar_documentos` |
| `ExtratorNode` | 19 campos | `ExtratorFatos` (offline `RuleBasedExtractor` ou `ExtratorLLM`) |
| `EspecialistaIdentificacao` | identificacao | veredito da fatia + achado (base `EspecialistaNode`) |
| `EspecialistaLimites` | limites, retencoes | veredito da fatia + achado |
| `EspecialistaCoberturas` | coberturas | veredito da fatia + achado |
| `EspecialistaExtensoes` | extensoes | veredito da fatia + achado |
| `EspecialistaExclusoes` | exclusoes | veredito da fatia + achado |
| `EspecialistaCondicoes` | condicoes | veredito da fatia + achado |
| `ComparadorNode` | todos | tool `comparar_apolices` → 19 linhas |
| `RevisorNode` | todos | `calcular_pontos_criticos` → `pontos` |
| `GateHumano` | — | `interrupt(pontos)`; auditoria JSONL |
| `SintetizadorNode` | — | resumo offline/LLM considerando `decisao_humana` |
| `PersistidorNode` | — | SQLite + `memoria.remember` |

Comunicação: **blackboard tipado** — cada agente retorna *partial state* que o
LangGraph mescla (`Annotated[list, operator.add]` para `live_status` e
`achados`; demais canais com escritor único). Especialistas rodam em paralelo
no mesmo super-step.

Modo de cada especialista: offline = regras determinísticas do domínio;
openai/groq/google = regra + chamada curta de veredito com system message
próprio — custo/tokens por chamada registrados no `logger` (`llm chamada
provedor=... tokens=...`).

### 4.5 Gate humano e pontos críticos

`calcular_pontos_criticos(estado) -> list[PontoCritico]` — regras:

1. comparação com `status == "ambigua"`;
2. Cobertura A/B/C, Limite máximo, Limite agregado ou Franquia ausente em só
   uma apólice (`ausente_em_a`/`ausente_em_b`);
3. página com `extraction_method` em `{"ocr-empty", "pdf-text-empty"}`;
4. fato `present` sem `evidence` ou sem `page`;
5. divergência material > 20% em campos numéricos (limite/franquia);
6. fallback do `ExtratorLLM` ativado (falha/JSON vazio do modelo).

Fluxo: nó `gate` → se `pontos` e sem `decisao_humana` → auditoria ("aguardando")
→ `interrupt(payload)` (mensagem redigida pelo supervisor). Streamlit exibe os
pontos com formulário de decisão (ação: aprovado / aprovado com ressalvas /
reprovado / solicitar ajuste + comentário) → retoma com
`Command(resume={"acao": ..., "comentario": ...})` e audita a decisão.
Auditoria em `evidence/gate_audit_<thread_id>.jsonl`: `timestamp, thread_id,
actor, status, pontos, decisao`.

### 4.6 Memória e persistência

- **Checkpointer**: `EpochDBCheckpointer` vendorizado de
  `epochdb.core.checkpointer` (MIT) — JSON por `thread_id` em
  `<storage_dir>/checkpoints/`; retomada/replay/time-travel.
  Motivo da vendorização: `hnswlib` (dep. do pacote epochdb) exige toolchain
  C++ ausente no ambiente; o checkpointer é autocontido (stdlib + langgraph).
- **Memória de longo prazo**: `Protocol Memoria` com `remember/query`;
  `criar_memoria(dir)` compõe `MemoriaLocal` (JSONL em
  `memoria/registros.jsonl` — sempre presente) e `MemoriaEpochDb` (epochdb
  completo, quando disponível: vetor + grafo). Sem epochdb (hnswlib ausente),
  cai só na fonte local com warning. DI: criada no composition root.
  - `MemoriaEpochDb.tentar_criar` instancia `EpochDB(storage_dir, model=…,
    auto_extract=True, extraction_model=…)`: embedding local
    `SEGURAMENTE_EMBEDDING` (default `all-MiniLM-L6-v2`, dim 384) e extração de
    triplas `EPOCHDB_EXTRACTION_MODEL` (default `local` — heurística offline;
    `google:gemini-2.5-flash` enriquece em background com fallback). `query`
    usa `recall_text(pergunta, top_k)` e lê `atom.payload` (o engine não tem
    `query` nem `atom.text`).
  - `MemoriaLocal.query` busca por termos de 4+ caracteres (sem acento),
    ranqueando por nº de ocorrências — recall OR determinístico offline.
  - **Uso da memória (estado `memoria_contexto`)**: supervisor consulta antes
    de planejar; especialistas injetam o bloco no prompt do veredito LLM; o
    Sintetizador repassa ao `resumir_comparacao`. `Persistidor._lembrar` grava
    texto + `metadata.assuntos` e triples `("analise","thread",…)`,
    `("analise","documento",…)`, `(thread,"aborda",<categoria_com_diferença>)`
    e `(<docA>,"compara_com",<docB>)` — o grafo de assuntos do epochDB nasce
    dessas triplas (+ `auto_extract`).

### 4.7 Interface (`app.py`) — três divisões

1. **Sidebar (configs)**: corpus/upload + checkbox **“Acionar OCR nas páginas
   (simulação)”** (`estado.simular_ocr` → `ingestar_documentos(forcar_ocr=…)` →
   `extract_pdf_pages`: dispara `tool:extrair_texto_ocr` por página mesmo com
   texto nativo, preservando o texto nativo na análise), provedor
   (`offline`/`openai`/`groq`/`google`), modelo (default por provedor) e API key
   (password). Chave e modelo digitados são persistidos no `.env` via
   `motor_llm/chaves.py` (`set_key` preserva o resto do arquivo, permissão
   `0600`, override `SEGURAMENTE_ENV_FILE` p/ testes) — auto-save **e** botão
   explícito **“💾 Salvar no .env”** com `st.success` de confirmação; um caption
   mostra o status mascarado (`chave: presente (••••)/ausente`). Pré-preenchidos
   no próximo boot — nunca vão ao estado/checkpoint do grafo.
2. **Chat (centro)**: intermediação com o supervisor — pedido via
   `st.chat_input`, fala do supervisor (plano, gate com pontos, resumo final,
   tabela/evidências em expander) e formulário de decisão do gate no próprio
   chat (retoma via worker).
3. **Orquestra (direita)**: semicírculo ao vivo (repintado a cada poll de
   0,5 s enquanto a análise roda): **maestro** no pé (Supervisor + Gate humano), **1ª fila** com os 12 agentes
   (Ingestor, Extrator, 6 especialistas, Comparador, Revisor, Sintetizador,
   Persistidor) e **2ª fila** com as 4 tools — cada quadrante acende por status
   (`pronto/executando/ok/pausa/falhou/fora do plano`) conforme os eventos da
   telemetria, com glow no executando, badge `⚡n` (ferramentas do contrato),
   progresso `N/M ✓` e legenda de 5 estados. Abaixo, **pills** (`st.pills`)
   escolhem o quadrante e abrem o **cartão mínimo de detalhe**: legenda do
   tipo (🤖 agente / 🔨 ferramenta) + status; especialistas fora do plano
   aparecem esmaecidos com status "fora do plano". Os cartões do semicírculo
   exibem o mesmo ícone de tipo (🤖 nas filas de agentes, 🔨 nas tools).

Execução em background (`threading.Thread` + `guardar_resultado`): a worker
publica `gate`/`fim`/`erro` no bus; o **script principal** consome o desfecho
antes de renderizar o chat (mesma execução, sem rerun de dentro de fragment) e,
enquanto `modo == "rodando"` sem desfecho, dorme 0,5 s e reroda — fonte única
de rerun, com teto de 15 min para worker silenciosa.

## 5. TDD — matriz teste → módulo

Ordem de execução: **testes primeiro (red) → código (green) → ruff → suíte completa.**

| Arquivo de teste | Cobre |
|---|---|
| `tests/test_provedores_llm.py` | registry 3 provedores, fábrica, defaults, modelo por provedor (`*_MODEL` + compat), payload openai/groq, parse gemini, `LLMError` sem chave/HTTP, redação da key do Google (mensagem/capa/traceback), retry transitório (`enviar_post`: 503×2→ok, 400 sem retry, timeout, esgotamento) |
| `tests/test_chaves_env.py` | persistência de chaves/modelos no `.env` (preserva variáveis, sem duplicar, `0600`, vazios ignorados) |
| `tests/test_tools.py` | allowlist (4 tools), `ingestar_documentos` (+ `forcar_ocr` repassado), `comparar_apolices`, `resumir_comparacao` (± bloco de memória), `extrair_texto_ocr` |
| `tests/test_contrato_agente.py` | `ContratoAgente` (validação, ⊆ allowlist, frozenset), contrato dos 9 nós e dos especialistas |
| `tests/test_registro_agentes.py` | decorator `@agente` (registro/erros), `FLUXO`/`FANOUT`/validação, `construir` com `Contexto`, agrupamento do front |
| `tests/test_especialistas.py` | 6 classes individuais (um módulo por área), fatiamento, instrução do supervisor, bloco de memória no prompt, prompt/contrato por especialista |
| `tests/test_telemetria.py` | eventos por thread, wrapper de nó (início/fim/pausa/falhou), telemetria automática das tools, origem por agente |
| `tests/test_estado.py` | serialização JSON-safe round-trip, `add_live_status` |
| `tests/test_gate.py` | regras 1–6 de pontos críticos, caso limpo, auditoria JSONL |
| `tests/test_supervisor.py` | roteamento LLM/keywords, plano tolerante (string/`plan`/`plano`, log de chaves), memória (consulta/contexto/falha), plano reordenado, instruções, mensagem de encerramento, fábrica com `memoria` |
| `tests/test_memoria.py` | epochDB (`model`/`auto_extract`/`extraction_model` por env, `recall_text`, fallback sem pacote, smoke roundtrip skip-if), `MemoriaLocal` por termos, triples de assuntos do Persistidor, `bloco_memoria` |
| `tests/test_grafo_agentes.py` | e2e offline: interrupt→resume, plano restrito, ferramentas via dispatcher (eventos com origem), sem pontos (A,A), checkpoint, `simular_ocr` (estado/node/e2e evento OCR), síntese com contexto de memória |
| `tests/test_app_front.py` | front: pills (18 quadrantes), detalhe mínimo (tipo+status), ícones 🤖/🔨, badges ⚡, fora do plano, arestas do grafo, persistência de chaves no .env (auto-save + botão 💾 + status mascarado), checkbox OCR |
| `tests/test_app_fluxo.py` | fluxo completo via AppTest: pedido → gate → decisão → fim (offline) |
| `tests/test_project_final.py` | regressão do fluxo clássico (inalterado) + `extract_pdf_pages` com/sem `forcar_ocr` |

Critérios de aceite: suíte verde (190 testes, 0 skips); `ruff check .` sem erros; `ruff format` estável;
modo agentes offline reproduz 19 campos/11 diferenças; gate só interrompe com
pontos reais e retoma pelo Streamlit; credidenciais fora do estado/checkpoint.

## 6. Riscos e mitigações

| Risco | Mitigação |
|---|---|
| `hnswlib` sem wheel/toolchain no py3.14 | checkpointer vendorizado; `MemoriaLocal` (JSONL) sempre presente; instalação documentada (`gcc-c++`/`python3-devel`) |
| Chave de API em log/checkpoint | credenciais só na DI; `LLMError` sem headers; causa encadeada já redigida (traceback limpo) |
| 429/503 do provedor em rajada | retry só transitório (`enviar_post`, 5× backoff+jitter+`Retry-After`) limitado por semáforo (2 simultâneas); cota esgotada desiste na 1ª resposta; fallback determinístico preservado e **sinalizado no front** (`fallback_*` + `motivo_degradacao`) |
| Custo LLM em cascata | especialistas só consultam em modo LLM; custo/tokens por chamada no `logger` |
| Quebra do fluxo clássico | pipeline inalterado; testes de regressão |
| Gate travado sem humano | decisão registrada e auditada; retomada por `thread_id` |
