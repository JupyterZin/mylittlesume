"""Sentinela: política entre o agente e o mundo (SPEC §7.3).

Ordem: allowlist → regras determinísticas → egress → classificador (só endurece) → concessões
pontuais (aprovações já dadas pelo Lucas para exatamente esta ação). Toda decisão vira um
`task_event` `sentinel_decision` (gravado por quem chama, via `on_decision`).
"""

from __future__ import annotations

import hashlib
import inspect
import json
import os
import re
from collections.abc import Awaitable, Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Protocol
from urllib.parse import urlparse

import yaml

from talos.sentinel import egress

Action = Literal["allow", "ask", "takeover", "deny"]
SEVERITY: dict[str, int] = {"allow": 0, "ask": 1, "takeover": 2, "deny": 3}
RULES_PATH = Path(__file__).with_name("rules.yaml")

FILE_TOOLS = {"Read", "Write", "Edit", "Glob", "Grep"}
NO_EGRESS_TOOLS = FILE_TOOLS | {"Skill", "Task", "Agent", "TodoWrite"}
URL_KEYS = ("url", "href", "link")
REF_RE = re.compile(r"^(f\d+)?e\d+$")
CLASSIFIED_PREFIXES = ("mcp__playwright__browser_",)
CLASSIFIED_TOOLS = {"WebFetch"}
READ_ONLY_BROWSER = {
    "mcp__playwright__browser_snapshot", "mcp__playwright__browser_take_screenshot",
    "mcp__playwright__browser_console_messages", "mcp__playwright__browser_network_requests",
    "mcp__playwright__browser_wait_for", "mcp__playwright__browser_find", "mcp__playwright__browser_tabs",
    "mcp__playwright__browser_resize", "mcp__playwright__browser_navigate_back",
}


