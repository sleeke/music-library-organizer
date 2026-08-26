"""SQLite-backed index of the music library: files, suggestions, dismissals."""
import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

SCHEMA = """
CREATE TABLE IF NOT EXISTS files (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  path TEXT UNIQUE NOT NULL,
  filename TEXT,
  size INTEGER, mtime REAL, checksum TEXT,
  duration REAL, bitrate INTEGER,
  artist TEXT, albumartist TEXT, album TEXT, title TEXT, tracknumber TEXT,
  error TEXT
);
CREATE INDEX IF NOT EXISTS idx_files_checksum ON files(checksum);
CREATE TABLE IF NOT EXISTS suggestions (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
  fields_json TEXT NOT NULL,
  sources_json TEXT NOT NULL,
  confidence REAL,
  status TEXT NOT NULL DEFAULT 'pending',
  created_at TEXT NOT NULL,
  updated_at TEXT
);
CREATE TABLE IF NOT EXISTS dismissed_clusters (
  cluster_key TEXT PRIMARY KEY,
  dismissed_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


class LibraryDB:
    def __init__(self, db_path):
        self.db_path = db_path
        # check_same_thread=False: FastAPI runs sync endpoints on a worker
        # pool while scan jobs run on their own daemon thread; all access is
        # serialized through short-lived requests/requests-of-jobs.
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute('PRAGMA foreign_keys = ON')
        self.conn.executescript(SCHEMA)
        self.conn.execute('PRAGMA journal_mode=WAL')
        self.conn.commit()
        self._lock = threading.Lock()

    def close(self):
        self.conn.close()

    def _execute(self, sql, params=()):
        with self._lock:
            cur = self.conn.execute(sql, params)
            self.conn.commit()
            return cur

    @staticmethod
    def _dict(row):
        return dict(row) if row is not None else None

    # -- meta -----------------------------------------------------------------
    def get_meta(self, key, default=None):
        row = self.conn.execute(
            'SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return row['value'] if row else default

    def set_meta(self, key, value):
        self._execute(
            'INSERT INTO meta(key,value) VALUES(?,?) '
            'ON CONFLICT(key) DO UPDATE SET value=excluded.value', (key, value))

    def reset_library(self):
        self._execute('DELETE FROM suggestions')
        self._execute('DELETE FROM files')

    # -- files ------------------------------------------------------------------
    def get_file(self, path):
        return self._dict(self.conn.execute(
            'SELECT * FROM files WHERE path=?', (path,)).fetchone())

    def get_file_by_id(self, file_id):
        return self._dict(self.conn.execute(
            'SELECT * FROM files WHERE id=?', (file_id,)).fetchone())

    def upsert_file(self, rec):
        cols = ['path', 'filename', 'size', 'mtime', 'checksum', 'duration',
                'bitrate', 'artist', 'albumartist', 'album', 'title', 'tracknumber']
        values = [rec.get(c) for c in cols]
        updates = ', '.join(f'{c}=excluded.{c}' for c in cols if c != 'path')
        self._execute(
            f'INSERT INTO files({",".join(cols)}) VALUES({",".join("?" * len(cols))}) '
            f'ON CONFLICT(path) DO UPDATE SET {updates}',
            values)

    def mark_error(self, path, message):
        if self.get_file(path):
            self._execute('UPDATE files SET error=?, size=NULL, mtime=NULL WHERE path=?',
                          (message, path))
        else:
            self._execute('INSERT INTO files(path, error) VALUES(?, ?)', (path, message))

    def prune_missing(self, folder):
        removed = 0
        for row in self.conn.execute('SELECT id, path FROM files').fetchall():
            if row['path'].startswith(folder) and not os.path.exists(row['path']):
                self.remove_file(row['path'])
                removed += 1
        return removed

    def list_files(self, offset=0, limit=100, q=None):
        where, params = '', []
        if q:
            where = ('WHERE (artist LIKE ? OR album LIKE ? '
                     'OR title LIKE ? OR path LIKE ?)')
            pat = f'%{q}%'
            params = [pat, pat, pat, pat]
        total = self.conn.execute(
            f'SELECT COUNT(*) c FROM files {where}', params).fetchone()['c']
        rows = self.conn.execute(
            f'SELECT * FROM files {where} ORDER BY path LIMIT ? OFFSET ?',
            [*params, limit, offset]).fetchall()
        return [dict(r) for r in rows], total

    def all_files(self):
        return [dict(r) for r in
                self.conn.execute('SELECT * FROM files ORDER BY path')]

    def update_file_tags(self, file_id, tags):
        sets, vals = [], []
        for k in ('artist', 'albumartist', 'album', 'title', 'tracknumber'):
            if k in tags:
                sets.append(f'{k}=?')
                vals.append(tags[k])
        if sets:
            self._execute(f'UPDATE files SET {", ".join(sets)} WHERE id=?',
                          [*vals, file_id])

    def update_file_path(self, file_id, new_path):
        self._execute('UPDATE files SET path=? WHERE id=?', (new_path, file_id))

    def remove_file(self, path):
        row = self.get_file(path)
        if not row:
            return
        self._execute('DELETE FROM suggestions WHERE file_id=?', (row['id'],))
        self._execute('DELETE FROM files WHERE id=?', (row['id'],))

    # -- suggestions ------------------------------------------------------------
    def replace_suggestion(self, file_id, fields, sources, confidence):
        self._execute("DELETE FROM suggestions WHERE file_id=? AND status='pending'",
                      (file_id,))
        self._execute(
            'INSERT INTO suggestions(file_id, fields_json, sources_json, confidence, '
            "status, created_at) VALUES(?,?,?,?, 'pending', ?)",
            (file_id, json.dumps(fields), json.dumps(sources), confidence, _now()))

    def has_non_pending_suggestion(self, file_id):
        return self.conn.execute(
            "SELECT 1 FROM suggestions WHERE file_id=? "
            "AND status IN ('approved','applied')",
            (file_id,)).fetchone() is not None

    def list_suggestions(self, status=None):
        if status:
            rows = self.conn.execute(
                'SELECT * FROM suggestions WHERE status=? ORDER BY id',
                (status,)).fetchall()
        else:
            rows = self.conn.execute(
                'SELECT * FROM suggestions ORDER BY id').fetchall()
        return [dict(r) for r in rows]

    def get_suggestion(self, sid):
        return self._dict(self.conn.execute(
            'SELECT * FROM suggestions WHERE id=?', (sid,)).fetchone())

    def update_suggestion_fields(self, sid, fields):
        self._execute('UPDATE suggestions SET fields_json=?, updated_at=? WHERE id=?',
                      (json.dumps(fields), _now(), sid))

    def set_suggestion_status(self, sid, status):
        self._execute('UPDATE suggestions SET status=?, updated_at=? WHERE id=?',
                      (status, _now(), sid))

    # -- dismissed clusters -----------------------------------------------------
    def dismiss_cluster(self, cluster_key):
        self._execute(
            'INSERT OR IGNORE INTO dismissed_clusters(cluster_key, dismissed_at) '
            'VALUES(?,?)', (cluster_key, _now()))

    def dismissed_keys(self):
        return {r['cluster_key'] for r in
                self.conn.execute('SELECT cluster_key FROM dismissed_clusters')}
