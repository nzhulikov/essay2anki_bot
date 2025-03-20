import os
import openai
import telebot
import csv
import zipfile
from hashlib import sha256

# Configuration
TELEGRAM_TOKEN = os.getenv("ESSAY2ANKI_BOT_KEY")
OPENAI_API_KEY = os.getenv("ESSAY2ANKI_OPENAI_KEY")

# Initialize APIs
bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = openai.OpenAI(api_key=OPENAI_API_KEY)

def translate_text(text):
    """Uses ChatGPT to translate and structure text into standard Greek while keeping original phrases."""
    prompt = (
        "Переведи на стандартный современный греческий язык "
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
    print(prompt)
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}],
        temperature=0.9
    )
    print(response.choices[0].message.content)
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

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    # Create a subdirectory for this chat if it doesn't exist
    status_message = bot.send_message(message.chat.id, "Перевожу текст...")
    bot.send_chat_action(message.chat.id, "typing")

    try:
        chat_dir = str(message.chat.id)
        if not os.path.exists(chat_dir):
            os.makedirs(chat_dir)
        os.chdir(chat_dir)
        os.makedirs("collection.media")

        translated_text = translate_text(message.text)
        lines = translated_text.strip().split("\n")
        lines = [line for line in lines if ';' in line]
        deck_name = lines[0].split(";")[0].strip()
        csv_filename = f"collection.csv"
        zip_filename = f"{deck_name}.zip"
        audio_files = []
        bot.edit_message_text("Озвучиваю текст...", message.chat.id, status_message.id)
        bot.send_chat_action(message.chat.id, "record_voice")
        # Prepare CSV file
        with open(csv_filename, "w", newline="", encoding="utf-8") as csvfile:
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
                mp3_filename_path = f"collection.media/{mp3_filename}"

                synthesize_speech(translated, mp3_filename_path)
                audio_files.append(mp3_filename_path)

                writer.writerow([original, f"{translated}[sound:{mp3_filename}]"])
        bot.edit_message_text("Собираю колоду...", message.chat.id, status_message.id)
        bot.send_chat_action(message.chat.id, "typing")
        # Create a ZIP file with CSV and MP3s
        with zipfile.ZipFile(zip_filename, "w") as zipf:
            zipf.write(csv_filename)
            for file in audio_files:
                zipf.write(file)

        bot.edit_message_text("Отправляю колоду...", message.chat.id, status_message.id)
        bot.send_chat_action(message.chat.id, "upload_document")
        # Send ZIP file to user
        with open(zip_filename, "rb") as zipf:
            bot.send_document(message.chat.id, zipf)
        bot.delete_message(message.chat.id, status_message.id)

        # Clean up files
        for file in os.listdir("collection.media"):
            os.remove(f"collection.media/{file}")
        os.rmdir("collection.media")

        for file in os.listdir():
            os.remove(file)

        os.chdir("..")
        os.rmdir(chat_dir)
    except Exception as e:
        bot.edit_message_text(f"Ошибка: {e}", message.chat.id, status_message.id)
