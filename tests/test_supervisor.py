"""Testes TDD do supervisor — roteamento dinâmico, instruções e intermediação."""

from __future__ import annotations

from seguramente_final.agentes.supervisor import SupervisorAbertura, SupervisorEncerramento

CATALOGO = [
    "identificacao",
    "limites",
    "coberturas",
    "extensoes",
    "exclusoes",
    "condicoes",
]


class ClienteRotulo:
    """Stub de cliente LLM: devolve resposta pré-gravada ou falha, e grava o prompt."""

    def __init__(self, resposta=None, erro: Exception | None = None) -> None:
        self.resposta = resposta
        self.erro = erro
        self.mensagens: list = []

    def chat_json(self, mensagens: list) -> dict:
        self.mensagens.append(mensagens)
        if self.erro is not None:
            raise self.erro
        return self.resposta


def test_abertura_keywords_roteiam_para_subset():
    supervisor = SupervisorAbertura()
    parcial = supervisor({"caminhos": ["a.pdf", "b.pdf"], "pedido_usuario": "compare coberturas e exclusões"})
    assert parcial["plano"] == ["coberturas", "exclusoes"]
    assert "Supervisor" in parcial["mensagem_supervisor"]
    assert "compare coberturas e exclusões" in parcial["mensagem_supervisor"]
    assert parcial["live_status"][0]["etapa"] == "supervisor_abertura"


def test_abertura_sem_match_de_keywords_despacha_todos():
    supervisor = SupervisorAbertura()
    parcial = supervisor({"caminhos": ["a.pdf", "b.pdf"], "pedido_usuario": "comparação geral das apólices"})
    assert parcial["plano"] == CATALOGO


def test_abertura_keywords_sao_insensiveis_a_acentos():
    supervisor = SupervisorAbertura()
    parcial = supervisor({"caminhos": ["a.pdf", "b.pdf"], "pedido_usuario": "compare as retenções"})
    assert parcial["plano"] == ["limites"]


def test_abertura_sem_pedido_usa_padrao():
    supervisor = SupervisorAbertura()
    parcial = supervisor({"caminhos": ["a.pdf", "b.pdf"]})
    assert parcial["pedido_usuario"]
    assert parcial["plano"] == ["limites", "coberturas", "exclusoes", "condicoes"]


def test_abertura_gera_instrucoes_para_cada_especialista_do_plano():
    supervisor = SupervisorAbertura()
    pedido = "compare os limites e as coberturas"
    parcial = supervisor({"caminhos": ["a.pdf", "b.pdf"], "pedido_usuario": pedido})
    assert set(parcial["instrucoes"]) == set(parcial["plano"])
    assert all(parcial["instrucoes"][nome] == pedido for nome in parcial["plano"])


def test_abertura_com_llm_roteia_para_subset_com_instrucoes():
    cliente = ClienteRotulo(
        resposta={
            "especialistas": ["coberturas", "limites"],
            "instrucoes": {"coberturas": "cláusulas B e custos", "limites": "só o limite agregado"},
        }
    )
    supervisor = SupervisorAbertura(cliente=cliente)
    parcial = supervisor({"caminhos": ["a.pdf", "b.pdf"], "pedido_usuario": "compare"})
    assert parcial["plano"] == ["limites", "coberturas"]
    assert parcial["instrucoes"] == {
        "limites": "só o limite agregado",
        "coberturas": "cláusulas B e custos",
    }
    system = cliente.mensagens[0][0]
    assert system["role"] == "system"
    assert system["content"] == supervisor.contrato.prompt_sistema


def test_abertura_com_llm_sem_instrucao_usa_o_pedido():
    cliente = ClienteRotulo(resposta={"especialistas": ["coberturas"]})
    supervisor = SupervisorAbertura(cliente=cliente)
    parcial = supervisor({"caminhos": ["a.pdf", "b.pdf"], "pedido_usuario": "compare coberturas"})
    assert parcial["plano"] == ["coberturas"]
    assert parcial["instrucoes"]["coberturas"] == "compare coberturas"


