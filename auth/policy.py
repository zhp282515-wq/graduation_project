"""Knowledge ACLs are server-derived and never accepted from model arguments."""
from contextvars import ContextVar

from fastapi import HTTPException

principal = ContextVar('fanfan_principal', default=None)


def allowed_documents(conn, user):
    if user.get('role') == 'admin':
        rows = conn.execute("SELECT file_md5 FROM kb_documents WHERE status='ready'").fetchall()
    else:
        rows = conn.execute("SELECT file_md5 FROM kb_documents WHERE visibility='public' AND status='ready'").fetchall()
    return frozenset(row['file_md5'] for row in rows)


def readable(doc, user):
    return bool(doc and (user['role']=='admin' or (doc.get('visibility')=='public' and doc.get('status')=='ready')))


def require_document(doc, user):
    if not readable(doc,user):
        raise HTTPException(404,'文档不存在或无访问权限')


class ScopedRegistry:
    """Expose only authorized registry rows while retaining the existing paging API."""
    def __init__(self, repo, user):
        self.repo, self.user = repo, user

    def __getattr__(self, name):
        return getattr(self.repo,name)

    def list_page(self, **kwargs):
        return self.repo.list_page(**kwargs) if self.user['role']=='admin' else self.repo.list_page(**kwargs, public_only=True)

    def facets(self, q=''):
        return self.repo.facets(q) if self.user['role']=='admin' else self.repo.facets(q,public_only=True)

    def overview(self):
        return self.repo.overview() if self.user['role']=='admin' else self.repo.overview(public_only=True)


class ScopedKnowledge:
    """StarMapBuilder facade: build/cache public and administrator graphs separately."""
    def __init__(self, service, allowed):
        self.service, self.allowed = service, allowed
        self.store = self
        self.collection = service.store.collection

    def list_documents(self):
        return [doc for doc in self.service.list_documents() if doc['file_md5'] in self.allowed]

    def iter_all_chunks(self, **kwargs):
        return (row for row in self.service.store.iter_all_chunks(**kwargs) if row.get('file_md5') in self.allowed)
