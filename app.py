"""Local web app: FastAPI backend + static UI for the MP3 library."""
import json
import os
import threading
import uuid

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from core import safety, scanner, suggester
from core.changelog import ChangeLogger
from core.duplicates import find_duplicate_clusters
from core.library_db import LibraryDB


class SecurityHeaders(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        resp = await call_next(request)
        resp.headers['X-Content-Type-Options'] = 'nosniff'
        resp.headers['Content-Security-Policy'] = "default-src 'self'"
        return resp

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT_DB_PATH = os.path.join(PROJECT_DIR, 'library.db')
STATIC_DIR = os.path.join(PROJECT_DIR, 'static')

TAG_FIELDS = ('artist', 'albumartist', 'album', 'title', 'tracknumber')

JOBS = {}


class ScanRequest(BaseModel):
    folder: str
    suggest: bool = True


class DismissRequest(BaseModel):
    cluster_key: str


class PathsRequest(BaseModel):
    paths: list[str]


class FieldsRequest(BaseModel):
    fields: dict


class IdsRequest(BaseModel):
    ids: list[int]


def create_app(db_path: str) -> FastAPI:
    application = FastAPI(title='MP3 Library Manager')
    application.add_middleware(SecurityHeaders)
    application.state.db = LibraryDB(db_path)
    application.state.project_dir = PROJECT_DIR

    def run_job(job_id, folder, do_suggest):
        job = JOBS[job_id]
        try:
            scan_stats = scanner.scan_folder(
                application.state.db, folder,
                progress_cb=lambda d, t, phase: job.update(
                    phase=phase, done=d, total=t))
            result = {'scan': scan_stats}
            if do_suggest:
                result['suggest'] = suggester.run_suggest_pass(
                    application.state.db,
                    progress_cb=lambda d, t, phase: job.update(
                        phase=phase, done=d, total=t))
            job['status'] = 'done'
            job['result'] = result
        except Exception as exc:  # surfaced through GET /api/jobs/{id}
            job['status'] = 'error'
            job['result'] = str(exc)
        finally:
            # Jobs are only needed while the UI polls them; drop them after
            # a grace period so repeated scans don't grow JOBS unboundedly.
            threading.Timer(300, lambda: JOBS.pop(job_id, None)).start()

    @application.post('/api/scan')
    def start_scan(req: ScanRequest):
        folder = os.path.abspath(os.path.expanduser(req.folder))
        if not os.path.isdir(folder):
            raise HTTPException(status_code=400, detail=f'not a directory: {folder}')
        job_id = uuid.uuid4().hex
        JOBS[job_id] = {'status': 'running', 'phase': 'scan', 'done': 0,
                        'total': 0, 'result': None}
        threading.Thread(target=run_job, args=(job_id, folder, req.suggest),
                         daemon=True).start()
        return {'job_id': job_id}

    @application.get('/api/jobs/{job_id}')
    def job_status(job_id: str):
        job = JOBS.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail='unknown job')
        return job

    @application.get('/api/library')
    def library(offset: int = 0, limit: int = Query(default=100, le=500),
                q: str = None):
        files, total = application.state.db.list_files(offset=offset,
                                                       limit=limit, q=q)
        pending_ids = {s['file_id'] for s in
                       application.state.db.list_suggestions(status='pending')}
        for f in files:
            f['has_pending'] = f['id'] in pending_ids
        return {'files': files, 'total': total}

    @application.get('/api/duplicates')
    def duplicates():
        clusters = find_duplicate_clusters(application.state.db.all_files())
        dismissed = application.state.db.dismissed_keys()
        return {'clusters': [c for c in clusters if c['key'] not in dismissed]}

    @application.post('/api/duplicates/dismiss')
    def dismiss(req: DismissRequest):
        application.state.db.dismiss_cluster(req.cluster_key)
        return {'ok': True}

    @application.post('/api/trash')
    def trash(req: PathsRequest):
        known = {f['path'] for f in application.state.db.all_files()}
        unknown = [p for p in req.paths if p not in known]
        if unknown:
            raise HTTPException(status_code=400,
                                detail=f'paths not in library index: {unknown}')
        logger = ChangeLogger(default_log(application.state.project_dir))
        results = safety.trash_files(application.state.db, req.paths, logger)
        return {'results': results}

    @application.get('/api/audio')
    def audio(path: str):
        # Resolve symlinks/.. before the DB check so a swapped or crafted
        # path cannot escape the indexed library.
        path = os.path.realpath(path)
        row = application.state.db.get_file(path)
        if row is None or not os.path.exists(path):
            raise HTTPException(status_code=400, detail='path not in library index')
        return FileResponse(path, media_type='audio/mpeg')

    @application.get('/api/suggestions')
    def suggestions(status: str = 'pending'):
        cards = []
        for s in application.state.db.list_suggestions(status=status):
            f = application.state.db.get_file_by_id(s['file_id'])
            if f is None:
                continue
            cards.append({
                'id': s['id'],
                'status': s['status'],
                'confidence': s['confidence'],
                'fields': json.loads(s['fields_json']),
                'sources': json.loads(s['sources_json']),
                'current': {k: f.get(k) for k in TAG_FIELDS},
                'path': f['path'],
                'filename': f.get('filename'),
            })
        return {'suggestions': cards}

    @application.patch('/api/suggestions/{sid}')
    def edit_suggestion(sid: int, req: FieldsRequest):
        sug = application.state.db.get_suggestion(sid)
        if sug is None:
            raise HTTPException(status_code=404, detail='unknown suggestion')
        merged = {**json.loads(sug['fields_json']), **req.fields}
        application.state.db.update_suggestion_fields(sid, merged)
        return {'ok': True}

    def _set_status(sid, status):
        sug = application.state.db.get_suggestion(sid)
        if sug is None:
            raise HTTPException(status_code=404, detail='unknown suggestion')
        application.state.db.set_suggestion_status(sid, status)
        return {'ok': True}

    @application.post('/api/suggestions/approve-batch')
    def approve_batch(req: IdsRequest):
        count = 0
        for sid in req.ids:
            if application.state.db.get_suggestion(sid):
                application.state.db.set_suggestion_status(sid, 'approved')
                count += 1
        return {'approved': count}

    @application.post('/api/suggestions/{sid}/approve')
    def approve(sid: int):
        return _set_status(sid, 'approved')

    @application.post('/api/suggestions/{sid}/reject')
    def reject(sid: int):
        return _set_status(sid, 'rejected')

    @application.post('/api/apply')
    def apply():
        logger = ChangeLogger(default_log(application.state.project_dir))
        return safety.apply_batch(application.state.db, logger)

    if os.path.isdir(STATIC_DIR):
        application.mount('/', StaticFiles(directory=STATIC_DIR, html=True),
                          name='static')

    return application


def default_log(project_dir):
    return safety.default_log_path(project_dir)


app = create_app(DEFAULT_DB_PATH)

if __name__ == '__main__':
    import uvicorn
    uvicorn.run(app, host='127.0.0.1', port=8000)
