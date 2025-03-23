from functools import partial
import os
import openai
import telebot
import json
import tempfile
import logging
from hashlib import sha256
from telebot.types import (
    ReplyParameters, Message,MenuButtonCommands, BotCommand,
    InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery,
    Update, BotCommandScopeChat)
from telebot.util import antiflood

from anki.collection import Collection, AddNoteRequest, ExportAnkiPackageOptions, DeckIdLimit

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
available_languages = {
    "gr": "греческий",
    "sb": "сербский",
    "en": "английский",
    "nl": "нидерландский",
}
language_flag_emojis = {
    "gr": "🇬🇷",
    "sb": "🇷🇸",
    "en": "🇬🇧",
    "nl": "🇳🇱",
}


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


def get_settings(chat_dir):
    settings = {"language": DEFAULT_LANGUAGE, "anki": DEFAULT_ANKI}
    if not os.path.exists(f"{chat_dir}/settings.json"):
        with open(f"{chat_dir}/settings.json", "w") as f:
            json.dump(settings, f)
    else:
        with open(f"{chat_dir}/settings.json", "r") as f:
            settings = {**settings, **json.load(f)}
    return settings


def handle_webhook(message: dict):
    try:
        bot.process_new_updates([Update.de_json(message)])
    except Exception as e:
        bot.send_message(message.chat.id, f"Произошла ошибка, попробуйте снова.")
        raise e


def health_check():
    user = antiflood(bot.get_me)
    return user is not None


def init_bot(webhook_url):
    logger.info(f"Setting webhook URL: {webhook_url}")
    bot.set_webhook(url=webhook_url + "/webhook",
                       secret_token=os.getenv("ESSAY2ANKI_SECRET_TOKEN"))
    init_commands()


def init_commands(chat_id: int | None = None):
    bot.set_chat_menu_button(
        chat_id=chat_id,
        menu_button=MenuButtonCommands(type="commands")
    )
    bot.set_my_commands(
        commands=[
            BotCommand(command="start", description="Начать работу с ботом"),
            BotCommand(command="settings", description="Настройки бота"),
            BotCommand(command="help", description="Показать доступные команды"),
        ],
        scope=BotCommandScopeChat(chat_id=chat_id) if chat_id else None
    )


def show_settings(chat_id: int, edit_message_id: int | None = None):
    chat_dir = get_chat_dir(chat_id)
    settings = get_settings(chat_dir)
    sentences = []
    if settings["anki"]:
        sentences.append("*Режим:* Anki")
        mode_btn = InlineKeyboardButton(text="Вкл. Чат", callback_data="chat")
    else:
        sentences.append("*Режим:* Чат")
        mode_btn = InlineKeyboardButton(text="Вкл. Anki", callback_data="anki")
    sentences.append(f"*Язык:* {settings['language']}")
    text = '\n'.join(sentences)
    if edit_message_id:
        func = partial(bot.edit_message_text, text, chat_id=chat_id, message_id=edit_message_id)
    else:
        func = partial(bot.send_message, chat_id, text)
    func(
        reply_markup=InlineKeyboardMarkup(
            keyboard=[
                [mode_btn, InlineKeyboardButton(text="Язык", callback_data="lang")]
            ]
        ),
        parse_mode="Markdown"
    )


def get_chat_dir(chat_id: int):
    chat_dir = f"chats/{str(chat_id)}"
    if not os.path.exists(chat_dir):
        os.makedirs(chat_dir)
    return chat_dir


@bot.message_handler(commands=["start"])
def handle_start(message: Message):
    chat_dir = get_chat_dir(message.chat.id)
    for file in os.listdir(chat_dir):
        os.remove(f"{chat_dir}/{file}")
    init_commands(message.chat.id)


@bot.message_handler(commands=["settings"])
def handle_settings(message: Message):
    show_settings(message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data in ["back_to_settings"])
def handle_back_to_settings_callback(call: CallbackQuery):
    show_settings(call.message.chat.id, call.message.id)


@bot.callback_query_handler(func=lambda call: call.data in ["anki", "chat", "lang"])
def handle_settings_callback(call: CallbackQuery):
    chat_dir = get_chat_dir(call.message.chat.id)
    settings = get_settings(chat_dir)
    if call.data == "anki":
        save_settings(chat_dir, settings, anki=True)
        show_settings(call.message.chat.id, call.message.id)
    elif call.data == "chat":
        save_settings(chat_dir, settings, anki=False)
        show_settings(call.message.chat.id, call.message.id)
    elif call.data == "lang":
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.id, text=f"На какой язык переводить?",
                              reply_markup=InlineKeyboardMarkup(
                                keyboard=[
                                    [InlineKeyboardButton(text=language_flag_emojis[language], callback_data=language) for language in available_languages.keys()],
                                    [InlineKeyboardButton(text="Назад", callback_data="back_to_settings")]
                                ]
                              ))
        

