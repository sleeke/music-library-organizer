# Code Review Report

**Date:** 2026-08-24
**Reviewer:** Code Reviewer Agent
**Scope:** branch — `feat/web-app-core-services` vs `dcea2dd` (main)
**Files reviewed:** 22 source files + 17 test files

---

## Summary

| Severity | Count |
|---|---|
| 🔴 Critical smells | 4 |
| 🟡 Warnings | 7 |
| 🔵 Suggestions | 6 |
| 🟣 Needs clarification | 1 |
| 🏷️ AI-pitfall tags | 5 |

The feature branch delivers a well-structured, spec-complete implementation with clean module boundaries and solid test coverage. The core/safety/library_db layering is coherent and the review-first guarantee is properly enforced end to end. The code is **not yet production-ready**: one test fails in CI, the global jobs dict is an unbounded memory leak, the single SQLite connection is unsafe for concurrent background-scan + request traffic, and a bare `except:` in the most-called library function swallows fatal signals. These four issues must be fixed before a release. All other findings are tractable.

---

## Strengths

- **Clean layering.** `core/` modules have one job each; `safety.py` correctly funnels all mutations through a single choke-point. The CLI's `--rollback` compatibility is preserved.
- **Review-first guarantee upheld.** Nothing is ever applied without explicit user approval. The `pending → approved → applied` state machine is fully exercised in tests.
- **Test suite quality.** Tests use real temporary files and real SQLite databases, not mocks of the system under test. Edge cases (conflict detection, tag-write failure, trash failure, cross-root reset) all have dedicated tests.
- **Security baseline for a local tool.** Server binds `127.0.0.1` only; `/api/trash` and `/api/audio` both validate paths against the library index before acting; deletes go to Trash, never permanent.
- **XSS-safe UI.** All user data is escaped through the `esc()` helper before insertion into innerHTML.

---

## Issues

### Critical (Must Fix)

---