@dataclass
class ToolCall:
    name: str
    input: dict[str, Any]
    task_id: int | None = None
    profile: str = "task"
    user_request: str = ""
    page_summary: str = ""
    tool_use_id: str | None = None

    def fingerprint(self) -> str:
        """Identidade estável da ação (sem refs voláteis do snapshot)."""
        stable = {k: v for k, v in self.input.items() if k not in {"target", "ref"}}
        raw = json.dumps({"tool": self.name, "input": stable}, sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(raw.encode()).hexdigest()[:32]


@dataclass
class Decision:
    action: Action
    reason: str = ""
    rule_id: str | None = None
    source: str = "rule"  # allowlist | rule | egress | classifier | grant | default
    egress_hits: list[egress.EgressHit] = field(default_factory=list)

    def harden(self, other: Decision) -> Decision:
        return other if SEVERITY[other.action] > SEVERITY[self.action] else self

    def as_event(self, call: ToolCall) -> dict[str, Any]:
        return {
            "tool": call.name,
            "decision": self.action,
            "reason": self.reason,
            "rule": self.rule_id,
            "source": self.source,
            "egress": [h.describe() for h in self.egress_hits],
            "fingerprint": call.fingerprint(),
        }


class Classifier(Protocol):
    async def __call__(self, call: ToolCall) -> tuple[str, str]:  # ("ok"|"ask"|"block", motivo)
        ...


class SnapshotIndex:
    """Mapa ref → texto do elemento, extraído dos snapshots ARIA do Playwright MCP.

    Permite à Sentinela avaliar o elemento REAL que vai ser clicado, e não só a descrição que o
    agente escreveu em `element` (que pode ser enganosa).

    Formato real do @playwright/mcp 0.0.83 (capturado; ver tests/test_browser.py):

        - generic [ref=f2e3] [cursor=pointer]: Finalizar compra     ← o texto vem DEPOIS de ":"
        - 'textbox "Pesquisar: produtos" [ref=f2e11]'               ← YAML entre aspas quando há ": "
        - link "Pagar agora" [ref=f2e5] [cursor=pointer]:           ← filhos indentados
          - /url: "#ver"
        - generic [ref=e7] [cursor=pointer]:                        ← sem nome: o texto está nos filhos
          - generic [ref=e8]: Aceitar
        - iframe [ref=f2e12]:                                       ← refs de outros frames: f3e1…

    Por isso o texto de cada ref = papel + nome + texto inline, e um elemento SEM nome nem texto
    herda o texto dos descendentes (um `div` clicável com "Aceitar" num `span`).

    As ações (navigate, click, type…) NÃO trazem o snapshot inline: o MCP escreve-o num `.yml`
    e devolve `- [Snapshot](caminho.yml)` (relativo ao cwd do MCP = workspace). O índice lê esse
    ficheiro, mas só se ele estiver dentro de `allowed_dirs` (o `--output-dir` do MCP).
    `page_url` guarda o último "- Page URL:" que o MCP reportou (a aba em que ele está a trabalhar).
    """

    ITEM_RE = re.compile(r"^(?P<indent>\s*)- (?P<body>.*?)\s*$")
    KEY_RE = re.compile(r'^(?P<role>/?[\w-]+)(?:\s+(?P<name>"(?:[^"\\]|\\.)*"))?(?P<attrs>(?:\s*\[[^\]]*\])*)'
                        r'\s*(?::\s*(?P<value>.*))?$')
    REF_ATTR_RE = re.compile(r"\[ref=(?P<ref>(?:f\d+)?e\d+)\]")
    LINK_RE = re.compile(r"\[Snapshot\]\((?P<path>[^)\s]+?\.ya?ml)\)")
    PAGE_URL_RE = re.compile(r"^- Page URL: (?P<url>\S+)\s*$", re.M)
    MAX_TEXT = 300
    MAX_FILE = 5_000_000

    def __init__(self, base_dir: Path | None = None, allowed_dirs: Iterable[Path] = ()) -> None:
        self._refs: dict[str, str] = {}
        self.page_url: str | None = None
        self.base_dir = Path(base_dir) if base_dir else None
        self.allowed_dirs = [os.path.realpath(d) for d in allowed_dirs]

    def ingest(self, text: str) -> None:
        text = text or ""
        if '\\"' in text:  # resposta serializada em JSON pelo hook PostToolUse
            text = text.replace('\\"', '"')
        for m in self.PAGE_URL_RE.finditer(text):
            self.page_url = m.group("url")
        self._parse(text)
        for m in self.LINK_RE.finditer(text):
            if (content := self._read_linked(m.group("path"))) is not None:
                self._parse(content)

    def lookup(self, ref: str) -> str | None:
        return self._refs.get(ref)

    # ---------- interno ----------
    def _parse(self, text: str) -> None:
        stack: list[tuple[int, str, bool]] = []  # (indentação, ref, herda texto dos filhos)
        for raw in text.splitlines():
            m = self.ITEM_RE.match(raw)
            if not m:
                continue
            indent = len(m.group("indent").expandtabs())
            while stack and stack[-1][0] >= indent:
                stack.pop()
            body = _yaml_unquote_key(m.group("body"))
            km = self.KEY_RE.match(body)
            role, name = (km.group("role"), km.group("name")) if km else ("", None)
            value = _yaml_unquote_value(km.group("value") or "") if km else ""
            if role.startswith("/"):  # propriedades (/url, /placeholder): sem rótulo, o placeholder já é o
                continue                # nome; e "/booking" ou "código postal" dariam falsos positivos
            ref_m = self.REF_ATTR_RE.search(km.group("attrs") if km else body)
            if km is None:  # formato inesperado: guarda a linha inteira (sem o ref) como texto
                own = self.REF_ATTR_RE.sub("", body).strip()
                informative = bool(own)
            else:
                own = role + (f" {name}" if name else "") + (f": {value}" if value else "")
                informative = bool(name or value)
            if not ref_m:
                if informative:  # ex.: "- text: Confirmar" dentro de um elemento sem nome
                    for _i, anc, inherits in stack:
                        if inherits:
                            self._append(anc, own)
                continue
            ref = ref_m.group("ref")
            self._refs[ref] = own[: self.MAX_TEXT]
            if informative:
                for _i, anc, inherits in stack:
                    if inherits:
                        self._append(anc, own)
            stack.append((indent, ref, km is not None and not informative))

    def _append(self, ref: str, text: str) -> None:
        cur = self._refs.get(ref, "")
        if len(cur) < self.MAX_TEXT:
            self._refs[ref] = f"{cur} · {text}"[: self.MAX_TEXT] if cur else text[: self.MAX_TEXT]

    def _read_linked(self, path: str) -> str | None:
        if not self.allowed_dirs:
            return None
        p = Path(path)
        candidates = [p] if p.is_absolute() else ([self.base_dir / p] if self.base_dir else [])
        candidates += [Path(d) / p.name for d in self.allowed_dirs]  # cwd do MCP diferente do esperado
        for c in candidates:
            real = os.path.realpath(c)
            if not any(real.startswith(d + os.sep) for d in self.allowed_dirs):
                continue
            try:
                if os.path.getsize(real) > self.MAX_FILE:
                    continue
                return Path(real).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
        return None


@dataclass
class Rule:
    id: str
    match: dict[str, Any]
    decision: Action
    reason: str = ""


class Sentinel:
    def __init__(
        self,
        *,
        workspace_dir: Path,
        vault_values: Callable[[], Mapping[str, str]] = dict,
        authorized_keys: Callable[[int | None], Iterable[str]] = lambda _t: (),
        classifier: Classifier | None = None,
        classifier_enabled: bool = True,
        rules_path: Path = RULES_PATH,
        on_decision: Callable[[ToolCall, Decision], Awaitable[None] | None] | None = None,
        snapshot_dirs: Iterable[Path] = (),
    ) -> None:
        self.workspace_dir = Path(workspace_dir)
        self.vault_values = vault_values
        self.authorized_keys = authorized_keys
        self.classifier = classifier
        self.classifier_enabled = classifier_enabled
        self.on_decision = on_decision
        # snapshot_dirs = `--output-dir` do Playwright MCP (onde ele grava os snapshots das ações)
        self.snapshots = SnapshotIndex(base_dir=self.workspace_dir, allowed_dirs=snapshot_dirs)
        self._grants: dict[str, int] = {}
        self.load_rules(rules_path)

    # ---------- configuração ----------
    def load_rules(self, path: Path) -> None:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        self.default: Action = data.get("default", "ask")
        self.lists: dict[str, list[str]] = {k: list(v or []) for k, v in (data.get("lists") or {}).items()}
        self.rules = [Rule(id=r["id"], match=r["match"], decision=r["decision"], reason=r.get("reason", ""))
                      for r in data.get("rules", [])]
        for r in self.rules:
            if r.decision not in SEVERITY:
                raise ValueError(f"regra {r.id}: decisão inválida {r.decision}")

    def grant_once(self, fingerprint: str) -> None:
        """O Lucas aprovou esta ação exata: a próxima tentativa passa (uma vez)."""
        self._grants[fingerprint] = self._grants.get(fingerprint, 0) + 1

    # ---------- avaliação ----------
    async def evaluate(self, call: ToolCall, allowed_tools: Iterable[str] | None = None) -> Decision:
        decision = self._evaluate_static(call, allowed_tools)

        if decision.action in ("allow", "ask") and call.name not in NO_EGRESS_TOOLS \
                and not call.name.startswith("mcp__talos__"):
            values = self.vault_values()
            url_hits = egress.scan([call.input.get(k) for k in URL_KEYS if call.input.get(k)], values)
            if url_hits:  # SPEC §7.5.3: nada de dados pessoais em URLs, nem com aprovação
                what = ", ".join(sorted({h.describe() for h in url_hits}))
                decision = Decision("deny", f"dados pessoais numa URL: {what}", "egress-url", "egress", url_hits)
            hits = egress.scan(call.input, values)
            bad = egress.unauthorized(hits, self.authorized_keys(call.task_id))
            if bad and decision.action in ("allow", "ask"):
                what = ", ".join(sorted({h.describe() for h in bad}))
                if decision.action == "allow":
                    decision = Decision("ask", f"dados pessoais a sair: {what}", "egress", "egress", bad)
                else:
                    decision.egress_hits = bad
                    decision.reason += f" · dados pessoais: {what}"

        if (decision.action == "allow" and self.classifier and self.classifier_enabled
                and self._classifiable(call.name)):
            try:
                verdict, why = await self.classifier(call)
            except Exception as e:  # classificador indisponível nunca afrouxa nada
                verdict, why = "ok", f"classificador indisponível: {e}"
            if verdict == "block":
                decision = decision.harden(Decision("deny", f"classificador: {why}", "classifier", "classifier"))
            elif verdict == "ask":
                decision = decision.harden(Decision("ask", f"classificador: {why}", "classifier", "classifier"))

        if decision.action == "ask":
            fp = call.fingerprint()
            if self._grants.get(fp):
                self._grants[fp] -= 1
                decision = Decision("allow", "aprovado pelo Lucas", "grant", "grant", decision.egress_hits)

        if self.on_decision:
            res = self.on_decision(call, decision)
            if inspect.isawaitable(res):
                await res
        return decision

    def _evaluate_static(self, call: ToolCall, allowed_tools: Iterable[str] | None) -> Decision:
        if allowed_tools is not None and not tool_allowed(call.name, allowed_tools):
            return Decision("deny", f"{call.name} não está na allowlist deste perfil", "allowlist", "allowlist")
        for rule in self.rules:
            if self._matches(rule.match, call):
                return Decision(rule.decision, rule.reason, rule.id, "rule")
        return Decision(self.default, "nenhuma regra casou", None, "default")

    @staticmethod
    def _classifiable(name: str) -> bool:
        if name in READ_ONLY_BROWSER:
            return False
        return name in CLASSIFIED_TOOLS or name.startswith(CLASSIFIED_PREFIXES)

    # ---------- matching ----------
    def _matches(self, m: dict[str, Any], call: ToolCall) -> bool:
        name, inp = call.name, call.input or {}
        if "tool" in m and name != m["tool"]:
            return False
        if "tool_prefix" in m and not name.startswith(m["tool_prefix"]):
            return False
        if "tool_in" in m and name not in m["tool_in"]:
            return False
        if m.get("element_missing") and self._has_descriptions(name, inp):
            return False
        if m.get("target_unknown") and not self._has_unknown_ref(inp):
            return False
        if "element_regex" in m and not _search(m["element_regex"], self._element_texts(inp)):
            return False
        if "field_regex" in m and not _search(m["field_regex"], self._element_texts(inp)):
            return False
        if "domain_in" in m:
            domains = self.lists.get(m["domain_in"], []) if isinstance(m["domain_in"], str) else m["domain_in"]
            host = (urlparse(str(inp.get("url", ""))).hostname or "").lower()
            if not host or not any(host == d or host.endswith("." + d) for d in domains):
                return False
        if "input_flag" in m and not all(inp.get(k) == v for k, v in m["input_flag"].items()):
            return False
        if "key_regex" in m and not re.search(m["key_regex"], str(inp.get("key", "")), re.I):
            return False
        if m.get("path_outside_workspace") and not self._path_outside(name, inp):
            return False
        return True

    @staticmethod
    def _has_descriptions(name: str, inp: dict[str, Any]) -> bool:
        if name.endswith("browser_fill_form"):
            fields = inp.get("fields") or []
            return bool(fields) and all(str(f.get("name") or f.get("element") or "").strip() for f in fields)
        if name.endswith(("browser_drag", "browser_drop")):
            return bool(str(inp.get("startElement") or inp.get("element") or "").strip())
        return bool(str(inp.get("element") or "").strip())

    def _has_unknown_ref(self, inp: dict[str, Any]) -> bool:
        """Ref do snapshot que a Sentinela nunca viu: não dá para saber o que é o elemento."""
        targets = [inp.get(k) for k in ("target", "ref", "startTarget", "endTarget")]
        targets += [f.get("target") or f.get("ref") for f in inp.get("fields") or []]
        return any(isinstance(t, str) and REF_RE.match(t) and self.snapshots.lookup(t) is None for t in targets)

    def _element_texts(self, inp: dict[str, Any]) -> list[str]:
        texts: list[str] = []

        def add_target(t: Any) -> None:
            if not t:
                return
            t = str(t)
            if REF_RE.match(t):
                if (real := self.snapshots.lookup(t)) is not None:
                    texts.append(real)
            else:
                texts.append(t)  # seletor CSS / locator: avaliado como texto

        for key in ("element", "startElement", "endElement"):
            if inp.get(key):
                texts.append(str(inp[key]))
        for key in ("target", "ref", "startTarget", "endTarget"):
            add_target(inp.get(key))
        for f in inp.get("fields") or []:
            for key in ("name", "element"):
                if f.get(key):
                    texts.append(str(f[key]))
            add_target(f.get("target") or f.get("ref"))
        return texts

    def _path_outside(self, name: str, inp: dict[str, Any]) -> bool:
        ws = os.path.realpath(self.workspace_dir)
        candidates = [inp.get(k) for k in ("file_path", "path", "notebook_path") if inp.get(k)]
        if name == "Glob" and inp.get("pattern"):
            candidates.append(inp["pattern"])
        for c in candidates:
            p = Path(str(c)).expanduser()
            if not p.is_absolute():
                p = Path(ws) / p
            real = os.path.realpath(p)
            if real != ws and not real.startswith(ws + os.sep):
                return True
            if ".." in Path(str(c)).parts:
                return True
        return False


def tool_allowed(name: str, allowed: Iterable[str]) -> bool:
    for a in allowed:
        if a.endswith("*") and name.startswith(a[:-1]):
            return True
        if name == a:
            return True
    return False


def _search(pattern: str, texts: list[str]) -> bool:
    rx = re.compile(pattern, re.I)
    return any(rx.search(t) for t in texts)


def _yaml_unquote_key(body: str) -> str:
    """`'textbox "a: b" [ref=e1]': resto` → `textbox "a: b" [ref=e1]: resto` (aspas simples, '' = ')."""
    if not body.startswith("'"):
        return body
    out, i = [], 1
    while i < len(body):
        if body[i] == "'":
            if body[i + 1:i + 2] == "'":
                out.append("'")
                i += 2
                continue
            return "".join(out) + body[i + 1:]
        out.append(body[i])
        i += 1
    return "".join(out)


def _yaml_unquote_value(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] == '"':
        try:
            return str(json.loads(value))
        except ValueError:
            return value[1:-1]
    if len(value) >= 2 and value[0] == value[-1] == "'":
        return value[1:-1].replace("''", "'")
    return value
