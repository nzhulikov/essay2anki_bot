import os
import openai
import telebot
import json
import tempfile
import logging
from hashlib import sha256
from telebot.types import ReplyParameters, Message, MenuButtonCommands, BotCommand, BotCommandScopeChat

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
available_languages = {
    "gr": "греческий",
    "sb": "сербский",
    "en": "английский",
    "nl": "нидерландский",
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


def init_commands(chat_id):
    bot.set_chat_menu_button(
        chat_id=chat_id,
        menu_button=MenuButtonCommands()
    )
    bot.set_my_commands(
        commands=[
            BotCommand(command="start", description="Начать работу с ботом"),
            BotCommand(command="settings", description="Настройки бота"),
            BotCommand(command="help", description="Показать доступные команды"),
        ],
        scope=BotCommandScopeChat(chat_id=chat_id)
    )

def init_language_commands(chat_id):
    commands = [BotCommand(command=command, description=f"Изменить язык на {language}") for command,language in available_languages.items()]
    commands.append(BotCommand(command="back", description="Вернуться к выбору настроек"))
    bot.set_my_commands(
        commands=commands,
        scope=BotCommandScopeChat(chat_id=chat_id)
    )


def init_settings_commands(chat_id):
    bot.set_my_commands(
        commands=[
            BotCommand(command="anki", description="Изменить режим на подготовку колоды для Anki"),
            BotCommand(command="chat", description="Изменить режим на отправку переводов в чат"),
            BotCommand(command="lang", description="Изменить текущий язык перевода"),
            BotCommand(command="back", description="Вернуться к главному меню"),
        ],
        scope=BotCommandScopeChat(chat_id=chat_id)
    )


@bot.message_handler(commands=["back"])
def handle_back_command(message: Message):
    current_commands = bot.get_my_commands()
    if current_commands[0].command in available_languages.keys():
        init_language_commands(message.chat.id)
    else:
        init_commands(message.chat.id)


@bot.message_handler(commands=["start"])
def handle_start(message: Message):
    chat_dir = str(message.chat.id)
    if os.path.exists(chat_dir):
        for file in os.listdir(chat_dir):
            os.remove(f"{chat_dir}/{file}")
    else:
        os.makedirs(chat_dir)
    init_commands(message.chat.id)


@bot.message_handler(commands=["settings"])
def handle_settings(message: Message):
    chat_dir = str(message.chat.id)
    settings = get_settings(chat_dir)
    sentences = []
    if settings["anki"]:
        sentences.append("Я буду готовить колоду для Anki.")
    else:
        sentences.append("Я буду отправлять переводы в чат.")
    sentences.append(f"Я перевожу текст на {settings['language']} язык.")
    bot.send_message(message.chat.id, '\n'.join(sentences))
    init_settings_commands(message.chat.id)


@bot.message_handler(commands=["lang"])
def handle_lang(message: Message):
    chat_dir = str(message.chat.id)
    settings = get_settings(chat_dir)
    bot.send_message(message.chat.id, f"Я перевожу текст на {settings['language']} язык.")
    init_language_commands(message.chat.id)


@bot.message_handler(commands=["gr", "sb", "en", "nl"])
def handle_set_language(message: Message):
    chat_dir = str(message.chat.id)
    settings = get_settings(chat_dir)
    language = available_languages[message.text[1:]]
    save_settings(chat_dir, settings, language=language)
    bot.send_message(message.chat.id, f"Теперь я перевожу текст на {language} язык.")
    init_settings_commands(message.chat.id)


@bot.message_handler(commands=["anki"])
def handle_anki(message: Message):
    chat_dir = str(message.chat.id)
    settings = get_settings(chat_dir)
    save_settings(chat_dir, settings, anki=True)
    bot.send_message(message.chat.id, "Теперь я буду готовить колоду для Anki.")
    init_commands(message.chat.id)


@bot.message_handler(commands=["chat"])
def handle_chat(message: Message):
    chat_dir = str(message.chat.id)
    settings = get_settings(chat_dir)
    save_settings(chat_dir, settings, anki=False)
    bot.send_message(message.chat.id, "Теперь я буду отправлять переводы в чат.")
    init_commands(message.chat.id)


@bot.message_handler(commands=["help"])
def handle_help(message: Message):
    sentences = [
        "Отправь мне текст, и я переведу его и озвучу. Ограничение 1000 символов.",
        "Доступные команды:",
        "/start - начать работу с ботом/сбросить настройки",
        "/settings - настройки бота",
        "/anki - изменить режим на подготовку колоды для Anki",
        "/chat - изменить режим на отправку переводов в чат",
        "/lang - текущий язык перевода",
        *[f"/{command} - изменить язык на {language}" for command, language in available_languages.items()],
        "/help - показать это сообщение"
    ]
    bot.send_message(message.chat.id, '\n'.join(sentences))
    init_commands(message.chat.id)


@bot.message_handler()
def handle_message(message: Message):
    init_commands(message.chat.id)
    chat_dir = str(message.chat.id)
    settings = get_settings(chat_dir)
    if len(message.text) > 1000:
        bot.send_message(message.chat.id, "Текст слишком длинный, попробуй меньше 1000 символов.")
        return

    with tempfile.TemporaryDirectory() as tmpdir:
        bot.send_chat_action(message.chat.id, "upload_document" if settings["anki"] else "typing", timeout=60)
        translated_text = translate_text(message.text, settings)
        if len(translated_text) > 1500:
            bot.send_message("Получился слишком длинный текст, попробуйте снова.", message.chat.id)
            return

        if not settings["anki"]:
            translation_message = bot.send_message(message.chat.id, translated_text,
                reply_parameters=ReplyParameters(message.id, allow_sending_without_reply=True))
            bot.send_chat_action(message.chat.id, "record_voice", timeout=60)
            audio_filename = f"{tmpdir}/audio_{sha256(translated_text.encode()).hexdigest()}.mp3"
            synthesize_speech(translated_text, audio_filename)
            with open(audio_filename, "rb") as audio:
                bot.send_voice(message.chat.id, audio,
                    reply_parameters=ReplyParameters(translation_message.id, allow_sending_without_reply=True))
            return
        
        lines = translated_text.strip().split("\n")
        lines = [line for line in lines if ';' in line]

        if not lines:
            bot.send_message("Не получилось перевести текст, попробуйте снова.", message.chat.id)
            return

        deck_name = lines[0].split(";")[0].strip()
        anki_package_filename = f"{tmpdir}/{deck_name}.apkg"
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

        with open(anki_package_filename, "rb") as zipf:
            bot.send_document(message.chat.id, zipf, reply_parameters=ReplyParameters(message.id, allow_sending_without_reply=True))
