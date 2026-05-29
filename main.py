import os
import re
import uuid
import requests
from flask import Flask, request, jsonify
from sqlalchemy import create_engine, Column, Integer, String, Float, Text
from sqlalchemy.orm import declarative_base, sessionmaker, scoped_session

app = Flask(__name__)

# ==========================================
# 1. RENDER ENVIRONMENT VARIABLES (ড্যাশবোর্ড থেকে আসবে)
# ==========================================
BOT_TOKEN = os.environ.get('BOT_TOKEN', '')
ADMIN_ID = os.environ.get('ADMIN_ID', '')        # আপনার পার্সোনাল টেলিগ্রাম আইডি
BOT_URL = os.environ.get('BOT_URL', '').rstrip('/') # রেন্ডার অ্যাপের লিংক (শেষে / ছাড়া)
NAGORIK_URL = os.environ.get('NAGORIK_URL', 'https://api.nagorikpay.com/v1').rstrip('/')
NAGORIK_KEY = os.environ.get('NAGORIK_KEY', '')
OPENROUTER_KEY = os.environ.get('OPENROUTER_KEY', '')
AI_ENABLED = os.environ.get('AI_ENABLED', '1')    # ১ হলে এআই চালু, ০ হলে বন্ধ
REF_REWARD = int(os.environ.get('REF_REWARD', '50')) # প্রতি রেফারে কত কয়েন

# ==========================================
# 2. DATABASE CONFIGURATION (SQLite)
# ==========================================
DB_FILE = 'database.sqlite'
engine = create_engine(f'sqlite:///{DB_FILE}', echo=False, connect_args={'check_same_thread': False})
Base = declarative_base()
session_factory = sessionmaker(bind=engine)
Session = scoped_session(session_factory)
db = Session()

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
    file_id = Column(Text) # টেলিগ্রাম সার্ভারের সুরক্ষিত ফাইল আইডি
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

Base.metadata.create_all(engine)

# ==========================================
# 3. HELPER FUNCTIONS & WEBHOOK AUTO-SETTER
# ==========================================
admin_states = {}

def tg(method, data):
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        return requests.post(url, json=data, timeout=15).json()
    except:
        return None

# রেন্ডার হোমপেজে ঢুকলে বা অ্যাপ রান হলে স্বয়ংক্রিয়ভাবে Webhook সেট করার জাদুকরী সিস্টেম
@app.route('/', methods=['GET'])
def index():
    if BOT_TOKEN and BOT_URL:
        webhook_target = f"{BOT_URL}/webhook/telegram"
        set_url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook?url={webhook_target}"
        try:
            res = requests.get(set_url, timeout=10).json()
            if res.get('ok'):
                return f"<h1>✅ System is Active & Webhook Auto-Configured Successfully!</h1><p>Target: {webhook_target}</p>", 200
        except Exception as e:
            return f"<h1>⚠️ Webhook Configuration Error: {str(e)}</h1>", 500
    return "<h1>✅ System is Running! Please configure Render Env Variables.</h1>", 200

# ==========================================
# 4. NAGORIKPAY GATEWAY ROUTES (PHP লজিক অনুযায়ী)
# ==========================================
def get_nagorik_endpoints():
    base = NAGORIK_URL.replace('/payment/create', '').replace('/payment/verify', '')
    return f"{base}/payment/create", f"{base}/payment/verify"

