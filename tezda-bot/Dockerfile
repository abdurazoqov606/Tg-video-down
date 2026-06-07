# Yengil va tezkor Python 3.10 versiyasi
FROM python:3.10-slim

# FFmpeg va kerakli tizim paketlarini o'rnatish (Root huquqida)
RUN apt-get update && \
    apt-get install -y ffmpeg curl && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Ishchi papkani belgilash
WORKDIR /app

# Kutubxonalarni o'rnatish
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Bot kodi va boshqa fayllarni nusxalash
COPY . .

# Render kutadigan portni ochish
EXPOSE 8080

# Botni ishga tushirish
CMD ["python", "bot.py"]
