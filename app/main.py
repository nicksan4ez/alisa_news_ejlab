import re
from bs4 import BeautifulSoup
import httpx
from fastapi import FastAPI, Request

app = FastAPI()

CHANNEL_URL = "https://t.me/s/ejlabru"

# Маскируемся под обычный браузер
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
}

def clean_text_for_alice(text: str) -> str:
    """Очищаем текст от ссылок, эмодзи и вводных конструкций"""
    
    # 1. Удаляем URL-адреса
    text = re.sub(r'http[s]?://(?:[a-zA-Z]|[0-9]|[$-_@.&+]|[!*\(\),]|(?:%[0-9a-fA-F][0-9a-fA-F]))+', '', text)
    
    # 2. Удаляем вводную фразу вроде "ЕЖ. Утро — главные новости к этому часу:"
    # Регулярка ищет "ЕЖ.", затем Утро/День/Вечер, любой текст до двоеточия и само двоеточие
    text = re.sub(r'ЕЖ\.\s*(Утро|День|Вечер)[^:]*:\s*', '', text)
    
    # 3. Удаляем эмодзи-цифры (1️⃣, 2️⃣, 10️⃣ и т.д.)
    # Ищем любую цифру, за которой идет символ квадратика-эмодзи
    text = re.sub(r'\d+️⃣\s*', '', text)
    
    # 4. Очищаем от лишних переносов строк и пробелов по краям
    text = re.sub(r'\n+', '\n', text).strip()
    
    return text

async def fetch_latest_news():
    """Парсим веб-версию канала и достаем 3 последних поста по категориям"""
    async with httpx.AsyncClient() as client:
        response = await client.get(CHANNEL_URL, headers=HEADERS)
    
    soup = BeautifulSoup(response.text, 'html.parser')
    messages = soup.find_all('div', class_='tgme_widget_message_text')
    
    news = {
        "утро": None,
        "день": None,
        "вечер": None
    }
    
    # Идем с конца, чтобы брать самые свежие посты за сегодня
    for msg in reversed(messages):
        # get_text(separator=' ') заменяет <br> на пробелы
        text = msg.get_text(separator=' ') 
        
        if "ЕЖ. Утро" in text and not news["утро"]:
            news["утро"] = clean_text_for_alice(text)
        elif "ЕЖ. День" in text and not news["день"]:
            news["день"] = clean_text_for_alice(text)
        elif "ЕЖ. Вечер" in text and not news["вечер"]:
            news["вечер"] = clean_text_for_alice(text)
            
        # Если нашли все три, прерываем цикл
        if all(news.values()):
            break
            
    return news

@app.post("/alice")
async def alice_webhook(request: Request):
    req_data = await request.json()
    
    # Получаем то, что сказал пользователь (в нижнем регистре)
    command = req_data.get("request", {}).get("command", "").lower()
    
    # Парсим свежие новости в реальном времени
    try:
        news_data = await fetch_latest_news()
    except Exception as e:
        return build_response("Произошла ошибка при получении новостей с канала.", end_session=True)

    # Определяем, что именно нужно зачитать
    text_to_say = ""
    
    if "сутки" in command or "весь день" in command or "все" in command:
        parts = []
        if news_data["утро"]: parts.append(news_data["утро"])
        if news_data["день"]: parts.append(news_data["день"])
        if news_data["вечер"]: parts.append(news_data["вечер"])
        
        if parts:
            text_to_say = "Новости за сутки. " + " \n ".join(parts)
        else:
            text_to_say = "Не нашла постов за сегодня."
            
    elif "утро" in command:
        text_to_say = news_data["утро"] if news_data["утро"] else "Утренний пост еще не вышел."
    elif "день" in command:
        text_to_say = news_data["день"] if news_data["день"] else "Дневной пост еще не вышел."
    elif "вечер" in command:
        text_to_say = news_data["вечер"] if news_data["вечер"] else "Вечерний пост еще не вышел."
    else:
        # Если команда не распознана (например, при запуске навыка без параметров)
        text_to_say = "Какие новости вам прочитать? За утро, день, вечер или за весь день?"
        return build_response(text_to_say, end_session=False)

    return build_response(text_to_say, end_session=True)

def truncate_for_alice(text: str, limit: int = 1024) -> str:
    """Обрезает текст до лимита по последней точке, чтобы не обрывать на полуслове"""
    if len(text) <= limit:
        return text
    
    # Берем максимально допустимый кусок текста
    truncated = text[:limit]
    
    # Ищем индекс последней точки в этом куске
    last_dot_index = truncated.rfind('.')
    
    # Если точка найдена, обрезаем по нее (включая саму точку)
    if last_dot_index != -1:
        return truncated[:last_dot_index + 1]
    
    # Резервный вариант: если точек почему-то нет вообще (например, сплошной текст)
    return truncated

def build_response(text: str, end_session: bool):
    """Формирует правильный JSON-ответ для Яндекса"""
    
    # Пропускаем текст через наш "умный" обрезатель
    safe_text = truncate_for_alice(text)
    
    return {
        "response": {
            "text": safe_text, 
            "tts": safe_text, 
            "end_session": end_session
        },
        "version": "1.0"
    }