#### C1 — One test fails in CI: `test_flag_present_in_argparser`
- **File:** [tests/test_batch.py](tests/test_batch.py#L71)
- **Description:** The test spawns `['python3', ...]` (system interpreter) which does not have `mutagen` installed outside the venv. The subprocess exits with `ModuleNotFoundError`, stdout is empty, and `assert '--batch' in result.stdout` fails. This blocks the CI green signal.
- **Suggested fix:**
  ```python
  import sys
  result = subprocess.run(
      [sys.executable, str(PROJECT_ROOT / 'update-mp3-metadata.py'), '--help'],
      capture_output=True, text=True)
  ```
  `sys.executable` resolves to the active venv interpreter, carrying all installed packages.
- **AI-pitfall tag:** P10 (missing edge case — subprocess inherits the wrong Python)

---

#### C2 — Bare `except:` swallows `KeyboardInterrupt` and `SystemExit`
- **File:** [core/lookups.py](core/lookups.py#L108) `[AI-PITFALL P4]`
- **Description:** A bare `except: pass` block wraps the MusicBrainz recording fetch inside `query_acoustid`. In Python, bare `except` catches `BaseException`, which includes `KeyboardInterrupt` and `SystemExit`. If the user presses Ctrl-C or if `sys.exit()` is called during a 10k-file scan job that hits this code path, the signal is absorbed silently and the process cannot be stopped cleanly.
- **Suggested fix:** Replace with `except Exception: pass`.

---

#### C3 — Single SQLite connection is not thread-safe under concurrent load
- **File:** [core/library_db.py](core/library_db.py#L44)
- **Description:** The code comment claims "all access is serialized through short-lived requests/requests-of-jobs", but FastAPI's sync endpoint handler runs on a `ThreadPoolExecutor` (multiple concurrent threads) while background scan/suggest jobs run on their own `daemon` threads. Both paths call `self.conn.execute()` on the same `sqlite3.Connection` object. `check_same_thread=False` only disables the guard — it does not make the connection thread-safe. SQLite's default journal mode will raise `OperationalError: database is locked` when a background scan write collides with an `/api/apply` or `/api/trash` request.
- **Suggested fix:** Enable WAL mode in `__init__` after `executescript(SCHEMA)`:
  ```python
  self.conn.execute('PRAGMA journal_mode=WAL')
  ```
  WAL allows concurrent reads and one writer without blocking. As a belt-and-suspenders measure, add a `threading.Lock` around `_execute` + `conn.commit()` pairs for strict serialization, since the server is single-user anyway.

---

#### C4 — `JOBS` dict is an unbounded memory leak
- **File:** [app.py](app.py#L9)
- **Description:** `JOBS` is a module-level dict. Jobs are added on every `/api/scan` POST but never removed. In a long-running instance (or when a CI harness repeatedly triggers scans) this grows without bound. There is no TTL, no cleanup on completion, and no cap.
- **Suggested fix:** Replace with a bounded FIFO or add a `threading.Timer` inside `run_job` to delete the entry after 5 minutes:
  ```python
  def run_job(job_id, folder, do_suggest):
      ...
      job['status'] = 'done'
      threading.Timer(300, lambda: JOBS.pop(job_id, None)).start()
  ```

---

### Important (Should Fix)

---

#### I1 — `print()` calls in a shared library module
- **File:** [core/lookups.py](core/lookups.py#L135-L195)
- **Description:** Seven `print()` calls emit diagnostics to stdout/stderr. In the web app context these go to uvicorn's stderr with no request correlation, structured format, or severity level. Users reviewing the UI have no way to see them. In the CLI context they were appropriate, but now that `lookups.py` is shared by both frontends it must be I/O-agnostic.
- **Suggested fix:**
  ```python
  import logging
  logger = logging.getLogger(__name__)
  # Replace print(f"Warning: ...") with logger.warning("...")
  # Replace print(f"Error: ...") with logger.error("...")
  # Replace print(f"  ℹ ...") with logger.info("...")
  ```

---

#### I2 — `os.rename()` fails across filesystems (cross-device link)
- **File:** [core/organize.py](core/organize.py#L46) `[AI-PITFALL P10]`
- **Description:** `os.rename(src, dst)` raises `OSError: [Errno 18] Invalid cross-device link` when `src` and `dst` are on different filesystems — which is the common case for a music library on a USB drive or network share. `safety.apply_batch` does not catch this `OSError`, so the error propagates as an unhandled exception. The file's tags will already have been written; the file will not have been moved; and the suggestion status will remain `approved` without a clear error message in the API response.
- **Suggested fix:**
  ```python
  import errno, shutil
  def move_file(src, dst):
      os.makedirs(os.path.dirname(dst), exist_ok=True)
      try:
          os.rename(src, dst)
      except OSError as e:
          if e.errno \!= errno.EXDEV:
              raise
          shutil.move(src, dst)
      return dst
  ```

---

#### I3 — `ChangeLogger.log_delete` missing `timestamp` field
- **File:** [core/changelog.py](core/changelog.py#L36)
- **Description:** Every `log_change` entry contains `'timestamp': datetime.now().isoformat()`. The `log_delete` entry does not. The spec says delete entries extend the existing format; a missing timestamp key causes inconsistent change-log rows that break any log consumer iterating entries and expecting a uniform shape (including the CLI `--rollback` code, which sorts by timestamp in some paths).
- **Suggested fix:** Add `'timestamp': datetime.now().isoformat()` to the dict returned by `log_delete`.

---

#### I4 — `/api/audio` path is user-controlled with a TOCTOU window
- **File:** [app.py](app.py#L113) `[SECURITY OWASP A01:2021 Broken Access Control]`
- **Description:** The `path` query parameter is an absolute filesystem path supplied directly by the client. The check `db.get_file(path)` and the `FileResponse(path)` are separate operations. Between them a file could be unlinked and a symlink planted pointing elsewhere. More practically, a path like `/music/../../../etc/shadow` that happens to be indexed in the DB would be served. Using `os.path.realpath()` before the DB lookup neutralises both.
- **Suggested fix:**
  ```python
  path = os.path.realpath(path)
  row = application.state.db.get_file(path)
  if row is None or not os.path.exists(path):
      raise HTTPException(status_code=400, detail='path not in library index')
  return FileResponse(path, media_type='audio/mpeg')
  ```

---

#### I5 — `run_suggest_pass` re-evaluates all files on every call
- **File:** [core/suggester.py](core/suggester.py#L53)
- **Description:** `run_suggest_pass` iterates every non-error file. `replace_suggestion` only deletes `pending` suggestions; it leaves `approved` and `applied` rows untouched. So on a re-scan, a file with an approved suggestion gets a *new* pending suggestion added alongside the approved one. For a 10k-file library this also means AcoustID fingerprinting (slow, network, rate-limited) is called on every file every time.
- **Suggested fix:** Add a method to `LibraryDB`:
  ```python
  def has_non_pending_suggestion(self, file_id):
      return self.conn.execute(
          "SELECT 1 FROM suggestions WHERE file_id=? AND status IN ('approved','applied')",
          (file_id,)).fetchone() is not None
  ```
  Then in `run_suggest_pass`: `if db.has_non_pending_suggestion(f['id']): continue`.

---

#### I6 — Duplicate cluster UI omits bitrate/filesize/duration columns
- **File:** [static/app.js](static/app.js#L103)
- **Description:** The spec states: "Duplicates page lists clusters with per-copy bitrate/filesize/duration/path and an audio preview." The cluster member rows only render artist/title, path, and audio preview. The `bitrate`, `size`, and `duration` fields are available in `all_files()` data returned from the API but are not displayed. This makes it harder to choose a keeper (you can't tell which copy is the higher-bitrate original).
- **Suggested fix:** Add `<td>${m.bitrate ? (m.bitrate/1000).toFixed(0)+'k' : '?'}</td><td>${m.size ? (m.size/1024/1024).toFixed(1)+' MB' : '?'}</td>` to the cluster member row template.

---

#### 🟣 I7 — Intent of `_set_status` closure is unclear
- **File:** [app.py](app.py#L158)
- **Observation:** `_set_status(sid, status)` is a nested function inside `create_app`. It accesses `application.state.db` via closure capture, but `application` is the outer variable from `create_app`'s scope — this is an implicit dependency not visible at the call sites `approve(sid)` and `reject(sid)`.
- **Open question:** Is this closure capture intentional (to avoid passing `db` explicitly), or was it expected to be a module-level helper that would receive `db` as a parameter?
- **If intentional:** Add a comment: `# Captures application from create_app scope — not a free function.`
- **If unintentional:** Promote to a module-level helper and pass `db` explicitly.

---

### Minor (Nice to Have)

---

#### M1 — `LibraryDB` unnecessarily re-exported from `suggester.py`
- **File:** [core/suggester.py](core/suggester.py#L6) `[AI-PITFALL P7]`
- `from .library_db import LibraryDB  # noqa: F401` — no test imports `LibraryDB` from `suggester`. This creates a latent circular-import hazard if `library_db` ever imports from `suggester`. Remove the line; callers should import `LibraryDB` from `core.library_db`.

---

#### M2 — Manual cascade in `remove_file` duplicates schema constraint
- **File:** [core/library_db.py](core/library_db.py#L144)
- The schema declares `REFERENCES files(id) ON DELETE CASCADE` and `PRAGMA foreign_keys = ON` is set. The manual `DELETE FROM suggestions WHERE file_id=?` before `DELETE FROM files WHERE id=?` in `remove_file` is redundant. Remove the manual delete or document why both are needed.

---

#### M3 — AcoustID demo API key hard-coded as fallback
- **File:** [core/lookups.py](core/lookups.py#L20) `[SECURITY OWASP A02:2021]`
- `os.environ.get('ACOUSTID_KEY', 'cSpUJKpD')` — the fallback is the public demo key from the pyacoustid README; it is shared, rate-limited, and could be revoked. Add a startup log warning if the env var is unset. Document in `README.md` that users must provide their own key for production use.

---

#### M4 — `pollJob` in `app.js` has no abort path
- **File:** [static/app.js](static/app.js#L85)
- The `while(true)` polling loop runs until `job.status \!== 'running'`. If the user closes the browser tab or navigates away mid-scan there is no mechanism to cancel the loop; the pending `setTimeout` continues in the background tab. For a local single-page app this is harmless but worth documenting.

---

#### M5 — `test_scan_job_completes` relies on wall-clock timing
- **File:** [tests/test_api.py](tests/test_api.py#L67)
- Polls up to 5 seconds (`100 × 0.05 s`). On a heavily loaded CI runner this can be too short and causes a flaky failure. Consider `time.sleep(0.5)` before the first poll and a longer retry cap.

---

#### M6 — No security response headers
- **File:** [app.py](app.py) `[SECURITY OWASP A05:2021 Security Misconfiguration]`
- FastAPI returns no `X-Content-Type-Options`, `Content-Security-Policy`, or `Referrer-Policy` headers. For a localhost-only tool the risk is low, but adding them costs nothing:
  ```python
  from fastapi.middleware.base import BaseHTTPMiddleware
  from starlette.requests import Request
  class SecurityHeaders(BaseHTTPMiddleware):
      async def dispatch(self, request: Request, call_next):
          resp = await call_next(request)
          resp.headers['X-Content-Type-Options'] = 'nosniff'
          resp.headers['Content-Security-Policy'] = "default-src 'self'"
          return resp
  application.add_middleware(SecurityHeaders)
  ```

---

## Assessment

**Production readiness: Not yet — fix C1–C4 first.**

The architecture is sound, the spec is fully implemented (modulo the duplicate UI columns in I6), and the test suite is genuinely useful rather than mock-heavy. Four issues block a safe release:

- **C1** makes the test suite report a failure on any standard CI setup right now.
- **C2** means the process cannot be stopped cleanly during a long scan.
- **C3** will cause intermittent `database is locked` crashes the moment a user tries to apply suggestions while a background scan is running — which is the most natural workflow.
- **C4** is a slow-burn memory leak that becomes visible after hours of use.

After those four are addressed, the I-series warnings (especially I2 for external-volume libraries and I3 for changelog consistency) should be resolved before broad use. The codebase is otherwise well-structured and ready for the cleanup phase.