@bot.callback_query_handler(func=lambda call: call.data in available_languages)
def handle_lang_callback(call: CallbackQuery):
    chat_dir = get_chat_dir(call.message.chat.id)
    settings = get_settings(chat_dir)
    language = available_languages[call.data]
    save_settings(chat_dir, settings, language=language)
    show_settings(call.message.chat.id, call.message.id)


@bot.message_handler(commands=["help"])
def handle_help(message: Message):
    commands = bot.get_my_commands()
    sentences = [
        "Отправь мне текст, и я переведу его и озвучу. Ограничение 1000 символов.",
        "Доступные команды:",
        *[f"/{command.command} - {command.description}" for command in commands]
    ]
    bot.send_message(message.chat.id, '\n'.join(sentences))


@bot.message_handler()
def handle_message(message: Message):
    if message.text.startswith("/"):
        handle_help(message)
        return
    if len(message.text) > 1000:
        bot.send_message(message.chat.id, "Текст слишком длинный, попробуй меньше 1000 символов.")
        return
    if len(message.text) < 10:
        bot.send_message(message.chat.id, "Текст слишком короткий, попробуй больше 10 символов.")
        return

    chat_dir = get_chat_dir(message.chat.id)
    settings = get_settings(chat_dir)

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            bot.send_chat_action(message.chat.id, "upload_document" if settings["anki"] else "typing")
            translated_text = translate_text(message.text, settings)
            if len(translated_text) > 1500:
                bot.send_message("Получился слишком длинный текст, попробуйте снова.", message.chat.id)
                return

            if not settings["anki"]:
                bot.send_chat_action(message.chat.id, "record_voice")
                audio_filename = os.path.join(tmpdir, f"audio_{sha256(translated_text.encode()).hexdigest()}.mp3")
                synthesize_speech(translated_text, audio_filename)
                with open(audio_filename, "rb") as audio:
                    bot.send_voice(message.chat.id, audio,
                                caption=translated_text,
                        reply_parameters=ReplyParameters(message.id, allow_sending_without_reply=True))
                return
            
            lines = translated_text.strip().split("\n")
            lines = [line for line in lines if ';' in line]

            if not lines:
                bot.send_message("Не получилось перевести текст, попробуйте снова.", message.chat.id)
                return

            deck_name = lines[0].split(";")[0].strip()
            anki_package_filename = os.path.join(tmpdir, "deck.apkg")
            collection = Collection(os.path.join(tmpdir, "collection.anki2"))
            try:
                deck_id = collection.decks.add_normal_deck_with_name(deck_name).id
                collection.decks.set_current(deck_id)
                add_note_requests = []
                for i in range(0, len(lines)):
                    bot.send_chat_action(message.chat.id, "upload_document")
                    original = lines[i].split(";")[0].strip()
                    translated = lines[i].split(";")[1].strip()
                    mp3_filename = f"phrase_{len(add_note_requests)+1}_{sha256(translated.encode()).hexdigest()}.mp3"
                    mp3_filename_path = os.path.join(tmpdir, mp3_filename)

                    synthesize_speech(translated, mp3_filename_path)
                    mp3_filename = collection.media.add_file(mp3_filename_path)
                    note = collection.new_note(collection.models.by_name("Basic"))
                    note.fields = [original, f"{translated}[sound:{mp3_filename}]"]
                    note.tags = ["эссе"]
                    add_note_requests.append(AddNoteRequest(note=note, deck_id=deck_id))
                
                collection.add_notes(add_note_requests)
                collection.export_anki_package(
                    out_path=anki_package_filename,
                    options=ExportAnkiPackageOptions(
                        with_media=True,
                        legacy=True
                    ),
                    limit=DeckIdLimit(
                        deck_id=deck_id
                    )
                )
            finally:
                collection.close()

            bot.send_chat_action(message.chat.id, "upload_document")
            with open(anki_package_filename, "rb") as zipf:
                bot.send_document(message.chat.id, zipf,
                                caption='\n'.join([f"*{line.split(';')[0]}* | {line.split(';')[1]}" for line in lines]),  
                                reply_parameters=ReplyParameters(message.id, allow_sending_without_reply=True),
                                parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error handling message: {e}", exc_info=True)
        bot.send_message("Произошла ошибка, попробуйте снова.", message.chat.id)
