# ikosy — Telegram Mini App

Готовый стартовый Telegram Mini App для сервиса объявлений.

## Возможности
- Главная и поиск
- Категории
- Карточки объявлений
- Избранное
- Профиль
- Публикация объявления
- Редактирование и удаление
- Уведомления
- Выбор города
- Простая админ-панель
- SQLite база данных
- Telegram Mini App initData validation
- Telegram-бот с кнопкой открытия Mini App

## Запуск локально
1. Установите Python 3.11+.
2. `pip install -r requirements.txt`
3. Задайте переменные:
   - `BOT_TOKEN`
   - `BOT_USERNAME`
   - `WEBAPP_URL`
4. Запустите: `uvicorn app:app --reload`
5. Откройте `http://127.0.0.1:8000`

Для Telegram Mini App нужен HTTPS-адрес. На Render используйте `render.yaml`.

## Важно
Это рабочий MVP-каркас. Перед публичным запуском добавьте модерацию, rate limits, резервные копии БД и реальное хранилище изображений (S3/Cloudinary и т.п.).
