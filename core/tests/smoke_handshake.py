"""Smoke test SEM chamada ao modelo: arranca o CLI com as opções reais do Talos e faz só o
handshake (initialize) + estado dos servidores MCP.

Rodar à mão: .venv/bin/python tests/smoke_handshake.py
"""

import asyncio
import json
import shutil
import sys
import tempfile
from pathlib import Path

from cryptography.fernet import Fernet

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from claude_agent_sdk import ClaudeSDKClient  # noqa: E402

from talos.config import Settings  # noqa: E402
from talos.connectors.fakes import FakeGmail  # noqa: E402
from talos.db.engine import Database  # noqa: E402
from talos.runtime.base import RunRequest  # noqa: E402
from talos.runtime.claude import ClaudeRuntime  # noqa: E402
from talos.sentinel.policy import Sentinel  # noqa: E402
from talos.services import build_services  # noqa: E402


async def main() -> None:
    tmp = Path(tempfile.mkdtemp())
    ws = tmp / "ws"
    shutil.copytree(Path(__file__).resolve().parents[2] / "workspace", ws)
    s = Settings(data_dir=tmp, workspace_dir=ws, vault_key_file=tmp / "k", gmail_address="x@gmail.com")
    db = Database(s.db_url)
    db.migrate()
    app = build_services(s, db, Fernet.generate_key(), gmail=FakeGmail())
    rt = ClaudeRuntime(app, Sentinel(workspace_dir=ws, vault_values=app.vault.personal_values))
    for profile in ("main", "task"):
        opts, _gate, _ctx, tail = rt.build_options(RunRequest(prompt="x", profile=profile))
        opts.mcp_servers.pop("playwright", None)  # sem navegador fora do servidor
        async with ClaudeSDKClient(options=opts) as c:
            info = await c.get_server_info() or {}
            st: dict = {}
            for _ in range(10):
                st = await c.get_mcp_status()
                if st.get("mcpServers"):
                    break
                await asyncio.sleep(1)
        servers = [(m["name"], m["status"], len(m.get("tools", []))) for m in st.get("mcpServers", [])]
        print(profile, "mcp:", json.dumps(servers), "hooks:", info.get("hooks_applied"),
              "perm:", info.get("current_permission_mode"))
        if tail:
            print("stderr:", tail[-5:])


if __name__ == "__main__":
    asyncio.run(main())
