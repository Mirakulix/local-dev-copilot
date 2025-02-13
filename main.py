from fastapi import FastAPI
from debug_assistant.core import DebuggingAssistant, DebugMiddleware

app = FastAPI()
debug_assistant = DebuggingAssistant(project_root=".")
app.add_middleware(DebugMiddleware, debug_assistant=debug_assistant)

@app.get("/")
async def read_root():
    # Beispiel-Endpunkt mit potenziellem Fehler
    return {"message": 42 / 0}