@app.route('/payment/success', methods=['GET'])
def payment_success():
    np_trx = request.args.get('transactionId')
    our_trx = request.args.get('trx_id')
    
    _, verify_url = get_nagorik_endpoints()
    headers = {'API-KEY': NAGORIK_KEY, 'Content-Type': 'application/json'}
    
    try:
        res = requests.post(verify_url, json={'transaction_id': np_trx}, headers=headers, timeout=10).json()
        if res.get('status', '').upper() == 'COMPLETED':
            order = db.query(Order).filter_by(trx_id=our_trx).first()
            if order:
                order.status = 'completed'
                db.commit()
            return "<html><body style='background:#0f172a;color:#00e676;text-align:center;padding-top:20%;font-family:sans-serif;'><h1>✅ পেমেন্ট সফল হয়েছে!</h1><p style='color:#fff;'>টেলিগ্রাম বটে ফিরে যান, আপনার ফাইলটি পাঠানো হয়েছে।</p></body></html>", 200
    except:
        pass
    return "<h1>❌ পেমেন্ট যাচাই করা যায়নি বা ব্যর্থ হয়েছে।</h1>", 400

@app.route('/payment/cancel', methods=['GET'])
def payment_cancel():
    return "<html><body style='background:#0f172a;color:#ff5500;text-align:center;padding-top:20%;font-family:sans-serif;'><h1>⚠️ পেমেন্ট বাতিল করা হয়েছে!</h1></body></html>", 200

@app.route('/webhook/nagorikpay', methods=['POST'])
def nagorikpay_webhook():
    data = request.json or {}
    trx_id = request.args.get('trx_id') or data.get('metadata', {}).get('trx_id')
    
    if trx_id and data.get('status', '').upper() == 'COMPLETED':
        order = db.query(Order).filter_by(trx_id=trx_id, status='pending').first()
        if order:
            order.status = 'completed'
            db.commit()
            
            product = db.query(Product).filter_by(id=order.product_id).first()
            msg = f"✅ <b>সম্মানিত গ্রাহক, আপনার পেমেন্টটি সফলভাবে গ্রহণ করা হয়েছে!</b>\n\n🛍 <b>প্রোডাক্টের নাম:</b> {product.name}\n\n<i>আপনার ফাইলটি নিচে প্রদান করা হলো। আমাদের সেবা গ্রহণ করার জন্য আপনাকে অসংখ্য ধন্যবাদ।</i>"
            tg('sendMessage', {'chat_id': order.user_id, 'text': msg, 'parse_mode': 'HTML'})
            tg('sendDocument', {'chat_id': order.user_id, 'document': product.file_id})
    return "OK", 200

