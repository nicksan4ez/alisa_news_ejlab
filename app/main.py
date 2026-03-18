import re
import time
from bs4 import BeautifulSoup
import httpx
from fastapi import FastAPI, Request

app = FastAPI()

CHANNEL_URL = "https://t.me/s/ejlabru"

# Маскируемся под обычный браузер
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

# --- Настройки кэширования ---
CACHE_TTL = 300  # Время жизни кэша в секундах (5 минут)
cache = {
    "timestamp": 0,
    "data": None
}

def clean_text_for_alice(text: str) -> str:
    """Очищаем текст от ссылок, эмодзи и вводных конструкций"""
    text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
    text = re.sub(r'ЕЖ\.\s*(Утро|День|Вечер)[^:]*:\s*', '', text)
    text = re.sub(r'\d+️⃣\s*', '', text)
    text = re.sub(r'\n+', '\n', text).strip()
    return text

async def fetch_latest_news():
    """Парсим веб-версию канала и достаем посты (с кэшированием)"""
    current_time = time.time()
    
    # Возвращаем кэш, если он еще свежий
    if cache["data"] and (current_time - cache["timestamp"] < CACHE_TTL):
        return cache["data"]

    # Если кэш устарел, идем в Telegram
    async with httpx.AsyncClient() as client:
        response = await client.get(CHANNEL_URL, headers=HEADERS)
    
    soup = BeautifulSoup(response.text, 'html.parser')
    messages = soup.find_all('div', class_='tgme_widget_message_text')
    
    news = {
        "утро": None,
        "день": None,
        "вечер": None,
        "последние": None
    }
    
    for msg in reversed(messages):
        text = msg.get_text(separator=' ') 
        found_now = False
        
        if "ЕЖ. Утро" in text and not news["утро"]:
            news["утро"] = clean_text_for_alice(text)
            found_now = True
        elif "ЕЖ. День" in text and not news["день"]:
            news["день"] = clean_text_for_alice(text)
            found_now = True
        elif "ЕЖ. Вечер" in text and not news["вечер"]:
            news["вечер"] = clean_text_for_alice(text)
            found_now = True
            
        # Запоминаем первую же найденную целевую новость как самую свежую
        if found_now and not news["последние"]:
            news["последние"] = clean_text_for_alice(text)
            
        if news["утро"] and news["день"] and news["вечер"]:
            break
            
    # Обновляем кэш
    cache["data"] = news
    cache["timestamp"] = current_time
        
    return news

@app.post("/alice")
async def alice_webhook(request: Request):
    req_data = await request.json()
    command = req_data.get("request", {}).get("command", "").lower()
    
    try:
        news_data = await fetch_latest_news()
    except Exception:
        return build_response("Произошла ошибка при получении новостей с канала.", end_session=True)

    text_to_say = ""
    
    if "последн" in command or "свеж" in command:
        text_to_say = news_data["последние"] if news_data["последние"] else "Сегодня новостей еще не было."
    elif "утро" in command:
        text_to_say = news_data["утро"] if news_data["утро"] else "Утренний пост еще не вышел."
    elif "день" in command:
        text_to_say = news_data["день"] if news_data["день"] else "Дневной пост еще не вышел."
    elif "вечер" in command:
        text_to_say = news_data["вечер"] if news_data["вечер"] else "Вечерний пост еще не вышел."
    else:
        text_to_say = "Какие новости вам прочитать? Последние, за утро, день или вечер?"
        return build_response(text_to_say, end_session=False)

    return build_response(text_to_say, end_session=True)

def truncate_for_alice(text: str, limit: int = 1024) -> str:
    """Обрезает текст до лимита по последней точке, чтобы не обрывать на полуслове"""
    if len(text) <= limit:
        return text
    
    truncated = text[:limit]
    last_dot_index = truncated.rfind('.')
    
    if last_dot_index != -1:
        return truncated[:last_dot_index + 1]
    
    return truncated

def build_response(text: str, end_session: bool):
    """Формирует правильный JSON-ответ для Яндекса"""
    safe_text = truncate_for_alice(text)
    
    return {
        "response": {
            "text": safe_text, 
            "tts": safe_text, 
            "end_session": end_session
        },
        "version": "1.0"
    }