"""Cartões de aprovação (SPEC Anexo A)."""

from __future__ import annotations

from talos.channels.base import Buttons
from talos.db.models import PendingAction
from talos.vault.placeholders import PlaceholderError, find_keys, label, resolve

TELEGRAM_LIMIT = 4096

VERB = {
    "email.send": ("enviar email", "Aprovar e enviar"),
    "email.reply": ("responder email", "Aprovar e enviar"),
    "calendar.invite": ("enviar convite", "Aprovar e convidar"),
    "browser.submit": ("submeter formulário", "Aprovar e submeter"),
    "purchase": ("concluir compra", "Aprovar e comprar"),
    "booking": ("fazer reserva", "Aprovar e reservar"),
    "share_data": ("partilhar dados pessoais", "Aprovar e partilhar"),
    "delete": ("apagar", "Aprovar e apagar"),
    "email.organize": ("organizar a caixa de entrada (rótulos e arquivo; nada é apagado)", "Aprovar e organizar"),
}
RISK = {"baixo": "baixo", "medio": "médio", "alto": "alto"}
RECIPIENT_NOTE = {
    "fornecido": "indicado por você",
    "contato_oficial": "fonte: {source}, verificada",
    "participante": "já participa da conversa",
    "novo": "⚠️ destinatário novo",
}


def buttons_for(action: PendingAction) -> Buttons:
    approve = VERB.get(action.kind, ("", "Aprovar"))[1]
    return [
        [(approve, f"ap:{action.id}:a")],
        [("Editar", f"ap:{action.id}:e"), ("Recusar", f"ap:{action.id}:r"), ("Depois", f"ap:{action.id}:l")],
    ]


def render(action: PendingAction, values: dict[str, str], task_title: str = "",
           app_url: str = "", limit: int = TELEGRAM_LIMIT) -> str:
    p = action.payload_json or {}
    what = VERB.get(action.kind, (action.kind, ""))[0]
    head = f"Aprovação necessária · Proposta #{action.id}"
    if action.task_id:
        head += f" · Tarefa #{action.task_id}" + (f" \"{task_title}\"" if task_title else "")
    lines = [head, f"Ação: {what}"]

    recips = p.get("_recipients") or []
    if recips:
        parts = []
        for r in recips:
            note = RECIPIENT_NOTE.get(r.get("status", "novo"), "").format(source=r.get("source_url", "?"))
            parts.append(f"{r['address']} ({note})")
        lines.append("Para: " + "; ".join(parts))
    elif p.get("to"):
        lines.append("Para: " + ", ".join(p["to"]))
    if p.get("subject"):
        lines.append(f"Assunto: {_fill(p['subject'], values)}")
    if p.get("when"):
        lines.append(f"Quando: {p['when']}")
    if p.get("summary"):
        lines.append(_fill(str(p["summary"]), values))

    tail = []
    keys = sorted(set(find_keys(p.get("subject", "")) + find_keys(p.get("body", "")) + p.get("_data_keys", [])))
    if keys:
        tail.append("Dados pessoais incluídos: " + ", ".join(label(k) for k in keys))
    if p.get("_raw_personal"):
        tail.append("⚠️ Dados pessoais escritos por extenso (sem placeholder): " + ", ".join(p["_raw_personal"]))
    risk = RISK.get(action.risk, action.risk)
    tail.append(f"Risco: {risk}" + (f" ({p['_risk_why']})" if p.get("_risk_why") else ""))
    if action.reason:
        tail.append(f"Por que: {action.reason}")

    body = _fill(p.get("body", ""), values) if p.get("body") else (action.preview_text or "")
    text = "\n".join(lines) + ("\n\n" + body if body else "") + "\n\n" + "\n".join(tail)
    if len(text) > limit:
        more = f"\n… (cortado) ver completo: {app_url}/aprovacoes/{action.id}" if app_url else "\n… (cortado; ver no app)"
        room = limit - len(more) - len("\n".join(lines)) - len("\n".join(tail)) - 6
        text = "\n".join(lines) + "\n\n" + body[:max(0, room)] + more + "\n\n" + "\n".join(tail)
    return text


def _fill(text: str, values: dict[str, str]) -> str:
    """No cartão o Lucas vê os valores reais (SPEC §7.4)."""
    try:
        return resolve(text, values)
    except PlaceholderError as e:
        return text + f"\n⚠️ {e}"


def parse_callback(data: str) -> tuple[int, str] | None:
    parts = (data or "").split(":")
    if len(parts) != 3 or parts[0] != "ap" or not parts[1].isdigit() or parts[2] not in "aerl":
        return None
    return int(parts[1]), {"a": "approve", "e": "edit", "r": "reject", "l": "later"}[parts[2]]
