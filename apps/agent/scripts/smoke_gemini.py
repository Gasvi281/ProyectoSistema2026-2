import os
import sys
from pathlib import Path

# Carga .env desde la raíz de apps/agent/
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    from dotenv import load_dotenv
    load_dotenv(env_path)

from langchain_google_genai import ChatGoogleGenerativeAI

api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
if not api_key:
    print("ERROR: Define GEMINI_API_KEY o GOOGLE_API_KEY en apps/agent/.env")
    sys.exit(1)

llm = ChatGoogleGenerativeAI(
    model=os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
    google_api_key=api_key,
    temperature=0,
)
print(llm.invoke("Responde solo con: OK").content)
