"""Memória de longo prazo das análises — Protocol + fontes local e epochDB."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import unicodedata
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol

logger = logging.getLogger(__name__)

MODELO_EMBEDDING_PADRAO = "all-MiniLM-L6-v2"
TAMANHO_MINIMO_TERMO = 4


class Memoria(Protocol):
    """Contrato mínimo de memória das análises (injetável no persistidor)."""

    def remember(self, texto: str, metadata: dict[str, Any] | None = None, triples: list[tuple] | None = None) -> None:
        """Armazena um registro de memória."""
        ...

    def query(self, pergunta: str, k: int = 3) -> list[str]:
        """Recupera os registros mais relevantes para a pergunta."""
        ...

    def indexar_documentos(self, documentos: list[dict[str, Any]]) -> dict[str, Any]:
        """Indexa os textos extraídos por página na memória vetorial."""
        ...

    def recuperar_trechos(self, pergunta: str, document_ids: list[str], k: int = 2) -> list[dict[str, Any]]:
        """Recupera trechos documentais com a origem preservada."""
        ...

    def finalizar(self) -> None:
        """Persiste o que estava em memória (WAL → frio); no-op quando não há o que flushar."""
        ...


class MemoriaLocal:
    """Memória persistente em JSONL — funciona sem dependências externas."""

    def __init__(self, caminho: str | Path) -> None:
        self.caminho = Path(caminho)

    def remember(self, texto: str, metadata: dict[str, Any] | None = None, triples: list[tuple] | None = None) -> None:
        self.caminho.parent.mkdir(parents=True, exist_ok=True)
        registro = {
            "timestamp": datetime.now(UTC).isoformat(),
            "texto": texto,
            "metadata": metadata or {},
            "triples": [list(triplo) for triplo in triples or []],
        }
        with self.caminho.open("a", encoding="utf-8") as fluxo:
            fluxo.write(json.dumps(registro, ensure_ascii=False, default=str) + "\n")

    def query(self, pergunta: str, k: int = 3) -> list[str]:
        if not self.caminho.exists():
            return []
        termos = _termos_relevantes(pergunta)
        if not termos:
            return []
        correspondencias: list[tuple[int, str]] = []
        for linha in self.caminho.read_text(encoding="utf-8").splitlines():
            try:
                registro = json.loads(linha)
            except ValueError:
                logger.warning("Registro de memória inválido ignorado em %s", self.caminho)
                continue
            texto = str(registro.get("texto", ""))
            alvo = _sem_acento(texto.casefold())
            pontos = sum(1 for termo in termos if termo in alvo)
            if pontos:
                correspondencias.append((pontos, texto))
        correspondencias.sort(key=lambda par: -par[0])  # estável: empates mantêm a ordem de gravação
        return [texto for _, texto in correspondencias[:k]]

    def finalizar(self) -> None:
        """JSONL já é gravado a cada ``remember``; nada a flushar."""

    def indexar_documentos(self, documentos: list[dict[str, Any]]) -> dict[str, Any]:
        """Sinaliza que esta memória textual não mantém índice vetorial documental."""
        return {"available": False, "indexed_pages": 0, "skipped_pages": 0}

    def recuperar_trechos(self, pergunta: str, document_ids: list[str], k: int = 2) -> list[dict[str, Any]]:
        """Memória local guarda resumos de análises, não páginas de apólices."""
        return []


def _sem_acento(texto: str) -> str:
    """Minúsculas sem acentos (``compare retenções`` casa com ``retencoes``)."""
    decomposto = unicodedata.normalize("NFD", texto)
    return "".join(caractere for caractere in decomposto if unicodedata.category(caractere) != "Mn")


def _termos_relevantes(pergunta: str) -> list[str]:
    """Termos com 4+ caracteres da pergunta (busca OR com peso por ocorrências)."""
    padrao = rf"[a-z0-9]{{{TAMANHO_MINIMO_TERMO},}}"
    return re.findall(padrao, _sem_acento(pergunta.casefold()))


class MemoriaEpochDb:
    """Memória consultável via epochDB (vetor + grafo), quando o pacote está disponível."""

    def __init__(self, db: Any, storage_dir: str | Path | None = None) -> None:
        self.db = db
        self.manifest_path = Path(storage_dir) / "documentos_indexados.json" if storage_dir else None

    def indexar_documentos(self, documentos: list[dict[str, Any]]) -> dict[str, Any]:
        """Indexa uma memória por página, com chave estável e proveniência explícita."""
        manifest = self._read_manifest()

        indexed = 0
        skipped = 0
        for documento in documentos:
            document_id = str(documento.get("document_id", ""))
            for pagina in documento.get("pages") or []:
                texto = str(pagina.get("text") or "").strip()
                if not document_id or not texto:
                    continue
                page_number = int(pagina.get("page_number") or 0)
                method = str(pagina.get("extraction_method") or "unknown")
                key = f"{document_id}:{page_number}"
                fingerprint = hashlib.sha256(f"{method}\0{texto}".encode("utf-8")).hexdigest()
                if manifest.get(key) == fingerprint:
                    skipped += 1
                    continue

                chunk_id = hashlib.sha256(f"{key}\0{fingerprint}".encode("utf-8")).hexdigest()[:32]
                page_entity = f"{document_id}:pagina:{page_number}"
                payload = f"[DOCUMENTO id={document_id} pagina={page_number} metodo={method}]\n{texto}"
                self.db.remember(
                    payload,
                    metadata={
                        "kind": "document_page",
                        "chunk_id": chunk_id,
                        "document_id": document_id,
                        "document_name": str(documento.get("name") or document_id),
                        "page_number": page_number,
                        "extraction_method": method,
                        "content_hash": fingerprint,
                    },
                    triples=[
                        (document_id, "has_page", page_entity),
                        (page_entity, "contains_chunk", chunk_id),
                        (chunk_id, "source_document", document_id),
                    ],
                    atom_id=chunk_id,
                )
                manifest[key] = fingerprint
                indexed += 1
                self._save_manifest(manifest)

        return {"available": True, "indexed_pages": indexed, "skipped_pages": skipped}

    def recuperar_trechos(self, pergunta: str, document_ids: list[str], k: int = 2) -> list[dict[str, Any]]:
        """Recupera por similaridade apenas páginas dos documentos solicitados."""
        ids = list(dict.fromkeys(document_ids))
        if not ids:
            return []
        manifest = self._read_manifest() if self.manifest_path is not None else {}
        resultados: list[Any] = []
        for document_id in ids:
            filtros: dict[str, Any] = {"kind": "document_page", "document_id": {"$in": [document_id]}}
            if self.manifest_path is not None:
                chunk_ids = [
                    hashlib.sha256(f"{key}\0{fingerprint}".encode("utf-8")).hexdigest()[:32]
                    for key, fingerprint in manifest.items()
                    if key.split(":", 1)[0] == document_id
                ]
                if not chunk_ids:
                    continue
                filtros["chunk_id"] = {"$in": chunk_ids}
            resultados.extend(self.db.query(pergunta, k=k, filters=filtros, expand_hops=0))
        trechos: list[dict[str, Any]] = []
        por_documento: dict[str, int] = {}
        paginas_vistas: set[tuple[str, int]] = set()
        for item in resultados:
            metadata = getattr(item, "metadata", {}) or {}
            document_id = str(metadata.get("document_id", ""))
            page_number = int(metadata.get("page_number") or 0)
            chave_pagina = (document_id, page_number)
            if document_id not in ids or chave_pagina in paginas_vistas:
                continue
            if por_documento.get(document_id, 0) >= k:
                continue
            texto = str(getattr(item, "text", "") or "").strip()
            prefixo = f"[DOCUMENTO id={document_id} pagina={page_number} metodo="
            if texto.startswith(prefixo):
                texto = texto.split("\n", 1)[-1].strip()
            if not texto:
                continue
            trechos.append(
                {
                    "document_id": document_id,
                    "document_name": str(metadata.get("document_name") or document_id),
                    "page_number": page_number,
                    "extraction_method": str(metadata.get("extraction_method") or "unknown"),
                    "text": texto[:2400],
                }
            )
            paginas_vistas.add(chave_pagina)
            por_documento[document_id] = por_documento.get(document_id, 0) + 1
        return trechos

    def _read_manifest(self) -> dict[str, str]:
        if self.manifest_path is None or not self.manifest_path.exists():
            return {}
        try:
            return json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            logger.warning("Manifesto de indexação epochDB inválido; será reconstruído.")
            return {}

    def _save_manifest(self, manifest: dict[str, str]) -> None:
        if self.manifest_path is None:
            return
        self.manifest_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.manifest_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, sort_keys=True), encoding="utf-8")
        temporary.replace(self.manifest_path)

    def remember(self, texto: str, metadata: dict[str, Any] | None = None, triples: list[tuple] | None = None) -> None:
        kwargs: dict[str, Any] = {"metadata": metadata or {}}
        if triples:
            kwargs["triples"] = list(triples)
        self.db.remember(texto, **kwargs)

    def query(self, pergunta: str, k: int = 3) -> list[str]:
        resultados = self.db.recall_text(pergunta, top_k=k)
        textos: list[str] = []
        for item in resultados:
            payload = getattr(item, "payload", None)
            textos.append(payload if isinstance(payload, str) else str(item))
        return textos[:k]

    def finalizar(self) -> None:
        """Espera as extrações de triplas e persiste o hot tier (WAL → parquet/HNSW).

        Sem este passo o epochDB mantém os atoms só no WAL em memória: a cada
        reinício o replay os restaura (log ``uncommitted``), o WAL cresce sem
        limite e o índice vetorial frio nunca é gravado.
        """
        esperar = getattr(self.db, "wait_for_extractions", None)
        if callable(esperar):
            try:
                esperar(timeout=30.0)
            except Exception as exc:  # noqa: BLE001 — persistência é melhor esforço.
                logger.warning("Espera de extrações do epochDB falhou (%s: %s); seguindo.", type(exc).__name__, exc)
        flushar = getattr(self.db, "flush", None)
        if not callable(flushar):
            return
        try:
            flushar()
        except Exception as exc:  # noqa: BLE001 — memória nunca derruba a análise concluída.
            logger.warning("Flush do epochDB falhou (%s: %s); átomos seguem no WAL.", type(exc).__name__, exc)

    @classmethod
    def tentar_criar(cls, storage_dir: str | Path) -> Memoria | None:
        """Instancia o epochDB; devolve ``None`` quando indisponível (ex.: hnswlib ausente).

        O vetor usa embedding local (``SEGURAMENTE_EMBEDDING``, default
        ``all-MiniLM-L6-v2``) e a extração de triplas nasce offline
        (``EPOCHDB_EXTRACTION_MODEL``, default ``local``), com ``auto_extract``
        semeando o grafo de assuntos em cada ``remember``.
        """
        try:
            from epochdb import EpochDB

            modelo = os.getenv("SEGURAMENTE_EMBEDDING") or MODELO_EMBEDDING_PADRAO
            extracao = os.getenv("EPOCHDB_EXTRACTION_MODEL") or "local"
            return cls(
                EpochDB(
                    storage_dir=str(storage_dir),
                    model=modelo,
                    auto_extract=True,
                    extraction_model=extracao,
                ),
                storage_dir,
            )
        except Exception as exc:  # noqa: BLE001 — fallback documentado para dependência nativa ausente.
            logger.warning("epochDB indisponível (%s: %s); usando apenas MemoriaLocal.", type(exc).__name__, exc)
            return None


def criar_memoria(diretorio: str | Path) -> Memoria:
    """Fabrica a memória: JSONL local sempre + epochDB quando disponível."""
    diretorio = Path(diretorio)
    fontes: list[Memoria] = []
    epoch = MemoriaEpochDb.tentar_criar(diretorio)
    if epoch is not None:
        fontes.append(epoch)
    fontes.append(MemoriaLocal(diretorio / "registros.jsonl"))
    if len(fontes) == 1:
        return fontes[0]
    return MemoriaComposta(fontes)


class MemoriaComposta:
    """Compõe várias fontes de memória (registro local + índice epochDB)."""

    def __init__(self, fontes: list[Memoria]) -> None:
        self.fontes = fontes

    def remember(self, texto: str, metadata: dict[str, Any] | None = None, triples: list[tuple] | None = None) -> None:
        for fonte in self.fontes:
            try:
                fonte.remember(texto, metadata=metadata, triples=triples)
            except Exception as exc:  # noqa: BLE001 — uma fonte falha não pode impedir as demais.
                logger.warning("Fonte de memória falhou (%s: %s); demais fontes seguem.", type(exc).__name__, exc)

    def query(self, pergunta: str, k: int = 3) -> list[str]:
        vistos: list[str] = []
        for fonte in self.fontes:
            try:
                for texto in fonte.query(pergunta, k=k):
                    if texto not in vistos:
                        vistos.append(texto)
            except Exception as exc:  # noqa: BLE001 — consulta degradada, não derruba a resposta.
                logger.warning(
                    "Consulta de memória falhou (%s: %s); seguindo com as demais fontes.", type(exc).__name__, exc
                )
        return vistos[:k]

    def finalizar(self) -> None:
        """Persiste cada fonte (a epochDB faz flush do WAL; a local é no-op)."""
        for fonte in self.fontes:
            finalizar = getattr(fonte, "finalizar", None)
            if not callable(finalizar):
                continue
            try:
                finalizar()
            except Exception as exc:  # noqa: BLE001 — persistência nunca derruba a análise.
                logger.warning(
                    "Finalização da fonte %s falhou (%s: %s).", type(fonte).__name__, type(exc).__name__, exc
                )

    def indexar_documentos(self, documentos: list[dict[str, Any]]) -> dict[str, Any]:
        """Indexa documentos somente nas fontes vetoriais, sem duplicá-los no JSONL."""
        fontes = [fonte for fonte in self.fontes if isinstance(fonte, MemoriaEpochDb)]
        if not fontes:
            return {"available": False, "indexed_pages": 0, "skipped_pages": 0}
        resultado = {"available": True, "indexed_pages": 0, "skipped_pages": 0}
        for fonte in fontes:
            parcial = fonte.indexar_documentos(documentos)
            resultado["indexed_pages"] += int(parcial.get("indexed_pages", 0))
            resultado["skipped_pages"] += int(parcial.get("skipped_pages", 0))
        return resultado

    def recuperar_trechos(self, pergunta: str, document_ids: list[str], k: int = 2) -> list[dict[str, Any]]:
        """Consulta as fontes epochDB; resumos locais não são tratados como evidência documental."""
        trechos: list[dict[str, Any]] = []
        for fonte in self.fontes:
            if not isinstance(fonte, MemoriaEpochDb):
                continue
            trechos.extend(fonte.recuperar_trechos(pergunta, document_ids, k=k))
        return trechos
