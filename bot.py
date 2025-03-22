import os
import openai
import telebot
import json
import tempfile
import logging
from hashlib import sha256
from telebot.types import ReplyParameters

from anki.collection import Collection, AddNoteRequest

logger = logging.getLogger(__name__)

# Configuration
TELEGRAM_TOKEN = os.getenv("ESSAY2ANKI_BOT_KEY")
OPENAI_API_KEY = os.getenv("ESSAY2ANKI_OPENAI_KEY")
DEFAULT_LANGUAGE = "греческий"
DEFAULT_ANKI = False

# Initialize APIs
logger.info("Initializing Telegram bot and OpenAI client...")
bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = openai.OpenAI(api_key=OPENAI_API_KEY)

def translate_text(text, settings):
    """Uses ChatGPT to translate and structure text into standard Greek while keeping original phrases."""
    prompt = (
        f"Переведи на стандартный современный {settings['language']} язык "
        "с соблюдением всех грамматических норм, сохраняя "
        "исходный стиль написания и уровень используемой лексики. "
        "Ответ сделай максимально компактным, не добавляя лишнего текста. "
        "Разбей переведённый текст на короткие отрывки 1-2 неразрывно "
        "связанных повествованием предложения для лёгкости заучивания текста наизусть. "
        "Строго напиши ответ в формате .csv с разделителем ; для импорта в Anki:\n"
        "отрывок из оригинала;переведённый отрывок\n"
        "Например:\n"
        "\"Это текст для перевода. Он состоит из двух отрывков.\". Ответ:\n"
        "Это текст для перевода;Αυτό είναι το κείμενο για μετάφραση\n"
        "Он состоит из двух отрывков;Αποτελείται από δύο περάσματα.\n"
        f"Вот текст для перевода:\n{text}"
    ) if settings["anki"] else (
        f"Переведи на стандартный современный {settings['language']} язык "
        "с соблюдением всех грамматических норм, сохраняя "
        "исходный стиль написания и уровень используемой лексики. "
        "Ответ сделай максимально компактным, не добавляя лишнего текста. "
        f"Вот текст для перевода:\n{text}"
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9
    )
    return response.choices[0].message.content

def synthesize_speech(text, filename):
    """Converts text to speech using OpenAI TTS and saves as MP3."""
    response = client.audio.speech.create(
        model="tts-1",
        voice="onyx",
        input=text
    )

    with open(filename, 'wb') as f:
        for chunk in response.iter_bytes():
            f.write(chunk)

    return filename

def save_settings(chat_dir, settings, **kwargs):
    for key, value in kwargs.items():
        settings[key] = value
    with open(f"{chat_dir}/settings.json", "w") as f:
        json.dump(settings, f)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    try:
        logger.info(f"Received message from chat {message.chat.id}: {message.text[:50]}...")
        _handle_message(message)
    except Exception as e:
        logger.exception("Error processing message")
        raise e

