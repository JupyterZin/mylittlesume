"""Memória: fatos ditos ou confirmados pelo Lucas + contatos com fonte verificável."""

from __future__ import annotations

from urllib.parse import urlparse

from sqlmodel import col, or_, select

from talos.clock import utcnow
from talos.db.engine import Database
from talos.db.models import Contact, MemoryFact


class MemoryService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def note(self, key: str, value: str, *, scope: str = "geral", source: str = "dito") -> MemoryFact:
        if source not in ("dito", "confirmado"):
            raise ValueError("só fatos ditos ou confirmados pelo Lucas")
        with self.db.session() as s:
            f = s.exec(select(MemoryFact).where(MemoryFact.scope == scope, MemoryFact.key == key)).first()
            if f is None:
                f = MemoryFact(scope=scope, key=key, value=value, source=source)
            else:
                f.value, f.source, f.updated_at = value, source, utcnow()
            s.add(f)
            s.commit()
            s.refresh(f)
            return f

    def search(self, query: str = "", limit: int = 20) -> list[MemoryFact]:
        with self.db.session() as s:
            q = select(MemoryFact).order_by(col(MemoryFact.updated_at).desc()).limit(limit)
            if query:
                like = f"%{query}%"
                q = q.where(or_(col(MemoryFact.key).ilike(like), col(MemoryFact.value).ilike(like),
                                col(MemoryFact.scope).ilike(like)))
            return list(s.exec(q))

    def delete(self, fact_id: int) -> bool:
        with self.db.session() as s:
            f = s.get(MemoryFact, fact_id)
            if not f:
                return False
            s.delete(f)
            s.commit()
            return True


class ContactService:
    def __init__(self, db: Database) -> None:
        self.db = db

    def save(self, *, name: str, source_url: str, org: str = "", email: str = "", phone: str = "",
             website: str = "", notes: str = "") -> Contact:
        if not source_url or urlparse(source_url).scheme not in ("http", "https"):
            raise ValueError("source_url obrigatória (página oficial onde o contato aparece)")
        with self.db.session() as s:
            existing = s.exec(select(Contact).where(Contact.email == email.lower())).first() if email else None
            c = existing or Contact(name=name, source_url=source_url)
            c.name, c.org, c.email, c.phone = name, org, email.lower(), phone
            c.website, c.source_url, c.notes, c.verified_at = website, source_url, notes, utcnow()
            s.add(c)
            s.commit()
            s.refresh(c)
            return c

    def lookup(self, query: str, limit: int = 10) -> list[Contact]:
        like = f"%{query}%"
        with self.db.session() as s:
            return list(s.exec(select(Contact).where(or_(
                col(Contact.name).ilike(like), col(Contact.org).ilike(like), col(Contact.email).ilike(like),
                col(Contact.website).ilike(like))).limit(limit)))

    def by_email(self, email: str) -> Contact | None:
        with self.db.session() as s:
            return s.exec(select(Contact).where(Contact.email == email.lower())).first()
