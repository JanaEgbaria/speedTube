from fastapi import FastAPI

app = FastAPI(title="SpeedTube API")


@app.get("/health")
def health():
    return {"status": "ok"}