def _handle_message(message):
    # create directory for this chat if not exists
    chat_dir = str(message.chat.id)
    
    if message.text == "/start":
        logger.debug("Processing /start command")
        bot.send_message(message.chat.id, "Привет! Отправь мне текст, и я переведу его, а затем создам для тебя колоду для Anki.\n"
                                         "Команда /help покажет доступные команды.")
        
        if os.path.exists(chat_dir):
            for file in os.listdir(chat_dir):
                os.remove(f"{chat_dir}/{file}")
        else:
            os.makedirs(chat_dir)
        return
    
    if message.text == "/help":
        bot.send_message(message.chat.id, "Отправь мне текст, и я переведу его, а затем создам для тебя колоду для Anki.\n"
                                         "Используй короткий текст, ограничение 1000 символов.\n"
                                         "Доступные команды:\n"
                                         "/start - начать работу с ботом/сбросить настройки\n"
                                         "/lang - текущий язык перевода\n"
                                         "/gr - изменить язык на греческий\n"
                                         "/sb - изменить язык на сербский\n"
                                         "/en - изменить язык на английский\n"
                                         "/anki - изменить режим на подготовку колоды для Anki\n"
                                         "/chat - изменить режим на отправку переводов в чат\n"
                                         "/help - показать это сообщение\n"
                                         )
        return

    if not os.path.exists(chat_dir):
        bot.send_message(message.chat.id, "Сначала отправь /start")
        return
    settings = {"language": DEFAULT_LANGUAGE, "anki": DEFAULT_ANKI}
    if not os.path.exists(f"{chat_dir}/settings.json"):
        with open(f"{chat_dir}/settings.json", "w") as f:
            json.dump(settings, f)
    else:
        with open(f"{chat_dir}/settings.json", "r") as f:
            settings = {**settings, **json.load(f)}

    if message.text == "/lang":
        bot.send_message(message.chat.id, f"Я перевожу текст на {settings['language']} язык.")
        return
    if message.text == "/gr":
        save_settings(chat_dir, settings, language="греческий")
        bot.send_message(message.chat.id, "Теперь я перевожу текст на греческий язык.")
        return
    if message.text == "/sb":
        save_settings(chat_dir, settings, language="сербский")
        bot.send_message(message.chat.id, "Теперь я перевожу текст на сербский язык.")
        return
    if message.text == "/en":
        save_settings(chat_dir, settings, language="английский")
        bot.send_message(message.chat.id, "Теперь я перевожу текст на английский язык.")
        return
    if message.text == "/anki":
        save_settings(chat_dir, settings, anki=True)
        bot.send_message(message.chat.id, "Теперь я буду готовить колоду для Anki.")
        return
    if message.text == "/chat":
        save_settings(chat_dir, settings, anki=False)
        bot.send_message(message.chat.id, "Теперь я буду скидывать переводы в чат.")
        return
    if len(message.text) > 1000:
        bot.send_message(message.chat.id, "Текст слишком длинный, попробуй меньше 1000 символов.")
        return

    status_message = bot.send_message(message.chat.id, "Перевожу текст...")
    with tempfile.TemporaryDirectory() as tmpdir:
        bot.send_chat_action(message.chat.id, "typing")
        translated_text = translate_text(message.text, settings)
        if len(translated_text) > 1000:
            bot.edit_message_text("Получился слишком длинный текст, попробуйте снова.", message.chat.id, status_message.id)
            return

        if not settings["anki"]:
            translation_message_id = status_message.id
            bot.edit_message_text(translated_text, message.chat.id, translation_message_id)
            status_message = bot.send_message(message.chat.id, "Озвучиваю текст...")
            bot.send_chat_action(message.chat.id, "record_voice")
            audio_filename = f"{tmpdir}/audio_{sha256(translated_text.encode()).hexdigest()}.mp3"
            synthesize_speech(translated_text, audio_filename)
            with open(audio_filename, "rb") as audio:
                bot.send_voice(message.chat.id, audio, reply_parameters=
                            ReplyParameters(translation_message_id, allow_sending_without_reply=True))
                bot.delete_message(message.chat.id, status_message.id)
            return
        
        lines = translated_text.strip().split("\n")
        lines = [line for line in lines if ';' in line]

        if not lines:
            bot.edit_message_text("Не получилось перевести текст, попробуйте снова.", message.chat.id, status_message.id)
            return

        deck_name = lines[0].split(";")[0].strip()
        anki_package_filename = f"{tmpdir}/{deck_name}.apkg"
        bot.edit_message_text("Озвучиваю текст...", message.chat.id, status_message.id)
        bot.send_chat_action(message.chat.id, "record_voice")
        collection = Collection(f"{tmpdir}/collection.anki2")
        try:
            deck_id = collection.decks.add_normal_deck_with_name(deck_name).id
            collection.decks.set_current(deck_id)
            add_note_requests = []
            for i in range(0, len(lines)):
                original = lines[i].split(";")[0].strip()
                translated = lines[i].split(";")[1].strip()
                mp3_filename = f"phrase_{len(add_note_requests)+1}_{sha256(translated.encode()).hexdigest()}.mp3"
                mp3_filename_path = f"{tmpdir}/{mp3_filename}"

                synthesize_speech(translated, mp3_filename_path)
                mp3_filename = collection.media.add_file(mp3_filename_path)
                note = collection.new_note(collection.models.by_name("Basic"))
                note.fields = [original, f"{translated}[sound:{mp3_filename}]"]
                note.tags = ["эссе"]
                add_note_requests.append(AddNoteRequest(note=note, deck_id=deck_id))

            bot.edit_message_text("Собираю колоду...", message.chat.id, status_message.id)
            bot.send_chat_action(message.chat.id, "typing")
            
            collection.add_notes(add_note_requests)
            collection.export_anki_package(
                out_path=anki_package_filename,
                with_media=True,
                with_scheduling=False,
                legacy_support=True,
                limit=None
            )
        finally:
            collection.close()

        bot.edit_message_text("Отправляю колоду...", message.chat.id, status_message.id)
        bot.send_chat_action(message.chat.id, "upload_document")
        with open(anki_package_filename, "rb") as zipf:
            bot.send_document(message.chat.id, zipf)
        bot.delete_message(message.chat.id, status_message.id)