def test_abertura_llm_com_nomes_invalidos_cai_para_keywords():
    cliente = ClienteRotulo(resposta={"especialistas": ["judiciais", "penais"]})
    supervisor = SupervisorAbertura(cliente=cliente)
    parcial = supervisor({"caminhos": ["a.pdf", "b.pdf"], "pedido_usuario": "compare limites"})
    assert parcial["plano"] == ["limites"]


def test_abertura_llm_que_falha_cai_para_keywords():
    cliente = ClienteRotulo(erro=RuntimeError("provedor fora do ar"))
    supervisor = SupervisorAbertura(cliente=cliente)
    parcial = supervisor({"caminhos": ["a.pdf", "b.pdf"], "pedido_usuario": "compare exclusões"})
    assert parcial["plano"] == ["exclusoes"]


def test_abertura_llm_aceita_especialistas_como_string_separado():
    cliente = ClienteRotulo(resposta={"especialistas": "limites, coberturas"})
    supervisor = SupervisorAbertura(cliente=cliente)
    parcial = supervisor({"caminhos": ["a.pdf", "b.pdf"], "pedido_usuario": "compare"})
    assert parcial["plano"] == ["limites", "coberturas"]
    assert set(parcial["instrucoes"]) == {"limites", "coberturas"}


def test_abertura_llm_aceita_chave_alternativa_plan():
    cliente = ClienteRotulo(resposta={"plan": ["exclusoes"]})
    supervisor = SupervisorAbertura(cliente=cliente)
    parcial = supervisor({"caminhos": ["a.pdf", "b.pdf"], "pedido_usuario": "compare"})
    assert parcial["plano"] == ["exclusoes"]


def test_abertura_llm_aceita_chave_alternativa_plano():
    cliente = ClienteRotulo(resposta={"plano": ["condicoes", "fora_do_catalogo"]})
    supervisor = SupervisorAbertura(cliente=cliente)
    parcial = supervisor({"caminhos": ["a.pdf", "b.pdf"], "pedido_usuario": "compare"})
    assert parcial["plano"] == ["condicoes"]


def test_abertura_llm_resposta_invalida_loga_chaves_recebidas(caplog):
    import logging

    cliente = ClienteRotulo(resposta={"rota": ["a"], "notas": "x"})
    supervisor = SupervisorAbertura(cliente=cliente)
    with caplog.at_level(logging.WARNING, logger="seguramente_final.agentes.supervisor"):
        parcial = supervisor({"caminhos": ["a.pdf", "b.pdf"], "pedido_usuario": "compare limites"})
    assert parcial["plano"] == ["limites"]  # fallback keywords
    assert "rota" in caplog.text and "notas" in caplog.text


def test_abertura_llm_normaliza_nomes_acentuados_e_maiusculos():
    cliente = ClienteRotulo(resposta={"especialistas": ["Identificação", "LIMITES"]})
    supervisor = SupervisorAbertura(cliente=cliente)
    parcial = supervisor({"caminhos": ["a.pdf", "b.pdf"], "pedido_usuario": "compare"})
    assert parcial["plano"] == ["identificacao", "limites"]


def test_abertura_llm_casa_por_conteudo_nome_longo():
    cliente = ClienteRotulo(resposta={"especialistas": ["Limites de responsabilidade"]})
    supervisor = SupervisorAbertura(cliente=cliente)
    parcial = supervisor({"caminhos": ["a.pdf", "b.pdf"], "pedido_usuario": "compare"})
    assert parcial["plano"] == ["limites"]


def test_abertura_llm_mapeia_instrucoes_com_chave_acentuada():
    cliente = ClienteRotulo(
        resposta={"especialistas": ["Coberturas"], "instrucoes": {"Coberturas": "cláusulas de defesa"}}
    )
    supervisor = SupervisorAbertura(cliente=cliente)
    parcial = supervisor({"caminhos": ["a.pdf", "b.pdf"], "pedido_usuario": "compare"})
    assert parcial["plano"] == ["coberturas"]
    assert parcial["instrucoes"] == {"coberturas": "cláusulas de defesa"}


