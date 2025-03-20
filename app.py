import threading
import logging
from fastapi import FastAPI
from bot import bot

app = FastAPI(title="Essay2Anki Bot API")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("Essay2Anki Bot API")

# Global thread variable
bot_thread = None

@app.get("/")
async def root():
    return {"status": "running", "service": "Essay2Anki Bot"}

@app.get("/health")
async def health_check():
    global bot_thread
    if bot_thread is None:
        return {"status": "starting"}
    if not bot_thread.is_alive():
        return {"status": "unhealthy"}
    return {"status": "healthy"}

@app.on_event("startup")
async def startup_event():
    global bot_thread
    logger.info("Starting Essay2Anki Bot...")
    bot_thread = threading.Thread(target=bot.polling, daemon=True)
    bot_thread.start()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080) 