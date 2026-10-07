"""Registro de agentes — registry + decorator `@agente` (fonte única p/ grafo e front).

Todo nó do grafo que deva aparecer na orquestra é decorado com
:data:`agente`; o registro deriva etapa e contrato da própria classe,
eliminando listas duplicadas em `grafo.py` e `app.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeVar

from .contrato import ContratoAgente

Grupo = Literal["maestro", "fila"]
T = TypeVar("T", bound=type)

_REGISTRO: dict[str, RegistroAgente] = {}


@dataclass(frozen=True)
class RegistroAgente:
    """Metadados de um agente registrado (etapa da telemetria → classe)."""

    etapa: str
    classe: type
    contrato: ContratoAgente
    rotulo: str
    ordem: int
    grupo: Grupo


def _resolver_contrato(classe: type) -> ContratoAgente:
    """Lê o contrato da classe (attr simples ou property na base)."""
    attr = next((base.__dict__["contrato"] for base in classe.__mro__ if "contrato" in base.__dict__), None)
    if attr is None:
        raise TypeError(f"{classe.__name__} precisa declarar 'contrato' (ContratoAgente).")
    if isinstance(attr, property):
        try:
            attr = attr.__get__(classe(), classe)
        except TypeError as exc:
            raise TypeError(
                f"{classe.__name__} expõe 'contrato' como property e precisa ser instanciável sem argumentos."
            ) from exc
    if not isinstance(attr, ContratoAgente):
        raise TypeError(f"{classe.__name__}.contrato deve ser ContratoAgente, obteve {type(attr).__name__}.")
    return attr


def agente(*, rotulo: str, ordem: int, grupo: Grupo = "fila") -> type:
    """Registra a classe como agente do grafo (decorator).

    Args:
        rotulo: Rótulo do quadrante no front (etapas do mesmo quadrante
            compartilham o rótulo, ex.: abertura e encerramento do supervisor).
        ordem: Ordem de exibição no front e na ordenação do registro.
        grupo: ``maestro`` (pé do semicírculo) ou ``fila`` (primeira fila).

    Returns:
        A própria classe, com ``contrato`` validado e entrada no registro.
    """

    def decorar(classe: T) -> T:
        if grupo not in ("maestro", "fila"):
            raise ValueError(f"grupo inválido: {grupo!r} (esperado 'maestro' ou 'fila').")
        contrato = _resolver_contrato(classe)
        existente = _REGISTRO.get(contrato.nome)
        if existente is not None:
            raise ValueError(f"etapa '{contrato.nome}' já registrada por {existente.classe.__name__}.")
        _REGISTRO[contrato.nome] = RegistroAgente(
            etapa=contrato.nome,
            classe=classe,
            contrato=contrato,
            rotulo=rotulo,
            ordem=ordem,
            grupo=grupo,
        )
        return classe

    return decorar


def agentes_registrados(*, grupo: Grupo | None = None) -> tuple[RegistroAgente, ...]:
    """Todos os agentes ordenados por ``ordem``, opcionalmente de um grupo."""
    registros = tuple(sorted(_REGISTRO.values(), key=lambda registro: registro.ordem))
    return tuple(registro for registro in registros if grupo is None or registro.grupo == grupo)


def agente_por_etapa(etapa: str) -> RegistroAgente:
    """Registro do agente de uma etapa; ValueError quando não existe."""
    registro = _REGISTRO.get(etapa)
    if registro is None:
        raise ValueError(f"agente não registrado: {etapa!r}.")
    return registro


def agrupar_por_rotulo(grupo: Grupo) -> list[tuple[str, list[str]]]:
    """Quadrantes do front: rótulo → etapas da telemetria (ordem do registro)."""
    por_rotulo: dict[str, list[str]] = {}
    for registro in agentes_registrados(grupo=grupo):
        por_rotulo.setdefault(registro.rotulo, []).append(registro.etapa)
    return list(por_rotulo.items())


def contratos_registrados() -> dict[str, ContratoAgente]:
    """Mapa etapa → contrato de todos os agentes registrados."""
    return {registro.etapa: registro.contrato for registro in agentes_registrados()}


def desregistrar(etapa: str) -> None:
    """Remove uma etapa do registro (testes e recarga em caliente)."""
    _REGISTRO.pop(etapa, None)
