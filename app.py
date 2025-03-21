import os
import logging
import requests
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, Response
from bot import bot
from telebot.types import Update
from telebot.util import antiflood
from typing import Annotated

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Essay2Anki Bot API")

def get_webhook_url():
    custom_webhook_url = os.getenv("ESSAY2ANKI_BOT_WEBHOOK_URL")
    if custom_webhook_url:
        return custom_webhook_url
    try:
        response = requests.get("http://localhost:4040/api/tunnels")
        tunnels = response.json()["tunnels"]
        for tunnel in tunnels:
            if tunnel["proto"] == "https":
                return tunnel["public_url"]
    except Exception as e:
        logger.error(f"Failed to get ngrok URL: {e}")
    return None

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Essay2Anki Bot...")
    webhook_url = get_webhook_url()
    if webhook_url:
        logger.info(f"Setting webhook URL: {webhook_url}")
        bot.set_webhook(url=webhook_url + "/webhook",
                       secret_token=os.getenv("ESSAY2ANKI_SECRET_TOKEN"))
    else:
        logger.error("Failed to get webhook URL")
    yield
    logger.info("Shutting down Essay2Anki Bot...")

app = FastAPI(title="Essay2Anki Bot API", lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "running", "service": "Essay2Anki Bot"}

@app.post("/webhook")
def webhook(message: dict, x_telegram_bot_api_secret_token: Annotated[str, Header()]):
    logger.info(f"Received message: {message}")
    if x_telegram_bot_api_secret_token != os.getenv("ESSAY2ANKI_SECRET_TOKEN"):
        return Response(status_code=403)
    bot.process_new_updates([Update.de_json(message)])

@app.get("/health")
async def health_check():
    antiflood(bot.get_me)
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=80) 