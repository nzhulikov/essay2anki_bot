import os
import openai
import telebot
import csv
import zipfile
import uuid
import json
from hashlib import sha256

# Configuration
TELEGRAM_TOKEN = os.getenv("ESSAY2ANKI_BOT_KEY")
OPENAI_API_KEY = os.getenv("ESSAY2ANKI_OPENAI_KEY")
DEFAULT_LANGUAGE = "греческий"

# Initialize APIs
bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = openai.OpenAI(api_key=OPENAI_API_KEY)

def translate_text(text, language):
    """Uses ChatGPT to translate and structure text into standard Greek while keeping original phrases."""
    prompt = (
        f"Переведи на стандартный современный {language} язык "
        "с соблюдением всех грамматических норм, сохраняя "
        "исходный стиль написания и уровень используемой лексики. "
        "Разбей переведённый текст на короткие отрывки 1-2 неразрывно "
        "связанных повествованием предложения для лёгкости заучивания текста наизусть. "
        "Ответ сделай максимально компактным, не добавляя лишнего текста. "
        "Строго напиши ответ в формате .csv с разделителем ; для импорта в Anki:\n"
        "отрывок из оригинала;переведённый отрывок\n"
        "Например:\n"
        "\"Это текст для перевода. Он состоит из двух отрывков.\". Ответ:\n"
        "Это текст для перевода;Αυτό είναι το κείμενο για μετάφραση\n"
        "Он состоит из двух отрывков;Αποτελείται από δύο περάσματα.\n"
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

def save_settings(chat_dir, settings, language):
    settings["language"] = language
    with open(f"{chat_dir}/settings.json", "w") as f:
        json.dump(settings, f)

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    # create directory for this chat if not exists
    chat_dir = str(message.chat.id)
    
    if message.text == "/start":
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
                                         "Для импорта в Anki:\n"
                                         "  1. Скачай колоду\n"
                                         "  2. Распакуй её\n"
                                         "  3. Создай в Anki колоду с названием, соответствующим названию текста\n"
                                         "  4. Импортируй в Anki файл с расширением .csv\n"
                                         "  5. Скопируй с заменой директорию collection.media в `%APPDATA%\\Anki2\\1-й Пользователь`\n"
                                         "Готово!\n"
                                         "Доступные команды:\n"
                                         "/lang - текущий язык перевода\n"
                                         "/gr - изменить язык на греческий\n"
                                         "/sb - изменить язык на сербский\n"
                                         "/en - изменить язык на английский\n"
                                         "/help - показать это сообщение\n"
                                         "/start - начать сначала\n"
                                         )
        return
    
    if not os.path.exists(chat_dir):
        bot.send_message(message.chat.id, "Сначала отправь /start")
        return
    settings = {"language": DEFAULT_LANGUAGE}
    if not os.path.exists(f"{chat_dir}/settings.json"):
        with open(f"{chat_dir}/settings.json", "w") as f:
            json.dump(settings, f)
    else:
        with open(f"{chat_dir}/settings.json", "r") as f:
            settings = json.load(f)

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
    if len(message.text) > 1000:
        bot.send_message(message.chat.id, "Текст слишком длинный, попробуй меньше 1000 символов.")
        return

    status_message = bot.send_message(message.chat.id, "Перевожу текст...")
    bot.send_chat_action(message.chat.id, "typing")

    conversation_id = uuid.uuid4().hex
    try:
        os.makedirs(f"{chat_dir}/{conversation_id}")

        translated_text = translate_text(message.text, settings["language"])
        lines = translated_text.strip().split("\n")
        lines = [line for line in lines if ';' in line]

        if not lines:
            bot.edit_message_text("Не получилось перевести текст, попробуйте снова.", message.chat.id, status_message.id)
            return

        if len(lines) > 25 or any(len(line) > 250 for line in lines):
            bot.edit_message_text("Получился слишком длинный текст, попробуйте снова.", message.chat.id, status_message.id)
            return

        deck_name = lines[0].split(";")[0].strip()
        csv_filename = f"collection.csv"
        zip_filename = f"{deck_name}.zip"
        audio_files = []
        bot.edit_message_text("Озвучиваю текст...", message.chat.id, status_message.id)
        bot.send_chat_action(message.chat.id, "record_voice")
        # Prepare CSV file
        with open(f"{chat_dir}/{conversation_id}/{csv_filename}", "w", newline="", encoding="utf-8") as csvfile:
            separator = ";"
            csvfile.writelines(
                [f"#separator:;\n",
                f"#tags:эссе\n",
                f"#deck:{deck_name}\n",
                f"#columns:Front;Back\n"])
            writer = csv.writer(csvfile, delimiter=separator)
            for i in range(0, len(lines)):
                original = lines[i].split(";")[0].strip()
                translated = lines[i].split(";")[1].strip()
                mp3_filename = f"phrase_{len(audio_files)+1}_{sha256(translated.encode()).hexdigest()}.mp3"
                mp3_filename_path = f"{chat_dir}/{conversation_id}/{mp3_filename}"

                synthesize_speech(translated, mp3_filename_path)
                audio_files.append(mp3_filename_path)

                writer.writerow([original, f"{translated}[sound:{mp3_filename}]"])
        bot.edit_message_text("Собираю колоду...", message.chat.id, status_message.id)
        bot.send_chat_action(message.chat.id, "typing")
        # Create a ZIP file with CSV and MP3s
        with zipfile.ZipFile(f"{chat_dir}/{conversation_id}/{zip_filename}", "w") as zipf:
            zipf.write(f"{chat_dir}/{conversation_id}/{csv_filename}", csv_filename)
            for file in audio_files:
                zipf.write(file, f"collection.media/{os.path.basename(file)}")

        bot.edit_message_text("Отправляю колоду...", message.chat.id, status_message.id)
        bot.send_chat_action(message.chat.id, "upload_document")
        # Send ZIP file to user
        with open(f"{chat_dir}/{conversation_id}/{zip_filename}", "rb") as zipf:
            bot.send_document(message.chat.id, zipf)
        bot.delete_message(message.chat.id, status_message.id)
    except Exception as e:
        bot.edit_message_text(f"Ошибка: {e}", message.chat.id, status_message.id)
    finally:
        # Clean up files
        for file in os.listdir(f"{chat_dir}/{conversation_id}"):
            os.remove(f"{chat_dir}/{conversation_id}/{file}")

        os.rmdir(f"{chat_dir}/{conversation_id}")
