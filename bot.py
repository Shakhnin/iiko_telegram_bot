import requests
import time
import json
import threading
from flask import Flask, request, jsonify

# ========== ВАШИ ДАННЫЕ ==========
IIKO_API_LOGIN = "47769dc09d974cbb981e55b642e01c23"
IIKO_ORG_ID = "a0d2ab37-a949-4354-b26e-075eef2a15d3"
IIKO_API_URL = "https://api-ru.iiko.services/api/1"

TELEGRAM_BOT_TOKEN = "7983836458:AAHDn8MBYdSf5FtXmDfF4VHy8CDdWC6pBy8"
TELEGRAM_CHAT_ID = "-5257859261"  # ID группы

# ========== КОД ==========
app = Flask(__name__)

# Хранилище последних отправленных статусов (чтобы не было дублей)
last_status = {}

# Хранилище времени начала приготовления для каждого заказа
cooking_start_time = {}

# Хранилище отправленных предупреждений о долгом приготовлении
cooking_warning_sent = {}

# Словарь для перевода статусов
status_mapping = {
    'CANCELLED': {'icon': '❌', 'text': 'ЗАКАЗ ОТМЕНЕН'},
}

tracked_statuses = ['CANCELLED']

def send_telegram_message(text):
    """Отправляет сообщение в Telegram группу"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("✅ Сообщение отправлено в Telegram")
        else:
            print(f"❌ Ошибка: {response.text}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

def check_long_cooking():
    """Фоновая задача: каждую минуту проверяет заказы, которые готовятся дольше 30 минут"""
    while True:
        time.sleep(60)  # Проверяем каждую минуту
        current_time = time.time()
        
        print(f"\n⏰ Фоновая проверка: активных заказов в готовке - {len(cooking_start_time)}")
        
        for order_number, start_time in list(cooking_start_time.items()):
            elapsed_minutes = (current_time - start_time) / 60
            print(f"   Заказ {order_number}: готовится {elapsed_minutes:.1f} мин")
            
            # Если прошло больше 30 минут и предупреждение ещё не отправлено
            if elapsed_minutes > 30 and order_number not in cooking_warning_sent:
                cooking_warning_sent[order_number] = True
                
                message = f"""⚠️ <b>ДОЛГОЕ ПРИГОТОВЛЕНИЕ!</b>

📋 <b>Номер заказа:</b> {order_number}
⏱️ <b>Время приготовления:</b> {elapsed_minutes:.0f} минут
📌 <b>Норматив:</b> более 30 минут

