import logging
import psycopg
import os

DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
DB_NAME = os.getenv("DB_NAME")

logger = logging.getLogger(__name__)

async def get_db():
    return await psycopg.AsyncConnection.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME,
        async_=True
    )


async def db_health_check(db: psycopg.AsyncConnection):
    try:
        await db.execute("SELECT 1")
        return True
    except Exception as e:
        logger.error(f"Database connection failed: {e}")
        return False
