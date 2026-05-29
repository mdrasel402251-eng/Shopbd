import os
import json
import uuid
import requests
from flask import Flask, request, jsonify, redirect, send_from_directory
from sqlalchemy import create_engine, Column, Integer, String, Float, Text
from sqlalchemy.orm import declarative_base, sessionmaker

# ফ্লাস্ক অ্যাপ এবং ফাইল সার্ভ করার জন্য ফোল্ডার সেটআপ
app = Flask(__name__)
app.secret_key = 'super_secret_key_store'
UPLOAD_FOLDER = 'uploads'
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

# ==========================================
# 1. DATABASE CONFIGURATION (SQLAlchemy)
# ==========================================
DB_FILE = 'database.sqlite'
engine = create_engine(f'sqlite:///{DB_FILE}', echo=False, connect_args={'check_same_thread': False})
Base = declarative_base()
Session = sessionmaker(bind=engine)
db = Session()

class Setting(Base):
    __tablename__ = 'settings'
    name = Column(String(50), primary_key=True)
    val = Column(Text)

class User(Base):
    __tablename__ = 'users'
    id = Column(Integer, primary_key=True, autoincrement=True)
    telegram_id = Column(String(50), unique=True)
    username = Column(String(100))
    first_name = Column(String(100))
    coins = Column(Integer, default=0)
    referrer_id = Column(Integer, default=None)

class Category(Base):
    __tablename__ = 'categories'
    id = Column(Integer, primary_key=True, autoincrement=True)
    name = Column(String(100))
    status = Column(Integer, default=1)

class Product(Base):
    __tablename__ = 'products'
    id = Column(Integer, primary_key=True, autoincrement=True)
    category_id = Column(Integer)
    name = Column(String(255))
    description = Column(Text)
    price = Column(Float)
    coin_price = Column(Integer)
    image_path = Column(Text)
    file_path = Column(Text)
    status = Column(Integer, default=1)

class Order(Base):
    __tablename__ = 'orders'
    id = Column(Integer, primary_key=True, autoincrement=True)
    trx_id = Column(String(100), unique=True)
    user_id = Column(String(50))
    product_id = Column(Integer)
    amount = Column(Float)
    method = Column(String(20))
    status = Column(String(20), default='pending')

# ডাটাবেস টেবিল তৈরি করা
Base.metadata.create_all(engine)

# ==========================================
# 2. AUTO-INSTALLER (Seed Default Settings)
# ==========================================
def initialize_database():
    if not db.query(Setting).first():
        default_settings = [
            Setting(name='bot_token', val='YOUR_BOT_TOKEN_HERE'),
            Setting(name='bot_url', val='https://your-render-app.onrender.com'),
            Setting(name='bot_username', val='YOUR_BOT_USERNAME'),
            Setting(name='nagorik_url', val='https://api.nagorikpay.com/v1'),
            Setting(name='nagorik_key', val='YOUR_NAGORIK_KEY'),
            Setting(name='openrouter_key', val='YOUR_OPENROUTER_KEY'),
            Setting(name='ai_model', val='openai/gpt-4o-mini'),
            Setting(name='ai_prompt', val='You are a polite human support agent. Never mention AI.'),
            Setting(name='ai_enabled', val='0'),
            Setting(name='ref_reward', val='50')
        ]
        db.add_all(default_settings)
        db.commit()
        print("Database initialized with default settings.")

initialize_database()

# ==========================================
# 3. HELPER FUNCTIONS
# ==========================================
def get_setting(key):
    s = db.query(Setting).filter_by(name=key).first()
    return s.val if s else ""

def tg(method, data):
    token = get_setting('bot_token')
    if not token or token == 'YOUR_BOT_TOKEN_HERE':
        return None
    url = f"https://api.telegram.org/bot{token}/{method}"
    try:
        res = requests.post(url, json=data, timeout=10).json()
        return res
    except Exception as e:
        print(f"Telegram API Error: {e}")
        return None

# ==========================================
# 4. APP ROUTES & WEBHOOKS
# ==========================================