# ==========================================
# 5. TELEGRAM WEBHOOK CONTROLLER
# ==========================================
@app.route('/webhook/telegram', methods=['POST'])
def telegram_webhook():
    update = request.json or {}
    if not update: return "OK", 200

    message = update.get('message', {})
    callback_query = update.get('callback_query', {})
    
    chat_id = str(message.get('chat', {}).get('id') or callback_query.get('message', {}).get('chat', {}).get('id'))
    text = message.get('text', '')
    callback_data = callback_query.get('data', '')
    from_user = message.get('from', {}) or callback_query.get('from', {})
    message_id = callback_query.get('message', {}).get('message_id')
    first_name = from_user.get('first_name', 'User')

    # ইউজার রেজিস্ট্রেশন ও রেফারেল ট্র্যাকিং (PHP লজিক)
    user = db.query(User).filter_by(telegram_id=chat_id).first()
    if not user:
        ref_db_id = None
        if text.startswith('/start ref_'):
            ref_chat_id = text.replace('/start ref_', '')
            ref_user = db.query(User).filter_by(telegram_id=ref_chat_id).first()
            if ref_user:
                ref_db_id = ref_user.id
                ref_user.coins += REF_REWARD
                db.commit()
                ref_msg = f"🎉 <b>অভিনন্দন!</b>\nআপনার রেফারেল লিংক ব্যবহার করে <b>{first_name}</b> জয়েন করেছেন। আপনি <b>{REF_REWARD} কয়েন</b> বোনাস অর্জন করেছেন!"
                tg('sendMessage', {'chat_id': ref_chat_id, 'text': ref_msg, 'parse_mode': 'HTML'})
        
        user = User(telegram_id=chat_id, username=from_user.get('username', ''), first_name=first_name, referrer_id=ref_db_id)
        db.add(user)
        db.commit()

    # ----------------------------------------
    # 🔴 IN-BOT ADMIN PANEL (সম্পূর্ণ কন্ট্রোল)
    # ----------------------------------------
    if chat_id == ADMIN_ID:
        if text == '/admin':
            admin_states.pop(chat_id, None)
            kb = {'inline_keyboard': [
                [{'text': '📁 নতুন ক্যাটাগরি যোগ করুন', 'callback_data': 'adm_add_cat'}],
                [{'text': '📦 নতুন প্রোডাক্ট যোগ করুন', 'callback_data': 'adm_add_prod'}],
                [{'text': '📊 ইউজার ও সেলস রিপোর্ট', 'callback_data': 'adm_stats'}]
            ]}
            tg('sendMessage', {'chat_id': chat_id, 'text': "👑 <b>Admin Control Panel</b>\nবটের সবকিছু এখান থেকেই পরিচালনা করুন:", 'parse_mode': 'HTML', 'reply_markup': kb})
            return "OK", 200

        if chat_id in admin_states:
            state = admin_states[chat_id]['step']
            if state == 'wait_cat_name' and text:
                db.add(Category(name=text))
                db.commit()
                tg('sendMessage', {'chat_id': chat_id, 'text': f"✅ ক্যাটাগরি '{text}' সফলভাবে তৈরি হয়েছে!"})
                del admin_states[chat_id]
                return "OK", 200
            elif state == 'wait_prod_name' and text:
                admin_states[chat_id]['data']['name'] = text
                admin_states[chat_id]['step'] = 'wait_prod_desc'
                tg('sendMessage', {'chat_id': chat_id, 'text': "২. প্রোডাক্টের বিবরণ (Description) লিখুন:"})
                return "OK", 200
            elif state == 'wait_prod_desc' and text:
                admin_states[chat_id]['data']['desc'] = text
                admin_states[chat_id]['step'] = 'wait_prod_price'
                tg('sendMessage', {'chat_id': chat_id, 'text': "৩. প্রোডাক্টের মূল্য (টাকা) লিখুন:"})
                return "OK", 200
            elif state == 'wait_prod_price' and text:
                admin_states[chat_id]['data']['price'] = float(text)
                admin_states[chat_id]['step'] = 'wait_prod_coin'
                tg('sendMessage', {'chat_id': chat_id, 'text': "৪. প্রোডাক্টের কয়েন মূল্য (Coins) লিখুন:"})
                return "OK", 200
            elif state == 'wait_prod_coin' and text:
                admin_states[chat_id]['data']['coin'] = int(text)
                admin_states[chat_id]['step'] = 'wait_prod_file'
                tg('sendMessage', {'chat_id': chat_id, 'text': "৫. এবার আপনার আসল প্রোডাক্ট ফাইলটি (ZIP/PDF/Image) এখানে আপলোড করুন। বট অটোমেটিক এর ফাইল আইডি সুরক্ষিত করে নেবে:"})
                return "OK", 200
            elif state == 'wait_prod_file' and 'document' in message:
                f_id = message['document']['file_id']
                d = admin_states[chat_id]['data']
                db.add(Product(category_id=d['cat_id'], name=d['name'], description=d['desc'], price=d['price'], coin_price=d['coin'], file_id=f_id))
                db.commit()
                tg('sendMessage', {'chat_id': chat_id, 'text': f"✅ প্রোডাক্ট <b>{d['name']}</b> ফাইল আইডিসহ সফলভাবে স্টোরে সেভ হয়েছে!", 'parse_mode': 'HTML'})
                del admin_states[chat_id]
                return "OK", 200

    # ----------------------------------------
    # 🔵 CALLBACK ACTIONS (User & Admin)
    # ----------------------------------------
    if callback_data:
        tg('answerCallbackQuery', {'callback_query_id': callback_query.get('id')})
        
        if callback_data == 'adm_stats' and chat_id == ADMIN_ID:
            total_u = db.query(User).count()
            total_o = db.query(Order).count()
            tg('sendMessage', {'chat_id': chat_id, 'text': f"📊 <b>লাইভ রিপোর্ট:</b>\n\nমোট গ্রাহক: {total_u} জন\nমোট সফল/পেন্ডিং অর্ডার: {total_o} টি", 'parse_mode': 'HTML'})
        elif callback_data == 'adm_add_cat' and chat_id == ADMIN_ID:
            admin_states[chat_id] = {'step': 'wait_cat_name'}
            tg('sendMessage', {'chat_id': chat_id, 'text': "নতুন ক্যাটাগরির নাম লিখে পাঠান:"})
        elif callback_data == 'adm_add_prod' and chat_id == ADMIN_ID:
            cats = db.query(Category).filter_by(status=1).all()
            if not cats: tg('sendMessage', {'chat_id': chat_id, 'text': "কোনো ক্যাটাগরি নেই, আগে ক্যাটাগরি বানান!"})
            else:
                kb = [[{'text': c.name, 'callback_data': f'adm_sel_cat_{c.id}'}] for c in cats]
                tg('sendMessage', {'chat_id': chat_id, 'text': "প্রোডাক্টের জন্য ক্যাটাগরি সিলেক্ট করুন:", 'reply_markup': {'inline_keyboard': kb}})
        elif callback_data.startswith('adm_sel_cat_') and chat_id == ADMIN_ID:
            cid = callback_data.split('_')[3]
            admin_states[chat_id] = {'step': 'wait_prod_name', 'data': {'cat_id': cid}}
            tg('sendMessage', {'chat_id': chat_id, 'text': "১. প্রোডাক্টের নাম লিখে পাঠান:"})

        # --- গ্রাহক বাটন অ্যাকশন ---
        elif callback_data.startswith('cat_'):
            cid = callback_data.split('_')[1]
            prods = db.query(Product).filter_by(category_id=cid, status=1).all()
            kb = [[{'text': f"📦 {p.name} - ৳{p.price}", 'callback_data': f"prod_{p.id}"}] for p in prods]
            tg('editMessageText', {'chat_id': chat_id, 'message_id': message_id, 'text': "<b>অ্যাভেইলেবল প্রোডাক্টসমূহ:</b>\nবিস্তারিত দেখতে নির্দিষ্ট প্রোডাক্ট নির্বাচন করুন:", 'parse_mode': 'HTML', 'reply_markup': {'inline_keyboard': kb}})
        elif callback_data.startswith('prod_'):
            p = db.query(Product).filter_by(id=callback_data.split('_')[1]).first()
            msg = f"🌟 <b>{p.name}</b>\n\n📝 <b>বিস্তারিত বিবরণ:</b>\n<i>{p.description}</i>\n\n💰 <b>মূল্য:</b> ৳{p.price}\n🪙 <b>কয়েন মূল্য:</b> {p.coin_price} Coins"
            kb = {'inline_keyboard': [
                [{'text': '💳 বিকাশ দিয়ে ক্রয় করুন (Auto)', 'callback_data': f'buyn_{p.id}'}], # শুধু বিকাশ ভিজ্যুয়াল নাম রাখা হলো
                [{'text': '🪙 কয়েন দিয়ে ক্রয় করুন', 'callback_data': f'buyc_{p.id}'}],
                [{'text': '🔙 ক্যাটাগরিতে ফিরে যান', 'callback_data': f'cat_{p.category_id}'}]
            ]}
            tg('sendMessage', {'chat_id': chat_id, 'text': msg, 'parse_mode': 'HTML', 'reply_markup': kb})
        
        elif callback_data.startswith('buyn_'):
            p = db.query(Product).filter_by(id=callback_data.split('_')[1]).first()
            trx_id = f"TRX_{uuid.uuid4().hex[:10].upper()}"
            db.add(Order(trx_id=trx_id, user_id=chat_id, product_id=p.id, amount=p.price, method='nagorikpay'))
            db.commit()
            
            create_url, _ = get_nagorik_endpoints()
            req_payload = {
                'cus_name': first_name if first_name.isalnum() else 'Customer',
                'cus_email': 'user@gmail.com',
                'amount': p.price,
                'success_url': f"{BOT_URL}/payment/success?trx_id={trx_id}",
                'cancel_url': f"{BOT_URL}/payment/cancel",
                'webhook_url': f"{BOT_URL}/webhook/nagorikpay?trx_id={trx_id}",
                'metadata': {'trx_id': trx_id}
            }
            try:
                res = requests.post(create_url, json=req_payload, headers={'API-KEY': NAGORIK_KEY}, timeout=10).json()
                if 'payment_url' in res:
                    kb = {'inline_keyboard': [
                        [{'text': '🔗 বিকাশ পেমেন্ট লিংক (Pay Now)', 'url': res['payment_url']}],
                        [{'text': '✅ পেমেন্ট ভেরিফাই করুন', 'callback_data': f'verify_{trx_id}'}]
                    ]}
                    tg('sendMessage', {'chat_id': chat_id, 'text': f"✅ <b>আপনার ইনভয়েস সফলভাবে তৈরি হয়েছে!</b>\n\n<b>অ্যামাউন্ট:</b> ৳{p.price}\n\n⚠️ <i>পেমেন্ট সম্পন্ন করার পর নিচের '✅ পেমেন্ট ভেরিফাই করুন' বাটনে ক্লিক করুন।</i>", 'parse_mode': 'HTML', 'reply_markup': kb})
            except:
                tg('sendMessage', {'chat_id': chat_id, 'text': "❌ পেমেন্ট গেটওয়েতে সাময়িক সংযোগ সমস্যা হয়েছে।"})
        
        elif callback_data.startswith('verify_'):
            trx_id = callback_data.replace('verify_', '')
            order = db.query(Order).filter_by(trx_id=trx_id).first()
            if order and order.status == 'completed':
                p = db.query(Product).filter_by(id=order.product_id).first()
                tg('deleteMessage', {'chat_id': chat_id, 'message_id': message_id})
                tg('sendMessage', {'chat_id': chat_id, 'text': f"✅ <b>সম্মানিত গ্রাহক, আপনার পেমেন্টটি সফলভাবে রিসিভ হয়েছে!</b>\n🛍 <b>প্রোডাক্ট:</b> {p.name}", 'parse_mode': 'HTML'})
                tg('sendDocument', {'chat_id': chat_id, 'document': p.file_id})
            else:
                tg('answerCallbackQuery', {'callback_query_id': callback_query.get('id'), 'text': "❌ পেমেন্ট এখনো সম্পন্ন হয়নি বা পেন্ডিং আছে।", 'show_alert': True})
        
        elif callback_data.startswith('buyc_'):
            p = db.query(Product).filter_by(id=callback_data.split('_')[1]).first()
            if user.coins >= p.coin_price:
                user.coins -= p.coin_price
                db.add(Order(trx_id=f"C_{uuid.uuid4().hex[:8].upper()}", user_id=chat_id, product_id=p.id, amount=p.coin_price, method='coins', status='completed'))
                db.commit()
                tg('sendMessage', {'chat_id': chat_id, 'text': f"✅ <b>কয়েন পেমেন্ট সফলভাবে সম্পন্ন হয়েছে!</b>\n🛍 <b>প্রোডাক্ট:</b> {p.name}", 'parse_mode': 'HTML'})
                tg('sendDocument', {'chat_id': chat_id, 'document': p.file_id})
            else:
                tg('answerCallbackQuery', {'callback_query_id': callback_query.get('id'), 'text': "❌ দুঃখিত, আপনার ওয়ালেটে পর্যাপ্ত কয়েন নেই।", 'show_alert': True})
        return "OK", 200

    # ----------------------------------------
    # 🟢 REGULAR USER MAIN MENU (PHP মেনু ভিত্তিক)
    # ----------------------------------------
    reply_keyboard = {'keyboard': [
        [{'text': '🛍 প্রোডাক্ট ব্রাউজ করুন'}, {'text': '💰 আমার ওয়ালেট'}],
        [{'text': '📦 আমার অর্ডারসমূহ'}, {'text': '🎁 রেফারেল ও বোনাস'}],
        [{'text': '🎧 সাপোর্ট চ্যাট'}]
    ], 'resize_keyboard': True, 'persistent': True}

    if text in ['/start', '/menu']:
        welcome = f"আসসালামু আলাইকুম, <b>{first_name}</b>।\nআমাদের স্টোরে আপনাকে স্বাগতম।\n\nঅনুগ্রহ করে নিচের মেনু থেকে অপশন নির্বাচন করুন:"
        tg('sendMessage', {'chat_id': chat_id, 'text': welcome, 'parse_mode': 'HTML', 'reply_markup': reply_keyboard})
        return "OK", 200

    if text == '🛍 প্রোডাক্ট ব্রাউজ করুন':
        cats = db.query(Category).filter_by(status=1).all()
        kb = [[{'text': f"📁 {c.name}", 'callback_data': f"cat_{c.id}"}] for c in cats]
        tg('sendMessage', {'chat_id': chat_id, 'text': "<b>আমাদের ক্যাটাগরিসমূহ:</b>", 'parse_mode': 'HTML', 'reply_markup': {'inline_keyboard': kb}})
        return "OK", 200

    if text == '💰 আমার ওয়ালেট':
        tg('sendMessage', {'chat_id': chat_id, 'text': f"💰 <b>আপনার ওয়ালেট প্রোফাইল</b>\n\nআপনার বর্তমান ব্যালেন্স: <b>{user.coins} Coins</b>", 'parse_mode': 'HTML'})
        return "OK", 200

    if text == '📦 আমার অর্ডারসমূহ':
        orders = db.query(Order).filter_by(user_id=chat_id).order_by(Order.id.desc()).limit(5).all()
        if not orders:
            msg = "📦 <b>আপনার কোনো পূর্ববর্তী অর্ডার পাওয়া যায়নি।</b>"
        else:
            msg = "📦 <b>আপনার সর্বশেষ ৫টি অর্ডারের তালিকা:</b>\n\n"
            for o in orders:
                p = db.query(Product).filter_by(id=o.product_id).first()
                p_name = p.name if p else 'Unknown Product'
                status = '✅ সম্পন্ন হয়েছে' if o.status == 'completed' else '⏳ পেন্ডিং অবস্থায় আছে'
                msg += f"🔹 <b>{p_name}</b>\nমেথড: {o.method.upper()} | স্ট্যাটাস: {status}\n\n"
        tg('sendMessage', {'chat_id': chat_id, 'text': msg, 'parse_mode': 'HTML'})
        return "OK", 200

    if text == '🎁 রেফারেল ও বোনাস':
        bot_info = tg('getMe', {})
        bot_usr = bot_info.get('result', {}).get('username', 'Bot')
        ref_link = f"https://t.me/{bot_usr}?start=ref_{chat_id}"
        msg = f"🎁 <b>রেফারেল ও রিওয়ার্ড প্রোগ্রাম</b>\n\nপ্রতিটি সফল রেফারেলের জন্য অর্জন করুন <b>{REF_REWARD} কয়েন!</b>\n\n<b>আপনার ইউনিক রেফারেল লিংক:</b>\n<code>{ref_link}</code>"
        tg('sendMessage', {'chat_id': chat_id, 'text': msg, 'parse_mode': 'HTML'})
        return "OK", 200

    if text == '🎧 সাপোর্ট চ্যাট':
        tg('sendMessage', {'chat_id': chat_id, 'text': "🎧 <b>সাপোর্ট সেন্টার</b>\n\nযেকোনো বিষয়ে সহায়তা পেতে সরাসরি এখানে আপনার মেসেজটি টাইপ করুন। আমি ইয়াসমিন, আপনার সেবায় নিয়োজিত আছি।", 'parse_mode': 'HTML'})
        return "OK", 200

    # ----------------------------------------
    # 🤖 AI CHAT INTEGRATION & [BUY_ID_X] PARSER
    # ----------------------------------------
    menu_commands = ['🛍 প্রোডাক্ট ব্রাউজ করুন', '💰 আমার ওয়ালেট', '📦 আমার অর্ডারসমূহ', '🎁 রেফারেল ও বোনাস', '🎧 সাপোর্ট চ্যাট']
    if text and not text.startswith('/') and text not in menu_commands and AI_ENABLED == '1' and OPENROUTER_KEY:
        tg('sendChatAction', {'chat_id': chat_id, 'action': 'typing'})
        
        products = db.query(Product).filter_by(status=1).limit(20).all()
        db_products = "".join([f"ID: {p.id} | Product: {p.name} | Price: ৳{p.price}\n" for p in products])
        
        enhanced_prompt = f"You are Yesmin (ইয়াসমিন), a real human girl working as a professional customer support representative.\nSTRICT RULES:\n1. YOU ARE NOT AN AI. Never mention AI/Bot.\n2. Chat like a polite Bengali support girl. Use natural Bengali. Respectfully use 'bhaiya' or 'apni'.\n3. DO NOT use markdown format (*, #). \n4. If someone asks about hosting, say: 'bhaiya hosting nite chaile chaihost.com theke nite paren, eta best. kivabe niben ei video ta dekhte paren: https://youtu.be/ZYL-3smG4_Q?t=69&si=3HOYpYc1GRutmvJc'\n5. Sell our products. List:\n{db_products}\n6. CRITICAL: If they want to buy, you MUST include this exact tag: [BUY_ID_X] (X is product ID)."
        
        try:
            res = requests.post("https://openrouter.ai/api/v1/chat/completions", json={
                'model': 'openai/gpt-4o-mini',
                'messages': [{'role': 'system', 'content': enhanced_prompt}, {'role': 'user', 'content': text}]
            }, headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": application/json}, timeout=15).json()
            
            reply = res['choices'][0]['message']['content']
            reply = reply.replace('**', '').replace('*', '')
            
            # [BUY_ID_X] ট্যাগ ডিটেকশন লজিক
            match = re.search(r'\[BUY_ID_(\d+)\]', reply)
            if match:
                pid = match.group(1)
                reply = reply.replace(match.group(0), '').strip()
                if reply: tg('sendMessage', {'chat_id': chat_id, 'text': reply})
                
                # অটো প্রোডাক্ট কার্ড পুশ
                p = db.query(Product).filter_by(id=pid).first()
                if p:
                    msg = f"🌟 <b>{p.name}</b>\n\n📝 <b>বিস্তারিত বিবরণ:</b>\n<i>{p.description}</i>\n\n💰 <b>মূল্য:</b> ৳{p.price}\n🪙 <b>কয়েন মূল্য:</b> {p.coin_price} Coins"
                    kb = {'inline_keyboard': [
                        [{'text': '💳 বিকাশ দিয়ে ক্রয় করুন (Auto)', 'callback_data': f'buyn_{p.id}'}],
                        [{'text': '🪙 কয়েন দিয়ে ক্রয় করুন', 'callback_data': f'buyc_{p.id}'}]
                    ]}
                    tg('sendMessage', {'chat_id': chat_id, 'text': msg, 'parse_mode': 'HTML', 'reply_markup': kb})
            else:
                tg('sendMessage', {'chat_id': chat_id, 'text': reply})
        except:
            tg('sendMessage', {'chat_id': chat_id, 'text': "bhaiya ektu pore sms den, net ektu prb korche amr ekhne"})

    return "OK", 200

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
