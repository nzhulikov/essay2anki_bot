from functools import partial
import os
import re
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
available_genders = {
    "male": "Мужской",
    "female": "Женский",
}
gender_to_voices_map = {
    "male": ["ash", "echo"],
    "female": ["coral", "nova"]
}
voice_to_gender_map = {voice: gender for gender,voices in gender_to_voices_map.items() for voice in voices}
available_voices = {
    "ash": "Бархатный, низкий",
    "echo": "Приятный, мягкий",
    "coral": "Тихий, спокойный",
    "nova": "Деловой, чистый"
}

DEFAULT_LANGUAGE = "gr"
DEFAULT_ANKI = False
DEFAULT_VOICE = "ash"
DEFAULT_INSTRUCTIONS = "спокойно, дружелюбно"


def handle_error(input: Message | CallbackQuery, e: Exception):
    logger.error(f"Error handling message: {e}", exc_info=True)
    if isinstance(input, CallbackQuery):
        bot.edit_message_text(chat_id=input.message.chat.id, message_id=input.message.id, text="Произошла ошибка, попробуйте снова.")
    else:
        bot.send_message(input.chat.id, "Произошла ошибка, попробуйте снова.")


def handle_error_decorator(func):
    def wrapper(message_or_callback: Message | CallbackQuery):
        try:
            return func(message_or_callback)
        except Exception as e:
            handle_error(message_or_callback, e)
    return wrapper


def translate_text(text, settings):
    """Uses ChatGPT to translate and structure text into standard Greek while keeping original phrases."""
    prompt = (
        f"Переведи на стандартный современный {available_languages[settings['language']]} язык "
        "с соблюдением всех грамматических норм, сохраняя "
        "исходный стиль написания и уровень используемой лексики. "
        "Ответ сделай максимально компактным, не добавляя лишнего текста. "
        "Разбей переведённый текст на короткие отрывки 1-2 неразрывно "
        "связанных повествованием предложения для лёгкости заучивания текста наизусть. "
        "Добавь инструкции для tts генератора, чтобы он читал текст максимально естественно "
        "и соответствуя смыслу написанного текста."
        "Например, если в тексте есть юмор, то дай инструкию сделать голос весёлым."
        "Или если в тексте есть вопрос, то дай инструкцию сделать голос с вопросительной интонацией."
        "Если в тексте описываются чувства, то дай инструкцию сделать голос более эмоциональным."
        "Если в тексте описываются радостные события, то дай инструкцию сделать голос более динамичным."
        "Если в тексте описываются трагические события, то дай инструкцию сделать голос более грустным."
        "Если в тексте описываются опасные события, то дай инструкцию сделать голос более тревожным."
        "Если в тексте описываются нейтральные события, то дай инструкцию сделать голос спокойным и дружелюбным."
        f"Пол автора текста: {settings['gender']}"
        "Строго напиши ответ в формате .csv с разделителем ; для импорта в Anki:\n"
        "отрывок из оригинала;переведённый отрывок;инструкция для tts генератора\n"
        "Например:\n"
        "\"Это текст для перевода. Он состоит из двух отрывков.\". Ответ:\n"
        "Это текст для перевода;Αυτό είναι το κείμενο για μετάφραση;спокойно, дружелюбно.\n"
        "Я был так напуган;I was so scared;тревожно, напуганно.\n"
        f"Вот текст для перевода:\n{text}"
    ) if settings["anki"] else (
        f"Переведи на стандартный современный {available_languages[settings['language']]} язык "
        "с соблюдением всех грамматических норм, сохраняя "
        "исходный стиль написания и уровень используемой лексики. "
        "Ответ сделай максимально компактным, не добавляя лишнего текста. "
        "В скобках напиши инструкцию для tts генератора, чтобы он читал текст с определённым настроем."
        "Например, если в тексте есть юмор, то дай инструкию сделать голос весёлым."
        "Или если в тексте есть вопрос, то дай инструкцию сделать голос с вопросительной интонацией."
        "Если в тексте описываются чувства, то дай инструкцию сделать голос более эмоциональным."
        "Если в тексте описываются радостные события, то дай инструкцию сделать голос более динамичным."
        "Если в тексте описываются трагические события, то дай инструкцию сделать голос более грустным."
        "Если в тексте описываются опасные события, то дай инструкцию сделать голос более тревожным."
        "Если в тексте описываются нейтральные события, то дай инструкцию сделать голос спокойным и дружелюбным."
        f"Пол автора текста: {settings['gender']}"
        "Пример перевода:\n"
        "\"Я был так напуган. Это мой первый полёт.\" -> \"(встревоженно, эмоционально) I was so scared. This is my first flight.\"\n"
        f"Вот текст для перевода:\n{text}"
    )
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9
    )
    return response.choices[0].message.content


