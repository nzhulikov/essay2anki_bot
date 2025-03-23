import os
import logging
import requests
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, Response, Request
from bot import init_bot, handle_webhook, health_check as bot_health_check
from typing import Annotated

# Configure logging to console
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(pathname)s:%(lineno)d - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

def get_webhook_url():
    custom_webhook_url = os.getenv("ESSAY2ANKI_BOT_WEBHOOK_URL")
    if custom_webhook_url:
        return custom_webhook_url
    try: # ngrok
        response = requests.get("http://localhost:4040/api/tunnels")
        tunnels = response.json()["tunnels"]
        for tunnel in tunnels:
            if tunnel["proto"] == "https":
                return tunnel["public_url"]
    except Exception as e:
        logger.error(f"Failed to get ngrok URL: {e}")
    raise Exception("Failed to get webhook URL")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Essay2Anki Bot...")
    init_bot(get_webhook_url())
    yield
    logger.info("Shutting down Essay2Anki Bot...")

app = FastAPI(title="Essay2Anki Bot API", lifespan=lifespan)

@app.middleware("http")
async def log_errors(request: Request, call_next):
    try:
        return await call_next(request)
    except Exception as e:
        logger.error(f"Error processing request: {e}")
        return Response(status_code=500)

@app.get("/")
async def root():
    return {"status": "running", "service": "Essay2Anki Bot"}

@app.post("/webhook")
def webhook(message: dict, x_telegram_bot_api_secret_token: Annotated[str, Header()]):
    logger.debug(f"Received message: {message}")
    if x_telegram_bot_api_secret_token != os.getenv("ESSAY2ANKI_SECRET_TOKEN"):
        return Response(status_code=403)
    handle_webhook(message)

@app.get("/health")
async def health_check():
    if not bot_health_check():
        return Response(content={"status": "unhealthy"}, status_code=500)
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=80) 