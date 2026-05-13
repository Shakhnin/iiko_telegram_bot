import os
import requests
import time
import json
from flask import Flask, request, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

IIKO_API_LOGIN = os.environ.get("IIKO_API_LOGIN", "")
IIKO_ORG_ID = os.environ.get("IIKO_ORG_ID", "")
IIKO_API_URL = os.environ.get("IIKO_API_URL", "https://api-ru.iiko.services/api/1")

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

app = Flask(__name__)

last_status = {}
cooking_start_time = {}
cooking_warning_sent = {}

status_mapping = {'CANCELLED': {'icon': '❌', 'text': 'ЗАКАЗ ОТМЕНЕН'}}
tracked_statuses = ['CANCELLED']

def send_telegram_message(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {"chat_id": TELEGRAM_CHAT_ID, "text": text, "parse_mode": "HTML"}
    try:
        response = requests.post(url, json=payload, timeout=10)
        if response.status_code == 200:
            print("✅ Сообщение отправлено в Telegram")
        else:
            print(f"❌ Ошибка: {response.text}")
    except Exception as e:
        print(f"❌ Ошибка: {e}")

def check_long_cooking():
    print(f"\n⏰ Фоновая проверка: активных заказов в готовке - {len(cooking_start_time)}")
    current_time = time.time()
    for order_number, start_time in list(cooking_start_time.items()):
        elapsed_minutes = (current_time - start_time) / 60
        print(f"   Заказ {order_number}: готовится {elapsed_minutes:.1f} мин")
        if elapsed_minutes > 30 and order_number not in cooking_warning_sent:
            cooking_warning_sent[order_number] = True
            message = f"""⚠️ <b>ДОЛГОЕ ПРИГОТОВЛЕНИЕ!</b>
📋 <b>Номер заказа:</b> {order_number}
⏱️ <b>Время приготовления:</b> {elapsed_minutes:.0f} минут
<i>Время: {time.strftime('%H:%M:%S')}</i>"""
            send_telegram_message(message)

scheduler = BackgroundScheduler()
scheduler.add_job(func=check_long_cooking, trigger="interval", seconds=60)
scheduler.start()
print("🟢 Фоновый мониторинг долгих заказов запущен (проверка каждую минуту)")

@app.route('/', methods=['POST'])
def handle_webhook_root():
    return handle_webhook()

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
        
        print(f"🔍 Заказ {order_number}, статус: {status}")
        
        if status and status.upper() == 'COOKINGSTARTED':
            if order_number not in cooking_start_time:
                cooking_start_time[order_number] = time.time()
                print(f"⏱️ Заказ {order_number}: начато приготовление")
        
        elif status and status.upper() in ['COOKINGCOMPLETED', 'CLOSED', 'CANCELLED']:
            if order_number in cooking_start_time:
                start = cooking_start_time[order_number]
                elapsed = (time.time() - start) / 60
                print(f"⏱️ Заказ {order_number}: завершён за {elapsed:.1f} мин")
                del cooking_start_time[order_number]
        
        if status and status.upper() == 'CANCELLED':
            status_key = f"{order_number}_CANCELLED"
            if status_key in last_status:
                continue
            last_status[status_key] = time.time()
            
            message = f"""❌ <b>ЗАКАЗ ОТМЕНЕН</b>
📋 <b>Номер:</b> {order_number}
👤 <b>Клиент:</b> {customer_name}
📞 <b>Телефон:</b> {phone}"""
            if comment:
                message += f"\n📝 <b>Комментарий:</b> {comment}"
            if cancel_reason:
                message += f"\n❌ <b>Причина отмены:</b> {cancel_reason}"
            if cancel_operator_comment:
                message += f"\n💬 <b>Комментарий оператора:</b> {cancel_operator_comment}"
            message += f"\n<i>Время: {time.strftime('%H:%M:%S')}</i>"
            send_telegram_message(message)
    
    return jsonify({"status": "ok"}), 200

@app.route('/')
def home():
    return "🤖 Бот для iiko работает!"

@app.route('/test_telegram')
def test_telegram():
    send_telegram_message("🧪 Тестовое сообщение! Бот работает.")
    return "OK"

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
