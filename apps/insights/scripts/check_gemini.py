"""Solo dev: prueba modelos Gemini sin reintentos ni esperas largas.

Uso (desde la raiz del repo):
  uv run --package proptech-insights python apps/insights/scripts/check_gemini.py
  uv run --package proptech-insights python apps/insights/scripts/check_gemini.py gemini-3.5-flash gemini-2.5-flash

Sin argumentos prueba el GEMINI_MODEL de apps/insights/.env. No imprime la API key.
"""
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI

load_dotenv(Path(__file__).parent.parent / ".env")
key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
models = sys.argv[1:] or [os.getenv("GEMINI_MODEL", "")]

for m in models:
    t0 = time.perf_counter()
    try:
        llm = ChatGoogleGenerativeAI(model=m, google_api_key=key, max_retries=0, timeout=30)
        out = llm.invoke("Responde solo: ok")
        text = out.content if isinstance(out.content, str) else str(out.content)[:60]
        print(f"[OK]   {m:32s} {time.perf_counter() - t0:6.1f}s  -> {text.strip()[:40]!r}")
    except Exception as e:
        msg = str(e).splitlines()[0][:110] if str(e) else ""
        print(f"[FAIL] {m:32s} {time.perf_counter() - t0:6.1f}s  {type(e).__name__}: {msg}")
