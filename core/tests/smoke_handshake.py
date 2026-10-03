# Rodar à mão: .venv/bin/python tests/smoke_handshake.py  (arranca o CLI, sem chamar o modelo)
"""Smoke test SEM chamada ao modelo: arranca o CLI com as opções reais do Talos e faz só o
handshake (initialize) + estado dos servidores MCP."""
import asyncio, json, sys, tempfile
from pathlib import Path
from cryptography.fernet import Fernet
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from talos.config import Settings
from talos.db.engine import Database
from talos.services import build_services
from talos.connectors.fakes import FakeGmail
from talos.sentinel.policy import Sentinel
from talos.runtime.claude import ClaudeRuntime
from talos.runtime.base import RunRequest

async def main():
    tmp = Path(tempfile.mkdtemp())
    ws = tmp / "ws"; import shutil; shutil.copytree(Path(__file__).resolve().parents[2] / "workspace", ws)
    s = Settings(data_dir=tmp, workspace_dir=ws, vault_key_file=tmp / "k", gmail_address="x@gmail.com")
    db = Database(s.db_url); db.migrate()
    app = build_services(s, db, Fernet.generate_key(), gmail=FakeGmail())
    sen = Sentinel(workspace_dir=ws, vault_values=app.vault.personal_values)
    rt = ClaudeRuntime(app, sen)
    from claude_agent_sdk import ClaudeSDKClient
    for profile in ("main", "task"):
        opts, *_ , tail = rt.build_options(RunRequest(prompt="x", profile=profile))
        if profile == "task":
            opts.mcp_servers.pop("playwright")  # sem browser neste contêiner
        async with ClaudeSDKClient(options=opts) as c:
            info = await c.get_server_info()
            st = None
            for _ in range(10):
                st = await c.get_mcp_status()
                if st.get("mcpServers"):
                    break
                await asyncio.sleep(1)
        print(profile, "server_info keys:", sorted((info or {}).keys())[:12])
        print(profile, "mcp:", json.dumps(st, default=str)[:1500])
        print(profile, "hooks_applied:", info.get("hooks_applied"), "perm:", info.get("current_permission_mode"))
        if tail: print("stderr:", tail[-5:])

asyncio.run(main())
