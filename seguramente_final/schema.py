"""Schema D&O didático — 19 campos comparáveis entre duas apólices."""

from __future__ import annotations

FIELD_DEFINITIONS: list[dict[str, str]] = [
    {"category": "identificacao", "label": "Seguradora"},
    {"category": "identificacao", "label": "Vigência"},
    {"category": "identificacao", "label": "Âmbito geográfico"},
    {"category": "limites", "label": "Limite máximo de responsabilidade"},
    {"category": "limites", "label": "Limite agregado"},
    {"category": "retencoes", "label": "Franquia / retenção"},
    {"category": "coberturas", "label": "Cobertura A — indenização ao segurado"},
    {"category": "coberturas", "label": "Cobertura B — reembolso à sociedade"},
    {"category": "coberturas", "label": "Cobertura C — entidade"},
    {"category": "coberturas", "label": "Custos de defesa"},
    {"category": "extensoes", "label": "Custos de investigação"},
    {"category": "extensoes", "label": "Novas subsidiárias"},
    {"category": "extensoes", "label": "Período adicional de notificação"},
    {"category": "exclusoes", "label": "Fraude ou dolo"},
    {"category": "exclusoes", "label": "Danos corporais ou materiais"},
    {"category": "exclusoes", "label": "Poluição"},
    {"category": "condicoes", "label": "Notificação de reclamações"},
    {"category": "condicoes", "label": "Mudança de controle"},
    {"category": "condicoes", "label": "Acordos e consentimento"},
]
"""Campos (categoria + rótulo) extraídos e comparados por ambos os providers."""
