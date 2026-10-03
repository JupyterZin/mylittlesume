"""Organização semanal da caixa do Gmail (segunda-feira, W12).

Determinístico + Sistema 1: o código lista a caixa, o Jev classifica cada email (categoria,
precisa de resposta, importância), o código monta um plano (rótulos Talos/* e arquivo das
categorias de baixo valor) e o Lucas aprova num cartão. Nunca apaga nada; tudo é reversível.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from typing import TYPE_CHECKING, Any

from sqlmodel import col, select

from talos.db.models import Job, PendingAction
from talos.logging import get_logger
from talos.system1.judgments import EMAIL_CATEGORIES

if TYPE_CHECKING:
    from talos.services import Services

log = get_logger("talos.organizer")

QUERY = "in:inbox -is:starred older_than:2d"
MAX_MESSAGES = 300
ARCHIVE = {"promocoes", "newsletters", "notificacoes"}
KEEP_IN_INBOX = {"pessoal", "trabalho", "financas", "contas_e_seguranca"}
LABEL = {
    "pessoal": "Talos/Pessoal", "trabalho": "Talos/Trabalho", "financas": "Talos/Finanças",
    "compras": "Talos/Compras", "viagens": "Talos/Viagens", "contas_e_seguranca": "Talos/Contas",
    "notificacoes": "Talos/Notificações", "newsletters": "Talos/Newsletters", "promocoes": "Talos/Promoções",
}
NAMES = {"pessoal": "pessoais", "trabalho": "trabalho", "financas": "finanças", "compras": "compras",
         "viagens": "viagens", "contas_e_seguranca": "contas e segurança", "notificacoes": "notificações",
         "newsletters": "newsletters", "promocoes": "promoções"}
GMAIL_CATEGORY = {"CATEGORY_PROMOTIONS": "promocoes", "CATEGORY_SOCIAL": "notificacoes",
                  "CATEGORY_UPDATES": "notificacoes", "CATEGORY_FORUMS": "newsletters"}


def deterministic_category(msg: dict[str, Any]) -> str | None:
    for lab in msg.get("labelIds", []):
        if lab in GMAIL_CATEGORY:
            return GMAIL_CATEGORY[lab]
    if msg.get("list_unsubscribe"):
        return "newsletters"
    return None


class InboxOrganizer:
    def __init__(self, app: Services) -> None:
        self.app = app

    async def plan(self) -> dict[str, Any]:
        gm = self.app.gmail
        msgs = await asyncio.to_thread(gm.list_messages, QUERY, MAX_MESSAGES)
        sem = asyncio.Semaphore(5)

        async def judge(m: dict[str, Any]) -> tuple[dict[str, Any], str, float, float]:
            det = deterministic_category(m)
            cat, needs, imp = det or "pessoal", 0.0, 1.0
            if self.app.system1.enabled:
                async with sem:
                    j = await self.app.system1.classify_email(m)
                if j is not None:
                    if det is None or j.category_confidence >= 0.6:
                        cat = j.category
                    needs, imp = j.needs_reply, j.importance
            elif det is None:
                cat, imp = "pessoal", 1.5  # sem Sistema 1 e sem sinais do Gmail: não mexe
            return m, cat, needs, imp

        judged = await asyncio.gather(*(judge(m) for m in msgs))
        labels: dict[str, list[str]] = {}
        archive: list[str] = []
        needs_reply: list[dict[str, str]] = []
        examples: dict[str, list[str]] = {}
        for m, cat, needs, imp in judged:
            labels.setdefault(LABEL[cat], []).append(m["id"])
            examples.setdefault(cat, [])
            if len(examples[cat]) < 3:
                examples[cat].append(_who(m))
            if cat in ARCHIVE and needs < 0.3 and imp < 1.5:
                archive.append(m["id"])
            if needs >= 0.6 and cat not in ARCHIVE:
                needs_reply.append({"id": m["id"], "de": _who(m), "assunto": m.get("subject", "")[:80],
                                    "importancia": round(imp, 2)})
        needs_reply.sort(key=lambda x: -x["importancia"])
        counts = Counter(cat for _m, cat, _n, _i in judged)
        return {"scanned": len(msgs), "labels": labels, "archive": archive, "needs_reply": needs_reply[:10],
                "counts": dict(counts), "examples": examples,
                "system1": self.app.system1.enabled}

    @staticmethod
    def summary(plan: dict[str, Any]) -> str:
        lines = [f"Revi {plan['scanned']} emails da caixa de entrada (mais de 2 dias, sem estrela)."]
        for cat, n in sorted(plan["counts"].items(), key=lambda kv: -kv[1]):
            ex = ", ".join(plan["examples"].get(cat, [])[:2])
            lines.append(f"• {NAMES.get(cat, cat)}: {n}" + (f" (ex.: {ex})" if ex else ""))
        lines.append(f"Arquivar (sair da caixa, continuam pesquisáveis): {len(plan['archive'])}")
        if plan["needs_reply"]:
            lines.append("Parecem esperar resposta sua:")
            lines += [f"  – {x['de']}: «{x['assunto']}»" for x in plan["needs_reply"][:5]]
        if not plan.get("system1"):
            lines.append("(Sem Sistema 1: só usei as categorias do próprio Gmail.)")
        return "\n".join(lines)

    async def propose(self) -> PendingAction | None:
        if self.app.gmail is None:
            return None
        plan = await self.plan()
        if not plan["scanned"]:
            await self.app.notifier.notify("📭 Organização semanal: a caixa de entrada já está arrumada.")
            return None
        with self.app.db.session() as s:  # uma proposta de organização de cada vez
            for old in s.exec(select(PendingAction).where(PendingAction.kind == "email.organize",
                                                          PendingAction.status == "pending")):
                old.status = "superseded"
                s.add(old)
            s.commit()
        summary = self.summary(plan)
        action = self.app.approvals.create(task_id=None, kind="email.organize",
                                           payload={**plan, "summary": summary}, preview=summary,
                                           reason="organização semanal da caixa (segunda-feira); nada é apagado")
        await self.app.notifier.send_card(action, task_title="Organização semanal do Gmail")
        return action

    async def handle_job(self, job: Job) -> None:
        await self.propose()


async def execute_organize(app: Services, action: PendingAction) -> dict[str, Any]:
    gm = app.gmail
    p = action.payload_json
    labeled = 0
    for label, ids in p.get("labels", {}).items():
        if not label.startswith("Talos/") or not ids:
            continue
        lid = await asyncio.to_thread(gm.ensure_label, label)
        await asyncio.to_thread(gm.batch_modify, ids, [lid], None)
        labeled += len(ids)
    archived = list(p.get("archive", []))
    if archived:
        await asyncio.to_thread(gm.batch_modify, archived, None, ["INBOX"])
    return {"labeled": labeled, "archived": len(archived), "archived_ids": archived}


async def undo_last(app: Services) -> str:
    with app.db.session() as s:
        a = s.exec(select(PendingAction).where(PendingAction.kind == "email.organize",
                                               PendingAction.status == "executed")
                   .order_by(col(PendingAction.id).desc())).first()
    if a is None:
        return "Não há organização para desfazer."
    ids = (a.result_json or {}).get("archived_ids", [])
    if (a.result_json or {}).get("undone"):
        return "A última organização já foi desfeita."
    if ids:
        await asyncio.to_thread(app.gmail.batch_modify, ids, ["INBOX"], None)
    with app.db.session() as s:
        row = s.get(PendingAction, a.id)
        row.result_json = {**row.result_json, "undone": True}
        s.add(row)
        s.commit()
    return f"↩️ Voltaram {len(ids)} emails para a caixa de entrada (os rótulos Talos/* ficam)."


def _who(m: dict[str, Any]) -> str:
    frm = m.get("from", "")
    name = frm.split("<")[0].strip().strip('"')
    return name or frm


_ = EMAIL_CATEGORIES  # as categorias vivem no Sistema 1
