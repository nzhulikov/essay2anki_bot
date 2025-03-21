import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Header, Response
from bot import bot
from telebot.types import Update
from typing import Annotated

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Essay2Anki Bot API")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Essay2Anki Bot...")
    # setup bot webhook
    bot.set_webhook(url=os.getenv("ESSAY2ANKI_BOT_WEBHOOK_URL"),
                     secret_token=os.getenv("ESSAY2ANKI_BOT_SECRET_TOKEN"))
    yield
    logger.info("Shutting down Essay2Anki Bot...")

app = FastAPI(title="Essay2Anki Bot API", lifespan=lifespan)

@app.get("/")
async def root():
    return {"status": "running", "service": "Essay2Anki Bot"}

@app.post("/webhook")
def webhook(message: dict, x_telegram_bot_api_secret_token: Annotated[str, Header()]):
    logger.info(f"Received message: {message}")
    if x_telegram_bot_api_secret_token != os.getenv("ESSAY2ANKI_BOT_SECRET_TOKEN"):
        return Response(status_code=403)
    bot.process_new_updates([Update.de_json(message)])

@app.get("/health")
async def health_check():
    bot.get_me()
    return {"status": "healthy"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=80) 