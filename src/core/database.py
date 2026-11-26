"""Warstwa persystencji SQLite dla historii weryfikacji, zadań wsadowych, audytu i list sankcyjnych."""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from src.config import DB_PATH


class Database:
    """Repozytorium SQLite z obsługą trybu WAL i bezpiecznych połączeń."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA foreign_keys=ON;")
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def init_schema(self) -> None:
        """Tworzy tabele i indeksy jeśli jeszcze nie istnieją."""
        with self.connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS verifications (
                    id TEXT PRIMARY KEY,
                    identifier TEXT NOT NULL,
                    identifier_kind TEXT NOT NULL,
                    nip TEXT,
                    krs TEXT,
                    regon TEXT,
                    nazwa TEXT NOT NULL,
                    forma_prawna TEXT NOT NULL,
                    poziom_ryzyka TEXT NOT NULL,
                    decyzja TEXT NOT NULL,
                    analyst_status TEXT NOT NULL DEFAULT 'AUTO',
                    status_vat TEXT,
                    status_rachunku TEXT,
                    blad_polaczenia INTEGER NOT NULL DEFAULT 0,
                    sankcje_hit INTEGER NOT NULL DEFAULT 0,
                    status_pep INTEGER NOT NULL DEFAULT 0,
                    sha256_hash TEXT NOT NULL,
                    mf_request_id TEXT,
                    card_json TEXT NOT NULL,
                    batch_id TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_verifications_identifier ON verifications(identifier);
                CREATE INDEX IF NOT EXISTS idx_verifications_nip ON verifications(nip);
                CREATE INDEX IF NOT EXISTS idx_verifications_created ON verifications(created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_verifications_batch ON verifications(batch_id);

                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    verification_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    previous_decision TEXT,
                    new_decision TEXT,
                    note TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (verification_id) REFERENCES verifications(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_audit_verification ON audit_events(verification_id);

                CREATE TABLE IF NOT EXISTS batch_jobs (
                    id TEXT PRIMARY KEY,
                    filename TEXT,
                    status TEXT NOT NULL,
                    total_count INTEGER NOT NULL DEFAULT 0,
                    processed_count INTEGER NOT NULL DEFAULT 0,
                    summary_json TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL,
                    finished_at TEXT
                );

                CREATE TABLE IF NOT EXISTS sanction_entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    entry_type TEXT NOT NULL,
                    name TEXT NOT NULL,
                    normalized_name TEXT NOT NULL,
                    nip TEXT,
                    krs TEXT,
                    aliases_json TEXT,
                    reason TEXT,
                    listed_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_sanctions_nip ON sanction_entries(nip);
                CREATE INDEX IF NOT EXISTS idx_sanctions_source ON sanction_entries(source);

                CREATE TABLE IF NOT EXISTS sanction_sync_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source TEXT NOT NULL,
                    status TEXT NOT NULL,
                    entries_count INTEGER NOT NULL DEFAULT 0,
                    message TEXT,
                    synced_at TEXT NOT NULL
                );
                """
            )

    def save_verification(self, record: Dict[str, Any]) -> None:
        """Zapisuje lub aktualizuje kartę weryfikacji w bazie."""
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO verifications (
                    id, identifier, identifier_kind, nip, krs, regon, nazwa, forma_prawna,
                    poziom_ryzyka, decyzja, analyst_status, status_vat, status_rachunku,
                    blad_polaczenia, sankcje_hit, status_pep, sha256_hash, mf_request_id,
                    card_json, batch_id, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    poziom_ryzyka = excluded.poziom_ryzyka,
                    decyzja = excluded.decyzja,
                    analyst_status = excluded.analyst_status,
                    card_json = excluded.card_json,
                    updated_at = excluded.updated_at
                """,
                (
                    record["id"],
                    record["identifier"],
                    record.get("identifier_kind", "NIP"),
                    record.get("nip"),
                    record.get("krs"),
                    record.get("regon"),
                    record.get("nazwa", "Podmiot"),
                    record.get("forma_prawna", "NIEZNANA"),
                    record.get("poziom_ryzyka", "NISKIE"),
                    record.get("decyzja", "AKCEPTACJA"),
                    record.get("analyst_status", "AUTO"),
                    record.get("status_vat"),
                    record.get("status_rachunku"),
                    1 if record.get("blad_polaczenia") else 0,
                    1 if record.get("sankcje_hit") else 0,
                    1 if record.get("status_pep") else 0,
                    record["sha256_hash"],
                    record.get("mf_request_id"),
                    record["card_json"],
                    record.get("batch_id"),
                    record.get("created_at", now),
                    now,
                ),
            )

    def get_verification_by_id(self, verification_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM verifications WHERE id = ?", (verification_id,)).fetchone()
            return dict(row) if row else None

    def get_latest_valid_cached_verification(
        self, identifier: str, ttl_hours: int = 24
    ) -> Optional[Dict[str, Any]]:
        """Zwraca najnowszą kompletną (nie-offline) weryfikację z ostatnich `ttl_hours` godzin."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=ttl_hours)).isoformat()
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM verifications
                WHERE (identifier = ? OR nip = ?)
                  AND blad_polaczenia = 0
                  AND created_at >= ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (identifier, identifier, cutoff),
            ).fetchone()
            return dict(row) if row else None

    def list_verifications(
        self,
        query: Optional[str] = None,
        risk_level: Optional[str] = None,
        offline_only: bool = False,
        batch_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM verifications WHERE 1=1"
        params: List[Any] = []
        if query and query.strip():
            like = f"%{query.strip()}%"
            sql += " AND (identifier LIKE ? OR nip LIKE ? OR krs LIKE ? OR nazwa LIKE ?)"
            params.extend([like, like, like, like])
        if risk_level and risk_level.strip():
            sql += " AND poziom_ryzyka = ?"
            params.append(risk_level.strip())
        if offline_only:
            sql += " AND blad_polaczenia = 1"
        if batch_id:
            sql += " AND batch_id = ?"
            params.append(batch_id)
        sql += " ORDER BY created_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            return [dict(r) for r in rows]

    def delete_verification(self, verification_id: str) -> bool:
        """Usuwa pojedynczą weryfikację oraz powiązane zdarzenia audytowe."""
        with self.connect() as conn:
            conn.execute("DELETE FROM audit_events WHERE verification_id = ?", (verification_id,))
            cur = conn.execute("DELETE FROM verifications WHERE id = ?", (verification_id,))
            return cur.rowcount > 0

    def delete_all_verifications(self) -> int:
        """Usuwa całą historię weryfikacji i zdarzeń audytowych."""
        with self.connect() as conn:
            conn.execute("DELETE FROM audit_events")
            cur = conn.execute("DELETE FROM verifications")
            return cur.rowcount

    def get_verification_stats(self) -> Dict[str, int]:
        with self.connect() as conn:
            row = conn.execute(
                """
                SELECT
                    COUNT(*) AS total,
                    SUM(CASE WHEN poziom_ryzyka = 'NISKIE' AND blad_polaczenia = 0 THEN 1 ELSE 0 END) AS low_risk,
                    SUM(CASE WHEN poziom_ryzyka = 'SREDNIE' AND blad_polaczenia = 0 THEN 1 ELSE 0 END) AS medium_risk,
                    SUM(CASE WHEN poziom_ryzyka = 'WYSOKIE' THEN 1 ELSE 0 END) AS high_risk,
                    SUM(CASE WHEN poziom_ryzyka = 'KRYTYCZNE_STOP' THEN 1 ELSE 0 END) AS critical_stop,
                    SUM(CASE WHEN blad_polaczenia = 1 THEN 1 ELSE 0 END) AS offline_errors
                FROM verifications
                """
            ).fetchone()
            if not row:
                return {"total": 0, "low_risk": 0, "medium_risk": 0, "high_risk": 0, "critical_stop": 0, "offline_errors": 0}
            return {k: int(row[k] or 0) for k in row.keys()}

    def add_audit_event(
        self,
        verification_id: str,
        actor: str,
        action: str,
        previous_decision: Optional[str],
        new_decision: Optional[str],
        note: str = "",
    ) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO audit_events (verification_id, actor, action, previous_decision, new_decision, note, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (verification_id, actor, action, previous_decision, new_decision, note, now),
            )

    def list_audit_events(self, verification_id: str) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM audit_events WHERE verification_id = ? ORDER BY id DESC",
                (verification_id,),
            ).fetchall()
            return [dict(r) for r in rows]

    def create_batch_job(self, batch_id: str, filename: str, total_count: int) -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO batch_jobs (id, filename, status, total_count, processed_count, created_at)
                VALUES (?, ?, 'RUNNING', ?, 0, ?)
                """,
                (batch_id, filename, total_count, now),
            )

    def update_batch_job(
        self,
        batch_id: str,
        status: Optional[str] = None,
        processed_count: Optional[int] = None,
        summary: Optional[Dict[str, Any]] = None,
        error_message: Optional[str] = None,
    ) -> None:
        fields: List[str] = []
        params: List[Any] = []
        if status is not None:
            fields.append("status = ?")
            params.append(status)
            if status in ("COMPLETED", "FAILED"):
                fields.append("finished_at = ?")
                params.append(datetime.now(timezone.utc).isoformat())
        if processed_count is not None:
            fields.append("processed_count = ?")
            params.append(processed_count)
        if summary is not None:
            fields.append("summary_json = ?")
            params.append(json.dumps(summary, ensure_ascii=False))
        if error_message is not None:
            fields.append("error_message = ?")
            params.append(error_message)
        if not fields:
            return
        params.append(batch_id)
        with self.connect() as conn:
            conn.execute(f"UPDATE batch_jobs SET {', '.join(fields)} WHERE id = ?", params)

    def get_batch_job(self, batch_id: str) -> Optional[Dict[str, Any]]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM batch_jobs WHERE id = ?", (batch_id,)).fetchone()
            if not row:
                return None
            data = dict(row)
            if data.get("summary_json"):
                try:
                    data["summary"] = json.loads(data["summary_json"])
                except Exception:
                    data["summary"] = None
            else:
                data["summary"] = None
            return data

    def list_batch_jobs(self, limit: int = 20) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM batch_jobs ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                if d.get("summary_json"):
                    try:
                        d["summary"] = json.loads(d["summary_json"])
                    except Exception:
                        d["summary"] = None
                else:
                    d["summary"] = None
                result.append(d)
            return result

    def replace_sanctions_for_source(self, source: str, entries: List[Dict[str, Any]]) -> int:
        """Atomowo podmienia wpisy sankcyjne dla danego źródła."""
        with self.connect() as conn:
            conn.execute("DELETE FROM sanction_entries WHERE source = ?", (source,))
            for e in entries:
                conn.execute(
                    """
                    INSERT INTO sanction_entries (source, entry_type, name, normalized_name, nip, krs, aliases_json, reason, listed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        source,
                        e["entry_type"],
                        e["name"],
                        e["normalized_name"],
                        e.get("nip"),
                        e.get("krs"),
                        json.dumps(e.get("aliases") or [], ensure_ascii=False),
                        e.get("reason", ""),
                        e.get("listed_at", ""),
                    ),
                )
        return len(entries)

    def list_sanction_entries(self, source: Optional[str] = None, limit: Optional[int] = None, offset: int = 0) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM sanction_entries"
        params: List[Any] = []
        if source:
            sql += " WHERE source = ?"
            params.append(source)
        sql += " ORDER BY id ASC"
        if limit is not None:
            sql += " LIMIT ? OFFSET ?"
            params.extend([limit, offset])
        with self.connect() as conn:
            rows = conn.execute(sql, params).fetchall()
            out: List[Dict[str, Any]] = []
            for r in rows:
                d = dict(r)
                try:
                    d["aliases"] = json.loads(d.get("aliases_json") or "[]")
                except Exception:
                    d["aliases"] = []
                out.append(d)
            return out

    def count_sanctions_by_source(self) -> Dict[str, int]:
        with self.connect() as conn:
            rows = conn.execute("SELECT source, COUNT(*) AS cnt FROM sanction_entries GROUP BY source").fetchall()
            return {r["source"]: int(r["cnt"]) for r in rows}

    def log_sanction_sync(self, source: str, status: str, entries_count: int, message: str = "") -> None:
        now = datetime.now(timezone.utc).isoformat()
        with self.connect() as conn:
            conn.execute(
                """
                INSERT INTO sanction_sync_log (source, status, entries_count, message, synced_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (source, status, entries_count, message, now),
            )

    def get_last_sanction_syncs(self) -> List[Dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                """
                SELECT s1.*
                FROM sanction_sync_log s1
                INNER JOIN (
                    SELECT source, MAX(id) AS max_id
                    FROM sanction_sync_log
                    GROUP BY source
                ) s2 ON s1.id = s2.max_id
                ORDER BY s1.source
                """
            ).fetchall()
            return [dict(r) for r in rows]
