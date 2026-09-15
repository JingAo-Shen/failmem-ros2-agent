import sqlite3
import json
from typing import Dict, Any, List, Optional

class FailureMemoryStore:
    def __init__(self, db_path: str = ":memory:"):
        self.conn = sqlite3.connect(db_path)
        c = self.conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS failure_records (
                id TEXT PRIMARY KEY,
                symptom TEXT,
                context_signature TEXT,
                cause_hypothesis TEXT,
                recovery_action TEXT,
                verified_outcome TEXT,
                map_version INTEGER
            )
        """)
        self.conn.commit()

    def record_failure(self, rec: Dict[str, Any]):
        c = self.conn.cursor()
        c.execute("""
            INSERT OR REPLACE INTO failure_records VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            rec["id"], rec["symptom"], rec.get("context_signature", ""),
            rec.get("cause_hypothesis", ""), rec.get("recovery_action", "clear_costmap"),
            rec.get("verified_outcome", "RECOVERED"), rec.get("map_version", 1)
        ))
        self.conn.commit()

    def retrieve_recovery(self, symptom: str, current_map_version: int, use_memory: bool = True) -> Optional[str]:
        if not use_memory:
            return None
        c = self.conn.cursor()
        c.execute("""
            SELECT recovery_action, map_version FROM failure_records WHERE symptom = ?
        """, (symptom,))
        row = c.fetchone()
        if row:
            action, map_ver = row
            # Expiry rule: if map version changed, old obstacle recovery is stale
            if map_ver <= current_map_version:
                return action
        return None

    def close(self):
        self.conn.close()
