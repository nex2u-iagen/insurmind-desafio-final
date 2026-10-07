"""Agentes do grafo D&O — supervisor, especialistas, gate humano e orquestração."""

from __future__ import annotations

from . import nodes  # noqa: F401 — popula o registro (@agente) junto com gate/supervisor
from .contrato import ContratoAgente
from .estado import EstadoAnalise, adicionar_live_status, novo_status, reidratar_documento, serializar_documento
from .gate import GateHumano, calcular_pontos_criticos, registrar_auditoria
from .registro import RegistroAgente, agente, agente_por_etapa, agentes_registrados, agrupar_por_rotulo
from .supervisor import ESPECIALISTAS, SupervisorAbertura, SupervisorEncerramento

__all__ = [
    "ESPECIALISTAS",
    "ContratoAgente",
    "EstadoAnalise",
    "GateHumano",
    "RegistroAgente",
    "SupervisorAbertura",
    "SupervisorEncerramento",
    "adicionar_live_status",
    "agente",
    "agente_por_etapa",
    "agentes_registrados",
    "agrupar_por_rotulo",
    "calcular_pontos_criticos",
    "novo_status",
    "registrar_auditoria",
    "reidratar_documento",
    "serializar_documento",
]
