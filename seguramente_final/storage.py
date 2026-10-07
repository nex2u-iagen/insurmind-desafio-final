"""Persistência SQLite do Projeto Final — documentos, páginas, fatos e comparações."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from .models import ComparisonRow, PolicyDocument

SCHEMA_SQL = """
    CREATE TABLE IF NOT EXISTS documents (
        document_id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        path TEXT NOT NULL,
        source TEXT NOT NULL,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
    CREATE TABLE IF NOT EXISTS pages (
        document_id TEXT NOT NULL,
        page_number INTEGER NOT NULL,
        text TEXT NOT NULL,
        extraction_method TEXT NOT NULL,
        PRIMARY KEY(document_id, page_number),
        FOREIGN KEY(document_id) REFERENCES documents(document_id)
    );
    CREATE TABLE IF NOT EXISTS facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        document_id TEXT NOT NULL,
        category TEXT NOT NULL,
        label TEXT NOT NULL,
        value TEXT,
        status TEXT NOT NULL,
        confidence REAL NOT NULL,
        page INTEGER,
        evidence TEXT NOT NULL,
        normalized_value TEXT,
        FOREIGN KEY(document_id) REFERENCES documents(document_id)
    );
    CREATE TABLE IF NOT EXISTS comparisons (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        document_a TEXT NOT NULL,
        document_b TEXT NOT NULL,
        category TEXT NOT NULL,
        label TEXT NOT NULL,
        policy_a TEXT,
        policy_b TEXT,
        difference TEXT NOT NULL,
        status TEXT NOT NULL,
        evidence_a TEXT NOT NULL,
        evidence_b TEXT NOT NULL,
        page_a INTEGER,
        page_b INTEGER,
        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
    );
"""


class PolicyStore:
    """Banco local simples para manter rastreabilidade da análise."""

    def __init__(self, path: str | Path = "data/policies.db") -> None:
        """Abre/cria o banco e garante o schema.

        Args:
            path: Caminho do arquivo SQLite (pai criado se não existir).
        """
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        """Abre uma conexão com ``row_factory`` em :class:`sqlite3.Row`."""
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_schema(self) -> None:
        """Cria as tabelas do modelo (idempotente)."""
        with self._connect() as connection:
            connection.executescript(SCHEMA_SQL)

    def save_document(self, document: PolicyDocument) -> None:
        """Grava documento, páginas e fatos, substituindo registros prévios do mesmo ID.

        Args:
            document: Documento com páginas e fatos já extraídos.
        """
        with self._connect() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO documents(document_id,name,path,source) VALUES (?,?,?,?)",
                (document.document_id, document.name, document.path, document.source),
            )
            connection.execute("DELETE FROM pages WHERE document_id = ?", (document.document_id,))
            connection.execute("DELETE FROM facts WHERE document_id = ?", (document.document_id,))
            connection.executemany(
                "INSERT INTO pages(document_id,page_number,text,extraction_method) VALUES (?,?,?,?)",
                [(page.document_id, page.page_number, page.text, page.extraction_method) for page in document.pages],
            )
            connection.executemany(
                """INSERT INTO facts(document_id,category,label,value,status,confidence,page,evidence,normalized_value)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        fact.document_id,
                        fact.category,
                        fact.label,
                        fact.value,
                        fact.status,
                        fact.confidence,
                        fact.page,
                        fact.evidence,
                        fact.normalized_value,
                    )
                    for fact in document.facts
                ],
            )

    def save_comparison(
        self, document_a: PolicyDocument, document_b: PolicyDocument, rows: list[ComparisonRow]
    ) -> None:
        """Grava as linhas comparativas de um par de documentos (substitui o par anterior).

        Args:
            document_a: Apólice de referência A.
            document_b: Apólice de referência B.
            rows: Linhas da tabela comparativa.
        """
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM comparisons WHERE document_a = ? AND document_b = ?",
                (document_a.document_id, document_b.document_id),
            )
            connection.executemany(
                """INSERT INTO comparisons(document_a,document_b,category,label,policy_a,policy_b,
                       difference,status,evidence_a,evidence_b,page_a,page_b)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
                [
                    (
                        document_a.document_id,
                        document_b.document_id,
                        row.category,
                        row.label,
                        row.policy_a,
                        row.policy_b,
                        row.difference,
                        row.status,
                        row.evidence_a,
                        row.evidence_b,
                        row.page_a,
                        row.page_b,
                    )
                    for row in rows
                ],
            )

    def counts(self) -> dict[str, int]:
        """Conta registros por tabela (documents, pages, facts, comparisons)."""
        with self._connect() as connection:
            return {
                table: int(connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
                for table in ["documents", "pages", "facts", "comparisons"]
            }