<i>Заказ всё ещё в статусе готовки!</i>
<i>Пора проверить, что случилось.</i>
<i>Время: {time.strftime('%H:%M:%S')}</i>"""
                
                send_telegram_message(message)
                print(f"⚠️ Отправлено предупреждение о долгом приготовлении заказа {order_number} ({elapsed_minutes:.0f} мин)")

# Запускаем фоновый поток для проверки долгих заказов
monitoring_thread = threading.Thread(target=check_long_cooking, daemon=True)
monitoring_thread.start()
print("🟢 Фоновый мониторинг долгих заказов запущен (проверка каждую минуту)")

# ===== ОБРАБОТЧИКИ ВЕБХУКОВ =====
# Обработчик для корневого адреса (iiko часто отправляет сюда)
@app.route('/', methods=['POST'])
def handle_webhook_root():
    """Обрабатывает вебхуки, которые iiko отправляет на корневой адрес"""
    return handle_webhook()

# Основной обработчик вебхуков
@app.route('/webhook', methods=['POST'])
def handle_webhook():
    global last_status, cooking_start_time, cooking_warning_sent
    
    data = request.json
    print(f"\n📥 Получен вебхук от iiko!")
    
    webhooks_list = data if isinstance(data, list) else [data]
    
    for webhook in webhooks_list:
        event_type = webhook.get('eventType', 'Unknown')
        print(f"📌 Тип события: {event_type}")
        
        order_number = "Неизвестно"
        status = None
        phone = "Не указан"
        customer_name = "Не указан"
        comment = ""
        cancel_reason = ""
        cancel_operator_comment = ""
        
        if event_type in ['DeliveryOrderUpdate', 'TableOrderUpdate']:
            event_info = webhook.get('eventInfo', {})
            order = event_info.get('order', {})
            status = order.get('status')
            order_number = order.get('number', 'Неизвестно')
            phone = order.get('phone', 'Не указан')
            customer_name = order.get('customer', {}).get('name', 'Не указан')
            comment = order.get('comment', '')
            
            cancel_info = order.get('cancelInfo', {})
            if cancel_info:
                # Причина отмены (из списка)
                cause = cancel_info.get('cause', {})
                if isinstance(cause, dict):
                    cancel_reason = cause.get('name', '')
                elif isinstance(cause, str):
                    cancel_reason = cause
                # Комментарий оператора
                cancel_operator_comment = cancel_info.get('comment', '')
            
            if not cancel_reason:
                cancel_reason = order.get('cancelReason', '')
                        
        elif event_type == 'TableOrderUpdate':
            event_info = webhook.get('eventInfo', {})
            order = event_info.get('order', {})
            status = order.get('status')
            order_number = order.get('number', 'Неизвестно')
            phone = order.get('phone', 'Не указан')
            customer_name = order.get('customer', {}).get('name', 'Не указан')
            comment = order.get('comment', '')
            
            cancel_info = order.get('cancelInfo', {})
            if cancel_info:
                cause = cancel_info.get('cause', {})
                if isinstance(cause, dict):
                    cancel_reason = cause.get('name', '')
                cancel_operator_comment = cancel_info.get('comment', '')
        else:
            status = webhook.get('status')
            order_number = webhook.get('number', 'Неизвестно')
            phone = webhook.get('phone', 'Не указан')
            comment = webhook.get('comment', '')
            cancel_reason = webhook.get('cancelReason', '')
            cancel_operator_comment = webhook.get('cancelComment', '')
        
        print(f"🔍 Номер заказа: {order_number}")
        print(f"🔍 Статус заказа: {status}")
        if comment:
            print(f"📝 Комментарий: {comment}")
        if cancel_reason:
            print(f"❌ Причина отмены: {cancel_reason}")
        if cancel_operator_comment:
            print(f"💬 Комментарий оператора: {cancel_operator_comment}")
        
        # ===== ОТСЛЕЖИВАНИЕ ВРЕМЕНИ ПРИГОТОВЛЕНИЯ =====
        if status and status.upper() == 'COOKINGSTARTED':
            if order_number not in cooking_start_time:
                cooking_start_time[order_number] = time.time()
                print(f"⏱️ Заказ {order_number}: начато приготовление в {time.strftime('%H:%M:%S')}")
                if order_number in cooking_warning_sent:
                    del cooking_warning_sent[order_number]
        
        elif status and status.upper() in ['COOKINGCOMPLETED', 'CLOSED', 'CANCELLED']:
            if order_number in cooking_start_time:
                start = cooking_start_time[order_number]
                elapsed_minutes = (time.time() - start) / 60
                print(f"⏱️ Заказ {order_number}: завершён. Готовился {elapsed_minutes:.1f} минут")
                del cooking_start_time[order_number]
                if order_number in cooking_warning_sent:
                    del cooking_warning_sent[order_number]
        
        # ===== ОТПРАВКА УВЕДОМЛЕНИЙ ТОЛЬКО ОБ ОТМЕНЕ =====
        if status and status.upper() in tracked_statuses:
            status_upper = status.upper()
            status_key = f"{order_number}_{status_upper}"
            
            if status_key in last_status:
                print(f"⏩ Статус '{status}' для заказа {order_number} уже отправлен, пропускаем")
                continue
            
            last_status[status_key] = time.time()
            
            current_time = time.time()
            to_delete = [k for k, v in last_status.items() if current_time - v > 3600]
            for k in to_delete:
                del last_status[k]
            
            status_info = status_mapping.get(status_upper, {'icon': 'ℹ️', 'text': f'ИЗМЕНЕНИЕ СТАТУСА'})
            icon = status_info['icon']
            status_text = status_info['text']
            
            message = f"""{icon} <b>{status_text}</b>

📋 <b>Номер:</b> {order_number}
👤 <b>Клиент:</b> {customer_name}
📞 <b>Телефон:</b> {phone}
🔄 <b>Статус:</b> {status}"""
            
            if comment:
                message += f"\n\n📝 <b>Комментарий:</b> {comment}"
            
            if cancel_reason:
                message += f"\n❌ <b>Причина отмены:</b> {cancel_reason}"
            
            if cancel_operator_comment:
                message += f"\n💬 <b>Комментарий оператора:</b> {cancel_operator_comment}"
            
            if not cancel_reason and not cancel_operator_comment:
                message += f"\n\n❌ <i>Причина отмены не указана</i>"
            
            message += f"\n\n<i>Время: {time.strftime('%H:%M:%S')}</i>"
            
            send_telegram_message(message)
            print(f"📢 Уведомление об отмене отправлено о заказе {order_number}")
    
    return jsonify({"status": "ok"}), 200

@app.route('/')
def home():
    return "🤖 Бот для iiko работает! Отслеживается долгое приготовление."

@app.route('/test_telegram')
def test_telegram():
    send_telegram_message("🧪 <b>Тестовое сообщение!</b>\n\nБот работает и готов принимать вебхуки от iiko.")
    return "Тестовое сообщение отправлено!"

@app.route('/active_cooking')
def active_cooking():
    """Показать текущие заказы в процессе готовки"""
    if not cooking_start_time:
        return "Нет заказов в процессе готовки"
    
    result = []
    for order, start in cooking_start_time.items():
        elapsed = (time.time() - start) / 60
        result.append(f"Заказ {order}: {elapsed:.1f} минут")
    return "<br>".join(result)

if __name__ == '__main__':
    import os
    print("=" * 60)
    print("🚀 БОТ ДЛЯ IIKO ЗАПУЩЕН С АКТИВНЫМ МОНИТОРИНГОМ")
    print("=" * 60)
    print(f"📡 Сервер: http://0.0.0.0:{os.environ.get('PORT', 5000)}")
    print(f"🔗 Вебхук: /webhook (и корневой / тоже принимает POST)")
    print("=" * 60)
    print("📌 Отслеживается только статус CANCELLED")
    print("📌 ДОПОЛНИТЕЛЬНО: каждую минуту проверяем заказы в готовке")
    print("📌 Если готовка >30 минут — приходит предупреждение")
    print("=" * 60)
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
