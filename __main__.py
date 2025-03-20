import os
import openai
import telebot
import csv
import zipfile

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
        "первой строкой в ответе напиши короткое название отрывка на языке оригинала без знаков препинания. "
        "Далее напиши ответ в формате для импорта в Anki:\n"
        "отрывок из оригинала;переведённый отрывок\n"
        f"Вот текст для перевода:\n{text}"
    )
    
    response = client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "user", "content": prompt}]
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

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    # Create a subdirectory for this chat if it doesn't exist
    chat_dir = str(message.chat.id)
    if not os.path.exists(chat_dir):
        os.makedirs(chat_dir)
    os.chdir(chat_dir)

    bot.send_chat_action(message.chat.id, "typing")
    status_message = bot.send_message(message.chat.id, "Перевожу текст...")
    translated_text = translate_text(message.text)
    lines = translated_text.strip().split("\n")

    csv_filename = f"anki_import.csv"
    zip_filename = f"{lines[0]}.zip"
    audio_files = []
    bot.edit_message_text("Озвучиваю текст...", message.chat.id, status_message.id)
    # Prepare CSV file
    with open(csv_filename, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile, delimiter=";")
        writer.writerow(["оригинал", "перевод", "произношение"])

        for i in range(1, len(lines)):
            has_line = ";" in lines[i]
            if not has_line:
                continue
            original = lines[i].split(";")[0].strip()
            translated = lines[i].split(";")[1].strip()
            mp3_filename = f"phrase_{len(audio_files)+1}.mp3"

            synthesize_speech(translated, mp3_filename)
            audio_files.append(mp3_filename)

            writer.writerow([original, translated, f"[sound:{mp3_filename}]"])

    bot.edit_message_text("Собираю колоду...", message.chat.id, status_message.id)
    # Create a ZIP file with CSV and MP3s
    with zipfile.ZipFile(zip_filename, "w") as zipf:
        zipf.write(csv_filename)
        for file in audio_files:
            zipf.write(file)

    bot.edit_message_text("Отправляю колоду...", message.chat.id, status_message.id)
    # Send ZIP file to user
    with open(zip_filename, "rb") as zipf:
        bot.send_document(message.chat.id, zipf)
    bot.delete_message(message.chat.id, status_message.id)

    # Clean up files
    for file in audio_files:
        os.remove(file)
    os.remove(csv_filename)
    os.remove(zip_filename)

    os.chdir("..")
    os.rmdir(chat_dir)

bot.polling()