def test_abertura_llm_loga_nomes_fora_do_catalogo(caplog):
    import logging

    cliente = ClienteRotulo(resposta={"especialistas": ["judiciais", "penais"]})
    supervisor = SupervisorAbertura(cliente=cliente)
    with caplog.at_level(logging.WARNING, logger="seguramente_final.agentes.supervisor"):
        parcial = supervisor({"caminhos": ["a.pdf", "b.pdf"], "pedido_usuario": "compare limites"})
    assert parcial["plano"] == ["limites"]
    assert "judiciais" in caplog.text


def test_prompt_sistema_lista_catalogo():
    supervisor = SupervisorAbertura()
    for nome in CATALOGO:
        assert nome in supervisor.contrato.prompt_sistema


def test_abertura_rejeita_menos_de_duas_apolices():
    supervisor = SupervisorAbertura()
    try:
        supervisor({"caminhos": ["a.pdf"]})
        raise AssertionError("deveria levantar ValueError")
    except ValueError as exc:
        assert "duas" in str(exc)


def test_encerramento_redige_mensagem_com_contagens_e_decisao():
    supervisor = SupervisorEncerramento()
    parcial = supervisor(
        {
            "documentos": [{"pages": []}, {"pages": []}],
            "comparacao": [{"status": "diferente"}, {"status": "igual"}],
            "pontos": [{"codigo": "divergencia_material"}],
            "decisao_humana": {"acao": "aprovado", "comentario": "ok"},
        }
    )
    mensagem = parcial["mensagem_supervisor"]
    assert "Supervisor" in mensagem
    assert "1" in mensagem  # 1 diferença
    assert "aprovado" in mensagem
    assert parcial["live_status"][0]["etapa"] == "supervisor_encerramento"


class MemoriaFalsa:
    """Stub de memória: grava consultas e devolve retornos pré-gravados."""

    def __init__(self, retornos: list[str] | None = None, erro: Exception | None = None) -> None:
        self.retornos = retornos or []
        self.erro = erro
        self.consultas: list[tuple[str, int]] = []

    def remember(self, texto: str, metadata=None, triples=None) -> None:
        pass

    def query(self, pergunta: str, k: int = 3) -> list[str]:
        self.consultas.append((pergunta, k))
        if self.erro is not None:
            raise self.erro
        return self.retornos


def test_abertura_consulta_memoria_e_publica_contexto():
    memoria = MemoriaFalsa(retornos=["limite divergiu na análise anterior"])
    supervisor = SupervisorAbertura(memoria=memoria)
    parcial = supervisor({"caminhos": ["a.pdf", "b.pdf"], "pedido_usuario": "compare os limites"})
    assert memoria.consultas == [("compare os limites", 3)]
    assert parcial["memoria_contexto"] == ["limite divergiu na análise anterior"]
    assert parcial["plano"] == ["limites"]


def test_abertura_sem_memoria_publica_contexto_vazio():
    supervisor = SupervisorAbertura()
    parcial = supervisor({"caminhos": ["a.pdf", "b.pdf"], "pedido_usuario": "compare limites"})
    assert parcial["memoria_contexto"] == []


def test_abertura_memoria_que_falha_nao_derruba_o_plano(caplog):
    import logging

    memoria = MemoriaFalsa(erro=RuntimeError("índice quebrado"))
    supervisor = SupervisorAbertura(memoria=memoria)
    with caplog.at_level(logging.WARNING, logger="seguramente_final.agentes.supervisor"):
        parcial = supervisor({"caminhos": ["a.pdf", "b.pdf"], "pedido_usuario": "compare exclusões"})
    assert parcial["memoria_contexto"] == []
    assert parcial["plano"] == ["exclusoes"]
    assert "mem" in caplog.text.lower()


def test_fabrica_do_supervisor_recebe_a_memoria_do_contexto():
    from seguramente_final.agentes.fluxo import FABRICAS, Contexto

    class MemoriaSimples:
        pass

    memoria = MemoriaSimples()
    supervisor = FABRICAS["supervisor_abertura"](Contexto(memoria=memoria))
    assert supervisor.memoria is memoria