def synthesize_speech(text, instructions, filename, settings):
    """Converts text to speech using OpenAI TTS and saves as MP3."""
    response = client.audio.speech.create(
        model="gpt-4o-mini-tts",
        voice=settings["voice"],
        input=text,
        instructions=instructions
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
    settings = {"language": DEFAULT_LANGUAGE, "anki": DEFAULT_ANKI, "voice": DEFAULT_VOICE, "gender": voice_to_gender_map[DEFAULT_VOICE]}
    if not os.path.exists(f"{chat_dir}/settings.json"):
        with open(f"{chat_dir}/settings.json", "w") as f:
            json.dump(settings, f)
    else:
        with open(f"{chat_dir}/settings.json", "r") as f:
            settings = {**settings, **json.load(f)}  
        if settings["language"] not in available_languages:
            settings["language"] = DEFAULT_LANGUAGE
        if settings["voice"] not in available_voices:
            settings["voice"] = DEFAULT_VOICE
        if settings["gender"] not in available_genders:
            settings["gender"] = voice_to_gender_map[settings["voice"]]
        if settings["anki"] not in [True, False]:
            settings["anki"] = DEFAULT_ANKI
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
    path_to_ssl_certificate = os.path.join(os.path.dirname(__file__), "ssl_certificate.pem")
    bot.set_webhook(url=webhook_url + "/webhook",
                    certificate=path_to_ssl_certificate,
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
    sentences.append(f"*Язык:* {available_languages[settings['language']]}")
    sentences.append(f"*{available_genders[settings['gender']]} голос:* {available_voices[settings['voice']]}")
    text = '\n'.join(sentences)
    if edit_message_id:
        func = partial(bot.edit_message_text, text, chat_id=chat_id, message_id=edit_message_id)
    else:
        func = partial(bot.send_message, chat_id, text)
    func(
        reply_markup=InlineKeyboardMarkup(
            keyboard=[
                [mode_btn, InlineKeyboardButton(text="Язык", callback_data="lang"),  InlineKeyboardButton(text="Голос", callback_data="voice")]
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
@handle_error_decorator
def handle_start(message: Message):
    chat_dir = get_chat_dir(message.chat.id)
    for file in os.listdir(chat_dir):
        os.remove(f"{chat_dir}/{file}")
    init_commands(message.chat.id)
    bot.send_message(message.chat.id, "Отправь мне текст, и я переведу его и озвучу. Ограничение 5000 символов.")


@bot.message_handler(commands=["settings"])
@handle_error_decorator
def handle_settings(message: Message):
    show_settings(message.chat.id)


@bot.callback_query_handler(func=lambda call: call.data in available_voices)
@handle_error_decorator
def handle_voice_callback(call: CallbackQuery):
    chat_dir = get_chat_dir(call.message.chat.id)
    settings = get_settings(chat_dir)
    save_settings(chat_dir, settings, voice=call.data, gender=voice_to_gender_map[call.data])
    show_settings(call.message.chat.id, call.message.id)


@bot.callback_query_handler(func=lambda call: call.data in available_genders)
@handle_error_decorator
def handle_gender_callback(call: CallbackQuery):
    voices = gender_to_voices_map[call.data]
    bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.id, text="Выберите голос",
                              reply_markup=InlineKeyboardMarkup(
                                keyboard=[
                                    [InlineKeyboardButton(text=available_voices[voice], callback_data=voice) for voice in voices],
                                    [InlineKeyboardButton(text="Назад", callback_data="back_to_settings")]
                                ]
                              ))



@bot.callback_query_handler(func=lambda call: call.data in ["back_to_settings"])
@handle_error_decorator
def handle_back_to_settings_callback(call: CallbackQuery):
    show_settings(call.message.chat.id, call.message.id)


@bot.callback_query_handler(func=lambda call: call.data in ["anki", "chat", "lang", "voice"])
@handle_error_decorator
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
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.id, text=f"Выберите язык перевода",
                              reply_markup=InlineKeyboardMarkup(
                                keyboard=[
                                    [InlineKeyboardButton(text=language_flag_emojis[language], callback_data=language) for language in available_languages.keys()],
                                    [InlineKeyboardButton(text="Назад", callback_data="back_to_settings")]
                                ]
                              ))
    elif call.data == "voice":
        bot.edit_message_text(chat_id=call.message.chat.id, message_id=call.message.id, text=f"Выберите пол",
                              reply_markup=InlineKeyboardMarkup(
                                keyboard=[
                                    [InlineKeyboardButton(text=gender_name, callback_data=gender) for gender, gender_name in available_genders.items()],
                                    [InlineKeyboardButton(text="Назад", callback_data="back_to_settings")]
                                ]
                              ))

@bot.callback_query_handler(func=lambda call: call.data in available_languages)
@handle_error_decorator
def handle_lang_callback(call: CallbackQuery):
    chat_dir = get_chat_dir(call.message.chat.id)
    settings = get_settings(chat_dir)
    save_settings(chat_dir, settings, language=call.data)
    show_settings(call.message.chat.id, call.message.id)


@bot.message_handler(commands=["help"])
@handle_error_decorator
def handle_help(message: Message):
    commands = bot.get_my_commands()
    sentences = [
        "Отправь мне текст, и я переведу его и озвучу. Ограничение 1000 символов.",
        "Доступные команды:",
        *[f"/{command.command} - {command.description}" for command in commands]
    ]
    bot.send_message(message.chat.id, '\n'.join(sentences))


@bot.message_handler()
@handle_error_decorator
def handle_message(message: Message):
    if message.text.startswith("/"):
        handle_help(message)
        return
    if len(message.text) > 5000:
        bot.send_message(message.chat.id, "Текст слишком длинный, попробуй меньше 5000 символов.")
        return
    if len(message.text) < 10:
        bot.send_message(message.chat.id, "Текст слишком короткий, попробуй больше 10 символов.")
        return

    chat_dir = get_chat_dir(message.chat.id)
    settings = get_settings(chat_dir)

    with tempfile.TemporaryDirectory() as tmpdir:
        bot.send_chat_action(message.chat.id, "typing")
        translated_text = translate_text(message.text, settings)
        if len(translated_text) > 7000:
            bot.send_message("Получился слишком длинный текст, попробуйте снова.", message.chat.id)
            return
        if not settings["anki"]:
            # strip instructions from translated text in brackets
            instructions = re.search(r'\((.*?)\)', translated_text)
            if instructions:
                instructions = instructions.group(1)
                translated_text = re.sub(r'\((.*?)\)', '', translated_text)
            else:
                instructions = DEFAULT_INSTRUCTIONS    
            bot.send_message(message.chat.id, translated_text, reply_parameters=ReplyParameters(message.id, allow_sending_without_reply=True))
            bot.send_chat_action(message.chat.id, "record_voice")
            audio_filename = os.path.join(tmpdir, f"audio_{sha256(translated_text.encode()).hexdigest()}.mp3")
            synthesize_speech(translated_text, instructions, audio_filename, settings)
            with open(audio_filename, "rb") as audio:
                bot.send_voice(message.chat.id, audio,
                    reply_parameters=ReplyParameters(message.id, allow_sending_without_reply=True))
            return
        
        lines = translated_text.strip().split("\n")
        lines = [line for line in lines if ';' in line]

        if not lines:
            bot.send_message("Не получилось перевести текст, попробуйте снова.", message.chat.id)
            return

        translated_text = '\n'.join([f"*{line.split(';')[0]}* | {line.split(';')[1]}" for line in lines])
        bot.send_message(message.chat.id, translated_text,
            reply_parameters=ReplyParameters(message.id, allow_sending_without_reply=True),
            parse_mode="Markdown")

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
                instructions = lines[i].split(";")[2].strip()
                mp3_filename = f"phrase_{len(add_note_requests)+1}_{sha256(translated.encode()).hexdigest()}.mp3"
                mp3_filename_path = os.path.join(tmpdir, mp3_filename)

                synthesize_speech(translated, instructions, mp3_filename_path, settings)
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
                            reply_parameters=ReplyParameters(message.id, allow_sending_without_reply=True))
