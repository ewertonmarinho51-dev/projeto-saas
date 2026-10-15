"""ASGI lab entry point. Assets are public; documents remain in authenticated sessions."""
import json
import os
from pathlib import Path
from urllib.parse import urlsplit
import streamlit as st
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles
from starlette.responses import Response

ROOT = Path(__file__).resolve().parent
config = json.loads(os.environ["GOVDOCS_WORDCRAFT_LAB"])
assert urlsplit(config["origin"]).hostname == "127.0.0.1"
assert urlsplit(os.environ["SUPABASE_URL"]).hostname == "127.0.0.1"
lab = Path(config["lab"])
assert (lab / ".wordcraft-local-qa").read_text(encoding="utf-8") == "LOCAL_WORDCRAFT_QA_ONLY\n"


class PublicAssets(StaticFiles):
    """Never expose a checkpoint/state accidentally placed beside an asset."""
    def __init__(self, directory, public_files):
        super().__init__(directory=directory)
        self.public_files = frozenset(public_files)

    async def get_response(self, path, scope):
        if path.replace("\\", "/") not in self.public_files:
            return Response(status_code=404)
        return await super().get_response(path, scope)


app = st.App(ROOT / "app.py", secrets={
    "SUPABASE_URL": os.environ["SUPABASE_URL"], "SUPABASE_KEY": os.environ["SUPABASE_KEY"],
    "SUPABASE_SECRET_KEY": "", "SUPABASE_SERVICE_KEY": os.environ["SUPABASE_SERVICE_KEY"],
}, routes=[Mount("/app/static/wordcraft", app=PublicAssets(lab / "static/wordcraft", config["public_files"]))])
