FROM python:3.12-slim

# Cài thư viện hệ thống (bao gồm opus và ffmpeg)
RUN apt update && apt install -y ffmpeg libopus0

WORKDIR /bot

COPY . .

RUN pip install --no-cache-dir -r requirements.txt

CMD ["python", "main.py"]