# হেলথ চেক রাউট (Render এর জন্য অত্যন্ত জরুরি)
@app.route('/', methods=['GET'])
def index():
    return "✅ System is running perfectly on Render!", 200

# ফাইল ডাউনলোডের রাউট
@app.route('/uploads/<path:filename>')
def download_file(filename):
    return send_from_directory(UPLOAD_FOLDER, filename)

@app.route('/payment/success', methods=['GET'])
def payment_success():
    np_trx = request.args.get('transactionId')
    our_trx = request.args.get('trx_id')
    bot_usr = get_setting('bot_username') or 'OurStore'
    
    base_api = get_setting('nagorik_url').rstrip('/')
    base_api = base_api.replace('/payment/create', '').replace('/payment/verify', '')
    verify_url = f"{base_api}/payment/verify"
    
    headers = {
        'API-KEY': get_setting('nagorik_key').strip(),
        'Content-Type': 'application/json'
    }
    
    try:
        res = requests.post(verify_url, json={'transaction_id': np_trx}, headers=headers, timeout=10).json()
        if res.get('status', '').upper() == 'COMPLETED':
            order = db.query(Order).filter_by(trx_id=our_trx).first()
            if order:
                order.status = 'completed'
                db.commit()
            
            return f"""
            <!DOCTYPE html><html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'>
            <title>Payment Successful</title><style>body{{background:#0f172a;color:#fff;text-align:center;padding-top:20%;font-family:sans-serif;}}</style>
            <script>setTimeout(function(){{ window.location.href = 'tg://resolve?domain={bot_usr}'; }}, 4000);</script>
            </head><body><h1>✅ পেমেন্ট সফল হয়েছে!</h1><p>আপনাকে টেলিগ্রামে ফেরত পাঠানো হচ্ছে...</p></body></html>
            """
    except Exception:
        pass

    return "<h1>❌ পেমেন্ট সম্পন্ন হয়নি বা যাচাই করা যায়নি</h1>"

@app.route('/payment/cancel', methods=['GET'])
def payment_cancel():
    bot_usr = get_setting('bot_username') or 'OurStore'
    return f"""
    <!DOCTYPE html><html><head><meta charset='UTF-8'><meta name='viewport' content='width=device-width, initial-scale=1.0'>
    <title>Payment Cancelled</title><style>body{{background:#0f172a;color:#fff;text-align:center;padding-top:20%;font-family:sans-serif;}}</style>
    </head><body><h1>⚠️ পেমেন্ট বাতিল করা হয়েছে</h1><a href='tg://resolve?domain={bot_usr}' style='color:#00e676;'>বটে ফিরে যান</a></body></html>
    """

@app.route('/webhook/nagorikpay', methods=['POST'])
def nagorikpay_webhook():
    data = request.json
    trx_id = request.args.get('trx_id') or (data.get('metadata', {}).get('trx_id'))
    
    if trx_id and data.get('status', '').upper() == 'COMPLETED':
        order = db.query(Order).filter_by(trx_id=trx_id, status='pending').first()
        if order:
            order.status = 'completed'
            db.commit()
            
            product = db.query(Product).filter_by(id=order.product_id).first()
            file_url = f"{get_setting('bot_url').rstrip('/')}/{product.file_path}"
            
            msg = f"✅ <b>সম্মানিত গ্রাহক, আপনার পেমেন্টটি সফলভাবে গ্রহণ করা হয়েছে!</b>\n\n🛍 <b>প্রোডাক্টের নাম:</b> {product.name}"
            tg('sendMessage', {'chat_id': order.user_id, 'text': msg, 'parse_mode': 'HTML'})
            tg('sendDocument', {'chat_id': order.user_id, 'document': file_url})
            
    return "OK", 200

@app.route('/webhook/telegram', methods=['POST'])
def telegram_webhook():
    update = request.json
    if not update:
        return "OK", 200

    message = update.get('message', {})
    callback_query = update.get('callback_query', {})
    
    chat_id = message.get('chat', {}).get('id') or callback_query.get('message', {}).get('chat', {}).get('id')
    text = message.get('text', '')
    callback_data = callback_query.get('data', '')
    from_user = message.get('from', {}) or callback_query.get('from', {})
    message_id = callback_query.get('message', {}).get('message_id')

    if not chat_id:
        return "OK", 200

    first_name = from_user.get('first_name', 'User')

    # User Registration
    user = db.query(User).filter_by(telegram_id=str(chat_id)).first()
    if not user:
        ref_db_id = None
        if text.startswith('/start ref_'):
            ref_chat_id = text.replace('/start ref_', '')
            ref_user = db.query(User).filter_by(telegram_id=ref_chat_id).first()
            if ref_user:
                ref_db_id = ref_user.id
                reward = int(get_setting('ref_reward') or 50)
                ref_user.coins += reward
                db.commit()
                tg('sendMessage', {'chat_id': ref_chat_id, 'text': f"🎉 <b>অভিনন্দন!</b> আপনার রেফারেল ব্যবহার করে একজন জয়েন করেছেন!", 'parse_mode': 'HTML'})
        
        user = User(telegram_id=str(chat_id), username=from_user.get('username', ''), first_name=first_name, referrer_id=ref_db_id)
        db.add(user)
        db.commit()

    reply_keyboard = {
        'keyboard': [
            [{'text': '🛍 প্রোডাক্ট ব্রাউজ করুন'}, {'text': '💰 আমার ওয়ালেট'}],
            [{'text': '📦 আমার অর্ডারসমূহ'}, {'text': '🎁 রেফারেল ও বোনাস'}],
            [{'text': '🎧 সাপোর্ট চ্যাট'}]
        ],
        'resize_keyboard': True, 'persistent': True
    }

    if text in ['/start', '/menu']:
        welcome = f"আসসালামু আলাইকুম, <b>{first_name}</b>।\nআমাদের স্টোরে স্বাগতম!"
        tg('sendMessage', {'chat_id': chat_id, 'text': welcome, 'parse_mode': 'HTML', 'reply_markup': reply_keyboard})
        return "OK", 200

    if text == '🛍 প্রোডাক্ট ব্রাউজ করুন':
        cats = db.query(Category).filter_by(status=1).all()
        if not cats:
            tg('sendMessage', {'chat_id': chat_id, 'text': "বর্তমানে কোনো ক্যাটাগরি নেই।"})
            return "OK", 200
            
        kb = [[{'text': f"📁 {c.name}", 'callback_data': f"cat_{c.id}"}] for c in cats]
        tg('sendMessage', {'chat_id': chat_id, 'text': "<b>আমাদের ক্যাটাগরিসমূহ:</b>", 'parse_mode': 'HTML', 'reply_markup': {'inline_keyboard': kb}})
        return "OK", 200

    if text == '💰 আমার ওয়ালেট':
        msg = f"💰 <b>আপনার ওয়ালেট</b>\nবর্তমান ব্যালেন্স: <b>{user.coins} Coins</b>"
        tg('sendMessage', {'chat_id': chat_id, 'text': msg, 'parse_mode': 'HTML', 'reply_markup': reply_keyboard})
        return "OK", 200

    if callback_data:
        tg('answerCallbackQuery', {'callback_query_id': callback_query.get('id')})
        
        if callback_data.startswith('cat_'):
            cid = callback_data.split('_')[1]
            prods = db.query(Product).filter_by(category_id=cid, status=1).all()
            if not prods:
                tg('editMessageText', {'chat_id': chat_id, 'message_id': message_id, 'text': "এই ক্যাটাগরিতে কোনো প্রোডাক্ট নেই।"})
            else:
                kb = [[{'text': f"📦 {p.name} - ৳{p.price}", 'callback_data': f"prod_{p.id}"}] for p in prods]
                tg('editMessageText', {'chat_id': chat_id, 'message_id': message_id, 'text': "<b>প্রোডাক্টসমূহ:</b>", 'parse_mode': 'HTML', 'reply_markup': {'inline_keyboard': kb}})

        elif callback_data.startswith('prod_'):
            pid = callback_data.split('_')[1]
            p = db.query(Product).filter_by(id=pid).first()
            if p:
                msg = f"🌟 <b>{p.name}</b>\n\n📝 <b>বিবরণ:</b>\n<i>{p.description}</i>\n\n💰 <b>মূল্য:</b> ৳{p.price}\n🪙 <b>কয়েন মূল্য:</b> {p.coin_price} Coins"
                kb = {'inline_keyboard': [
                    [{'text': '💳 বিকাশ/নগদ দিয়ে ক্রয় করুন', 'callback_data': f'buyn_{p.id}'}],
                    [{'text': '🪙 কয়েন দিয়ে ক্রয় করুন', 'callback_data': f'buyc_{p.id}'}]
                ]}
                tg('deleteMessage', {'chat_id': chat_id, 'message_id': message_id})
                tg('sendMessage', {'chat_id': chat_id, 'text': msg, 'parse_mode': 'HTML', 'reply_markup': kb})

        elif callback_data.startswith('buyn_'):
            pid = callback_data.split('_')[1]
            p = db.query(Product).filter_by(id=pid).first()
            
            if p:
                trx_id = f"TRX_{uuid.uuid4().hex[:10].upper()}"
                new_order = Order(trx_id=trx_id, user_id=str(chat_id), product_id=p.id, amount=p.price, method='nagorikpay')
                db.add(new_order)
                db.commit()

                base_api = get_setting('nagorik_url').rstrip('/').replace('/payment/create', '')
                create_url = f"{base_api}/payment/create"
                bot_url = get_setting('bot_url').rstrip('/')
                
                req_data = {
                    'cus_name': first_name,
                    'cus_email': 'user@gmail.com',
                    'amount': p.price,
                    'success_url': f"{bot_url}/payment/success?trx_id={trx_id}",
                    'cancel_url': f"{bot_url}/payment/cancel",
                    'webhook_url': f"{bot_url}/webhook/nagorikpay?trx_id={trx_id}",
                    'metadata': {'trx_id': trx_id}
                }
                headers = {'API-KEY': get_setting('nagorik_key').strip()}
                
                try:
                    res = requests.post(create_url, json=req_data, headers=headers, timeout=10).json()
                    if 'payment_url' in res:
                        kb = {'inline_keyboard': [
                            [{'text': '🔗 পেমেন্ট করুন (Pay Now)', 'url': res['payment_url']}],
                            [{'text': '✅ পেমেন্ট ভেরিফাই করুন', 'callback_data': f'verify_{trx_id}'}]
                        ]}
                        tg('sendMessage', {'chat_id': chat_id, 'text': f"✅ ইনভয়েস তৈরি হয়েছে!\n<b>অ্যামাউন্ট:</b> ৳{p.price}", 'parse_mode': 'HTML', 'reply_markup': kb})
                except Exception:
                    tg('sendMessage', {'chat_id': chat_id, 'text': "❌ পেমেন্ট গেটওয়েতে সমস্যা দেখা দিয়েছে (Invalid API Key)।"})

        elif callback_data.startswith('verify_'):
            trx_id = callback_data.replace('verify_', '')
            order = db.query(Order).filter_by(trx_id=trx_id).first()
            if order and order.status == 'completed':
                p = db.query(Product).filter_by(id=order.product_id).first()
                tg('deleteMessage', {'chat_id': chat_id, 'message_id': message_id})
                tg('sendMessage', {'chat_id': chat_id, 'text': f"✅ আপনার পেমেন্ট রিসিভ হয়েছে!\n🛍 <b>প্রোডাক্ট:</b> {p.name}"})
                tg('sendDocument', {'chat_id': chat_id, 'document': f"{get_setting('bot_url').rstrip('/')}/{p.file_path}"})
            else:
                tg('answerCallbackQuery', {'callback_query_id': callback_query.get('id'), 'text': "❌ পেমেন্ট এখনো সম্পন্ন হয়নি।", 'show_alert': True})

        return "OK", 200

    return "OK", 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
