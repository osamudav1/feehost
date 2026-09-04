
import os, re, time, secrets, sqlite3, json
from functools import wraps
from flask import Flask, request, redirect, session, url_for, flash, jsonify, render_template_string, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

APP = 'RT777'
BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, 'rt777.sqlite3')
UPLOADS = os.path.join(BASE, 'rt777_uploads')
AUDIO_UPLOADS = os.path.join(BASE, 'rt777_audio')
os.makedirs(UPLOADS, exist_ok=True)
os.makedirs(AUDIO_UPLOADS, exist_ok=True)
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'CHANGE_THIS_SECRET_KEY')
app.config['MAX_CONTENT_LENGTH'] = 2 * 1024 * 1024
ADMIN_USER = os.environ.get('ADMIN_USERNAME', 'admin1')
ADMIN_PASS = os.environ.get('ADMIN_PASSWORD', 'change-me')
CARDS = {'A':1,'2':2,'3':3,'4':4,'5':5,'6':6,'7':7,'8':8,'9':9,'10':10,'J':11,'Q':12,'K':13}
ALLOWED = {'png','jpg','jpeg','webp','gif'}
AUDIO_ALLOWED = {'mp3','wav','ogg'}


def now(): return time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())
def db():
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    return c

def init_db():
    c=db()
    c.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id TEXT UNIQUE,username TEXT UNIQUE,password_hash TEXT,balance INTEGER NOT NULL DEFAULT 500,status TEXT NOT NULL DEFAULT 'active',created_at TEXT);
    CREATE TABLE IF NOT EXISTS rooms(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT UNIQUE,active INTEGER DEFAULT 1,created_at TEXT);
    CREATE TABLE IF NOT EXISTS room_players(room_id INTEGER,user_id INTEGER,joined_at TEXT,last_seen REAL,PRIMARY KEY(room_id,user_id));
    CREATE TABLE IF NOT EXISTS rounds(id INTEGER PRIMARY KEY AUTOINCREMENT,room_id INTEGER,round_no INTEGER,started_at REAL,tiger_card TEXT,dragon_card TEXT,result TEXT,status TEXT DEFAULT 'open',admin_overridden INTEGER DEFAULT 0,UNIQUE(room_id,round_no));
    CREATE TABLE IF NOT EXISTS bets(id INTEGER PRIMARY KEY AUTOINCREMENT,round_id INTEGER,user_id INTEGER,side TEXT,amount INTEGER,status TEXT DEFAULT 'pending',created_at TEXT);
    CREATE TABLE IF NOT EXISTS transactions(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,type TEXT,amount INTEGER,before_balance INTEGER,after_balance INTEGER,description TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS cards(id INTEGER PRIMARY KEY AUTOINCREMENT,side TEXT UNIQUE,card_name TEXT,card_value INTEGER,image_path TEXT,active INTEGER DEFAULT 1,updated_at TEXT);
    CREATE TABLE IF NOT EXISTS settings(id INTEGER PRIMARY KEY CHECK(id=1),site_name TEXT DEFAULT 'RT777',logo_path TEXT,maintenance INTEGER DEFAULT 0);
    CREATE TABLE IF NOT EXISTS admin_logs(id INTEGER PRIMARY KEY AUTOINCREMENT,admin TEXT,action TEXT,user_id TEXT,details TEXT,created_at TEXT);
    CREATE TABLE IF NOT EXISTS audio_files(id INTEGER PRIMARY KEY AUTOINCREMENT,event_type TEXT UNIQUE,file_path TEXT,active INTEGER DEFAULT 1,updated_at TEXT);
    ''')
    # Repair older databases used by previous versions.
    for table,col,typ in [
        ('users','user_id','TEXT'),('users','balance','INTEGER NOT NULL DEFAULT 500'),('users','status',"TEXT NOT NULL DEFAULT 'active'"),
        ('rounds','room_id','INTEGER'),('rounds','round_no','INTEGER'),('rounds','started_at','REAL'),('rounds','tiger_card','TEXT'),('rounds','dragon_card','TEXT'),('rounds','result','TEXT'),('rounds','status',"TEXT DEFAULT 'open'"),('rounds','admin_overridden','INTEGER DEFAULT 0')]:
        cols=[x['name'] for x in c.execute('PRAGMA table_info('+table+')').fetchall()]
        if col not in cols: c.execute('ALTER TABLE '+table+' ADD COLUMN '+col+' '+typ)
    c.execute("INSERT OR IGNORE INTO settings(id,site_name,logo_path,maintenance) VALUES(1,'RT777',NULL,0)")
    for name in ('Table 1','Table 2'):
        c.execute('INSERT OR IGNORE INTO rooms(name,active,created_at) VALUES(?,1,?)',(name,now()))
    for side,card in (('tiger','A'),('dragon','K')):
        c.execute('INSERT OR IGNORE INTO cards(side,card_name,card_value,active,updated_at) VALUES(?,?,?,?,?)',(side,card,CARDS[card],1,now()))
    # Initialize audio settings
    for event in ['bet_click', 'win', 'lose', 'draw', 'bet_close']:
        c.execute('INSERT OR IGNORE INTO audio_files(event_type,active,updated_at) VALUES(?,1,?)',(event,now()))
    c.commit(); c.close()
init_db()


def svg(name,size=20):
    p={
      'home':'<path d="m3 11 9-8 9 8"/><path d="M5 10v10h14V10"/><path d="M9 20v-6h6v6"/>',
      'user':'<circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/>',
      'wallet':'<path d="M3 7h18v12H3z"/><path d="M3 7l2-4h14l2 4"/><path d="M16 13h5"/>',
      'game':'<rect x="3" y="5" width="18" height="14" rx="3"/><path d="M8 12h5M10.5 9.5v5M17 10h.1M19 13h.1"/>',
      'history':'<path d="M4 5v5h5"/><path d="M5 10a8 8 0 1 1 2 7"/><path d="M12 8v5l3 2"/>',
      'logout':'<path d="M10 17l5-5-5-5M15 12H3M21 3v18"/>',
      'settings':'<circle cx="12" cy="12" r="3"/><path d="M19 15l1 1-2 3-2-1a8 8 0 0 1-2 1v2h-4v-2a8 8 0 0 1-2-1l-2 1-2-3 1-1a8 8 0 0 1 0-2l-1-1 2-3 2 1a8 8 0 0 1 2-1V7h4v2a8 8 0 0 1 2 1l2-1 2 3-1 1a8 8 0 0 1 0 2Z"/>',
      'plus':'<path d="M12 5v14M5 12h14"/>','minus':'<path d="M5 12h14"/>','card':'<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 9h18"/>',
      'volume':'<path d="M11 5L6 9H2v6h4l5 4V5z"/><path d="M19.07 4.93a10 10 0 0 1 0 14.14"/><path d="M15.54 8.46a5 5 0 0 1 0 7.07"/>'}
    return f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">{p.get(name,p["game"])}</svg>'

BASE = '''<!doctype html><html lang="my"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{{title}} · {{site}}</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;800&family=Noto+Sans+Myanmar:wght@400;500;600;700&family=Orbitron:wght@600;800&display=swap');
:root{--bg:#070807;--p:#121612;--g:#f3c64e;--g2:#ffe48a;--m:#9da399;--line:#4b3c1b}*{box-sizing:border-box}html,body{margin:0;background:radial-gradient(circle at 15% 0,#292317,#090b09 42%,#050605);color:#f7f5ed;font-family:Inter,"Noto Sans Myanmar",sans-serif}a{text-decoration:none;color:inherit}.top{height:68px;display:flex;align-items:center;justify-content:space-between;padding:0 18px;background:#090b09ee;border-bottom:1px solid var(--line);position:sticky;top:0;z-index:50}.brand{display:flex;align-items:center;gap:10px;font-weight:800}.logo{width:42px;height:42px;border-radius:12px;display:grid;place-items:center;background:linear-gradient(145deg,#ffe17a,#a66c11);color:#15120a;font:800 16px Orbitron}.brand img{width:42px;height:42px;object-fit:contain;border-radius:12px}.actions{display:flex;align-items:center;gap:7px}.pill{padding:9px 13px;border:1px solid var(--line);border-radius:999px;background:#17150d;color:var(--g2);font-weight:800}.ib{width:42px;height:42px;border-radius:12px;border:1px solid var(--line);background:#11150f;color:var(--g);display:grid;place-items:center}.page{width:min(1120px,calc(100% - 20px));margin:22px auto 45px}.hero,.card{background:linear-gradient(145deg,#181c17,#0d100d);border:1px solid var(--line);border-radius:20px;box-shadow:0 18px 55px #0008}.hero{padding:28px}.card{padding:18px}.k{font:600 11px Orbitron;color:var(--g);letter-spacing:2px}.sub,.muted{color:var(--m);line-height:1.7}h1{font-size:clamp(28px,5vw,50px);margin:8px 0}h2,h3{margin:6px 0 10px}.grid{display:grid;gap:15px}.g2{grid-template-columns:repeat(2,minmax(0,1fr))}.g3{grid-template-columns:repeat(3,minmax(0,1fr))}.g4{grid-template-columns:repeat(4,minmax(0,1fr))}.btn{min-height:43px;border-radius:13px;border:0;padding:10px 15px;font-weight:800;display:inline-flex;align-items:center;justify-content:center;gap:7px}.gold{background:linear-gradient(135deg,#ffe17b,#c78918);color:#17120a}.dark{background:#121712;color:#f7f5ec;border:1px solid var(--line)}.red{background:#321417;color:#ffb5b9;border:1px solid #673039}.input{width:100%;height:46px;background:#0a0d0a;color:#fff;border:1px solid var(--line);border-radius:12px;padding:0 12px}.field{margin:14px 0}.form{max-width:520px;margin:45px auto}.flash{padding:12px 14px;border-radius:12px;margin-bottom:12px;background:#291f0d;border:1px solid #5a4519;color:#ffe49a}.flash.error{background:#2a1215;border-color:#69303a;color:#ffc0c4}.gamecard{min-height:250px;display:flex;flex-direction:column;justify-content:space-between}.art{display:flex;align-items:center;justify-content:center;gap:22px;font-size:45px}.mini{width:62px;height:82px;background:#f5f2e8;color:#151611;border-radius:9px;display:grid;place-items:center;font:800 29px Georgia;box-shadow:0 8px 20px #000}.nav2{display:flex;gap:8px;overflow:auto;margin-bottom:16px}.nav2 .btn{white-space:nowrap}.tw{overflow:auto;border:1px solid var(--line);border-radius:14px}table{width:100%;border-collapse:collapse;min-width:680px}th,td{padding:11px;border-bottom:1px solid #252923;font-size:13px;text-align:left}th{color:var(--g);background:#121510}.stat .v{font-size:26px;color:var(--g2);font-weight:800}@media(max-width:760px){.g2,.g3,.g4{grid-template-columns:1fr}.page{width:calc(100% - 12px);margin-top:12px}.hero{padding:20px}.top{padding:0 9px}.brand>span{display:none}}
</style></head><body><header class="top"><a class="brand" href="/home">{{logo|safe}}<span>{{site}}</span></a><div class="actions">{% if session.get('uid') %}<span class="pill">Credits {{session.get('balance',0)|int}}</span><a class="ib" href="/profile">{{iu|safe}}</a><a class="ib" href="/logout">{{io|safe}}</a>{% elif session.get('admin') %}<a class="ib" href="/admin">{{iset|safe}}</a><a class="ib" href="/admin/logout">{{io|safe}}</a>{% endif %}</div></header><main class="page">{% for cat,msg in get_flashed_messages(with_categories=true) %}<div class="flash {{'error' if cat=='error' else ''}}">{{msg}}</div>{% endfor %}{{body|safe}}</main></body></html>'''

def page(title, body):
    c=db();s=c.execute('SELECT * FROM settings WHERE id=1').fetchone();c.close()
    logo='<img src="/uploads/'+secure_filename(s['logo_path'])+'">' if s['logo_path'] else '<span class="logo">RT</span>'
    return render_template_string(BASE,title=title,body=body,site=s['site_name'],logo=logo,iu=svg('user'),io=svg('logout'),iset=svg('settings'))

def user_required(fn):
    @wraps(fn)
    def w(*a,**kw):
        if not session.get('uid'): return redirect('/login')
        c=db();u=c.execute('SELECT * FROM users WHERE id=?',(session['uid'],)).fetchone();c.close()
        if not u or u['status']!='active': session.clear(); return redirect('/login')
        session['balance']=u['balance']; return fn(*a,**kw)
    return w

def admin_required(fn):
    @wraps(fn)
    def w(*a,**kw):
        if not session.get('admin'): return redirect('/admin/login')
        return fn(*a,**kw)
    return w

@app.route('/')
def root(): return redirect('/home' if session.get('uid') else '/login')

@app.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        un=request.form.get('username','').strip(); pw=request.form.get('password','')
        c=db();u=c.execute('SELECT * FROM users WHERE username=?',(un,)).fetchone();c.close()
        if not u or not check_password_hash(u['password_hash'],pw): flash('Username သို့မဟုတ် Password မှားနေပါတယ်','error')
        elif u['status']!='active': flash('Account ပိတ်ထားပါတယ်','error')
        else: session.clear();session.permanent=True;session['uid']=u['id'];session['balance']=u['balance'];return redirect('/home')
    return page('Login','''<div class="card form"><div class="k">RT777 · ACCOUNT</div><h1>Login</h1><div class="sub">Account ဖြင့် ဝင်ရောက်ပါ။</div><form method="post"><div class="field"><label>Username</label><input class="input" name="username" maxlength="24" required></div><div class="field"><label>Password</label><input class="input" name="password" type="password" required></div><button class="btn gold" style="width:100%">LOGIN · ဝင်မည်</button></form><p class="muted" style="text-align:center">Account မရှိသေးပါသလား? <a href="/register" style="color:#ffe17b">Register</a></p></div>''')

@app.route('/register',methods=['GET','POST'])
def register():
    if request.method=='POST':
        un=request.form.get('username','').strip();pw=request.form.get('password','');cf=request.form.get('confirm','')
        if not re.fullmatch(r'[A-Za-z0-9_]{3,24}',un): flash('Username 3–24 characters ဖြစ်ရမယ်','error')
        elif len(pw)<6: flash('Password အနည်းဆုံး 6 characters လိုပါတယ်','error')
        elif pw!=cf: flash('Password မတူပါ','error')
        else:
            c=db()
            try:
                c.execute('INSERT INTO users(user_id,username,password_hash,balance,status,created_at) VALUES(?,?,?,?,?,?)',('G'+secrets.token_hex(5).upper(),un,generate_password_hash(pw),500,'active',now()));c.commit();flash('Account ဖန်တီးပြီးပါပြီ');return redirect('/login')
            except sqlite3.IntegrityError: flash('Username အသုံးပြုပြီးသားပါ','error')
            finally: c.close()
    return page('Register','''<div class="card form"><div class="k">RT777 · NEW ACCOUNT</div><h1>Register</h1><form method="post"><div class="field"><label>Username</label><input class="input" name="username" maxlength="24" required></div><div class="field"><label>Password</label><input class="input" name="password" type="password" minlength="6" required></div><div class="field"><label>Confirm Password</label><input class="input" name="confirm" type="password" minlength="6" required></div><button class="btn gold" style="width:100%">CREATE ACCOUNT</button></form><p class="muted" style="text-align:center">Account ရှိပြီးသားလား? <a href="/login" style="color:#ffe17b">Login</a></p></div>''')

@app.route('/logout')
def logout(): session.clear();return redirect('/login')

@app.route('/home')
@user_required
def home():
    c=db();u=c.execute('SELECT * FROM users WHERE id=?',(session['uid'],)).fetchone();rooms=c.execute('SELECT * FROM rooms WHERE active=1').fetchall();c.close()
    b=render_template_string('''<div class="hero"><div class="k">PREMIUM LOBBY</div><h1>Welcome, {{u.username}}</h1><div class="sub">User ID: <b>{{u.user_id}}</b> · Balance: <b style="color:#ffe17b">{{"{:,}".format(u.balance)}} Credits</b></div></div><div style="margin:20px 0 10px"><h2>Games · ဂိမ်းများ</h2></div><div class="grid g2"><div class="card gamecard"><div><div class="art"><span>🐯</span><div class="mini">A</div><span>🐉</span></div><h2>Tiger Dragon</h2><div class="sub">2 Minute Round · 8 Player Table · Player Only</div></div><a class="btn gold" href="/game">PLAY GAME {{ig|safe}}</a></div><div class="card"><div class="k">PLAYER TABLES</div><h2>Room System</h2><div class="sub">Bot မပါပါ။ Player ဝင်လာမှ seat ပေါ်မယ်။ Table ပြည့်ရင် switch မလုပ်နိုင်ပါ။</div>{% for r in rooms %}<span class="pill" style="display:inline-block;margin:5px">{{r.name}}</span>{% endfor %}</div></div><div style="margin:20px 0 10px"><h2>Quick Access</h2></div><div class="grid g3"><a class="card" href="/profile">{{iu|safe}} <b>Profile</b><div class="sub">Account details</div></a><a class="card" href="/history">{{ih|safe}} <b>History</b><div class="sub">Bet records</div></a><a class="card" href="/game">{{ig|safe}} <b>Game</b><div class="sub">Open table</div></a></div>''',u=u,rooms=rooms,ig=svg('game'),iu=svg('user'),ih=svg('history'))
    return page('Home',b)

@app.route('/profile')
@user_required
def profile():
    c=db();u=c.execute('SELECT * FROM users WHERE id=?',(session['uid'],)).fetchone();c.close()
    return page('Profile',render_template_string('''<div class="card"><div class="k">ACCOUNT</div><h1>Profile</h1><div class="grid g2"><div class="card"><div class="muted">User ID</div><h3>{{u.user_id}}</h3></div><div class="card"><div class="muted">Username</div><h3>{{u.username}}</h3></div><div class="card"><div class="muted">Balance</div><h3 style="color:#ffe17b">{{"{:,}".format(u.balance)}} Credits</h3></div><div class="card"><div class="muted">Status</div><h3>{{u.status}}</h3></div></div></div>''',u=u))

@app.route('/history')
@user_required
def history():
    c=db();bs=c.execute('SELECT b.*,r.round_no FROM bets b JOIN rounds r ON r.id=b.round_id WHERE b.user_id=? ORDER BY b.id DESC LIMIT 100',(session['uid'],)).fetchall();c.close()
    return page('History',render_template_string('''<div class="card"><div class="k">PLAYER HISTORY</div><h1>History</h1><div class="tw"><table><tr><th>Round</th><th>Side</th><th>Amount</th><th>Status</th><th>Date</th></tr>{% for x in bs %}<tr><td>{{x.round_no}}</td><td>{{x.side|upper}}</td><td>{{"{:,}".format(x.amount)}}</td><td>{{x.status}}</td><td>{{x.created_at}}</td></tr>{% else %}<tr><td colspan="5">No records</td></tr>{% endfor %}</table></div></div>''',bs=bs))

GAME = '''<style>html,body{overflow:hidden;width:100%;height:100%;margin:0;padding:0}body{background:#020403}.top{display:none}.page{width:100%;height:100dvh;margin:0;padding:0;overflow:hidden}.rotate{display:none}.game{width:min(100vw,177.7778dvh);height:min(100dvh,56.25vw);aspect-ratio:16/9;margin:auto;position:fixed;left:50%;top:50%;transform:translate(-50%,-50%);overflow:hidden;background:radial-gradient(ellipse at 50% 42%,#126b45,#092f21 58%,#04170f);color:#fff}.game:after{content:"";position:absolute;inset:1.6%;border:2px solid #d5aa3e66;border-radius:26px;pointer-events:none}.gh{position:absolute;left:3.2%;right:3.2%;top:2.4%;height:9%;display:grid;grid-template-columns:1fr auto 1fr;align-items:center;z-index:5}.gu,.gb{background:#07100ddd;border:1px solid #d3a83c66;border-radius:10px;padding:6px 9px;font-size:clamp(7px,.9vw,12px);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}.gb{text-align:right;color:#ffe17b;font-weight:800}.gt{font:800 clamp(11px,1.75vw,22px) Orbitron;text-align:center;color:#ffe17b}.rooms{position:absolute;top:12%;left:3.2%;z-index:6;display:flex;gap:4px}.rooms button{font-size:clamp(6px,.7vw,10px);padding:5px 8px;min-height:0}.timer{position:absolute;top:12%;right:3.2%;z-index:6;background:#07100d;border:1px solid #d3a83c66;border-radius:10px;padding:4px 9px;text-align:center}.tm{font:800 clamp(12px,1.9vw,24px) Orbitron;color:#ffe17b}.closed{color:#ff858c!important}.tl{font-size:clamp(5px,.58vw,8px);color:#9ca99e}.table{position:absolute;left:14%;right:14%;top:19%;bottom:27%;border-radius:48%/43%;background:radial-gradient(circle,#197b50,#0b4b32 65%,#06281c);border:clamp(2px,.3vw,4px) solid #d9af45;box-shadow:inset 0 0 50px #0008,0 12px 40px #0008}.center{position:absolute;inset:17% 12%;display:flex;align-items:center;justify-content:center;gap:clamp(6px,1.5vw,22px)}.side{width:31%;text-align:center}.sn{font:800 clamp(7px,1vw,13px) Orbitron;color:#ffe17b}.pool{font-size:clamp(6px,.65vw,10px);color:#c7d2c9}.cardx{width:clamp(38px,5.3vw,72px);height:clamp(53px,7.5vw,98px);margin:5px auto;border-radius:8px;background:#f4f1e6;color:#171813;display:grid;place-items:center;font:800 clamp(17px,2.4vw,31px) Georgia;box-shadow:0 8px 20px #0008;transform-style:preserve-3d;backface-visibility:hidden;position:relative}.cardx.flip{animation:cardFlip .78s cubic-bezier(.2,.75,.25,1)}.cardx.revealed{background:#f4f1e6;color:#171813;border:2px solid #ffe17b;box-shadow:0 0 18px #ffe17b55,0 8px 20px #0008}.cardx.revealed:after{content:'';position:absolute;inset:4px;border:1px solid #b58b2d66;border-radius:5px;pointer-events:none}@keyframes cardFlip{0%{transform:perspective(700px) rotateY(0) scale(.96)}45%{transform:perspective(700px) rotateY(90deg) scale(1.06)}100%{transform:perspective(700px) rotateY(0) scale(1)}}.back{background:repeating-linear-gradient(45deg,#191d1a 0 5px,#b98a28 5px 7px);color:transparent;border:2px solid #f2c95a}.back:after{content:"RT";color:#f3cb61;font:800 clamp(9px,1vw,14px) Orbitron;border:1px solid #f3cb61;padding:3px;transform:rotate(-8deg)}.draw{width:17%;text-align:center}.draw b{display:block;border:1px solid #d3a83c66;background:#07100dbb;border-radius:9px;padding:6px;color:#ffe17b;font-size:clamp(6px,.85vw,11px)}.result{position:absolute;left:50%;top:51%;transform:translate(-50%,-50%);font:800 clamp(8px,1vw,14px) Orbitron;text-align:center;white-space:nowrap;text-shadow:0 0 15px #ffe17b77}.result.win{animation:resultPulse .75s ease-out}@keyframes resultPulse{0%{transform:translate(-50%,-50%) scale(.65);opacity:.2}70%{transform:translate(-50%,-50%) scale(1.15)}100%{transform:translate(-50%,-50%) scale(1)}}.seat{position:absolute;width:clamp(42px,5.3vw,70px);text-align:center;font-size:clamp(5px,.58vw,8px);color:#dce5dd}.av{width:clamp(23px,2.7vw,36px);height:clamp(23px,2.7vw,36px);margin:auto;border-radius:50%;display:grid;place-items:center;background:linear-gradient(145deg,#f3cf61,#865c13);color:#19140a;font-weight:900;border:2px solid #fff9}.me .av{box-shadow:0 0 0 3px #ffe27b}.s1{left:3%;top:42%}.s2{left:11%;top:4%}.s3{left:43%;top:-1%}.s4{right:11%;top:4%}.s5{right:3%;top:42%}.s6{right:11%;bottom:4%}.s7{left:43%;bottom:-1%}.s8{left:11%;bottom:4%}.bets{position:absolute;left:3.2%;right:3.2%;bottom:7%;height:15%;display:grid;grid-template-columns:1fr 1fr 1fr;gap:6px;z-index:8}.bb{background:#06100ddd;border:1px solid #d3a83c66;border-radius:10px;padding:5px;display:grid;grid-template-columns:1fr auto;align-items:center;min-width:0}.bn{font:800 clamp(6px,.78vw,10px) Orbitron;color:#ffe17b}.bb button{grid-column:1/-1;border:0;border-radius:7px;padding:5px;background:linear-gradient(135deg,#f9d663,#ad7114);font-weight:900;font-size:clamp(6px,.68vw,9px)}.bb button:disabled{opacity:.35}.amounts{position:absolute;bottom:22.5%;left:50%;transform:translateX(-50%);display:flex;gap:4px;z-index:9}.amounts button{background:#0b120e;color:#ffe17b;border:1px solid #d3a83c66;border-radius:7px;padding:4px 7px;font-size:clamp(6px,.65vw,9px)}.historybar{position:absolute;left:3.2%;right:3.2%;bottom:1.4%;height:4.3%;display:flex;align-items:center;gap:5px;z-index:10;background:#06100ddd;border:1px solid #d3a83c55;border-radius:8px;padding:3px 6px;overflow:hidden}.hist-title{font:800 clamp(6px,.65vw,9px) Orbitron;color:#ffe17b;flex:0 0 auto}.hist-list{display:flex;gap:4px;overflow-x:auto;scrollbar-width:none;white-space:nowrap}.hist-list::-webkit-scrollbar{display:none}.hitem{min-width:clamp(48px,5vw,68px);padding:3px 5px;border-radius:6px;border:1px solid #ffffff18;background:#0c1510;text-align:center;font-size:clamp(5px,.55vw,8px)}.hitem b{display:block}.twin{color:#7ee5b0}.gwin{color:#83b7ff}.drawwin{color:#ffe17b}.modal{display:none;position:fixed;inset:0;background:#000b;z-index:20;place-items:center}.modal.show{display:grid}.mc{width:min(340px,85vw);background:#111611;border:1px solid #d3a83c;border-radius:18px;padding:18px}.mc h3{color:#ffe17b}.toast{position:fixed;left:50%;bottom:15px;transform:translate(-50%,80px);background:#111611;border:1px solid #d3a83c;border-radius:10px;padding:10px 14px;z-index:30;transition:.2s}.toast.on{transform:translate(-50%,0)}@supports not (height:100dvh){.page{height:100vh}.game{height:min(100vh,56.25vw)}}@media (orientation:landscape) and (max-height:420px){.gh{top:1.8%}.rooms{top:10%}.timer{top:10%}.table{top:16%;bottom:28%}.bets{bottom:7%;height:16%}.amounts{bottom:22.5%}.historybar{height:4.8%}}@media(max-aspect-ratio:1/1){.game{display:none}.rotate{display:grid;position:fixed;inset:0;background:#070807;place-items:center;text-align:center}.rotate h2{color:#ffe17b}}</style><div class="rotate"><div><div style="font-size:48px">↔</div><h2>Please Rotate Your Phone</h2><div>ဖုန်းကို အလျားလိုက်လှည့်ပြီး ကစားပါ</div></div></div><div class="game"><div class="gh"><div class="gu" id="u">Guest</div><div class="gt">RT777 · TIGER DRAGON</div><div class="gb" id="bal">Credits 0</div></div><div class="rooms">{% for r in rooms %}<button class="btn dark" onclick="sw({{r.id}})">{{r.name}}</button>{% endfor %}</div><div class="timer"><div class="tm" id="tm">02:00</div><div class="tl" id="tl">BETTING OPEN</div></div><div class="table"><div id="seatbox"></div><div class="center"><div class="side"><div class="sn">TIGER</div><div class="cardx back" id="tc"></div><div class="pool" id="tp">My Bet 0</div></div><div class="draw"><b>DRAW<br>သရေ</b><div class="pool" id="dp">My Bet 0</div></div><div class="side"><div class="sn">DRAGON</div><div class="cardx back" id="dc"></div><div class="pool" id="gp">My Bet 0</div></div></div><div class="result" id="res">ROUND IN PROGRESS</div></div><div class="amounts">{% for a in [100,500,1000,5000] %}<button onclick="amt={{a}}">{{"{:,}".format(a)}}</button>{% endfor %}</div><div class="bets"><div class="bb"><div class="bn">TIGER · MY BET</div><div id="bt" class="pool">0</div><button onclick="openBet('tiger')">BET TIGER</button></div><div class="bb"><div class="bn">DRAW · MY BET</div><div id="bd" class="pool">0</div><button onclick="openBet('draw')">BET DRAW</button></div><div class="bb"><div class="bn">DRAGON · MY BET</div><div id="bg" class="pool">0</div><button onclick="openBet('dragon')">BET DRAGON</button></div></div><div class="historybar"><div class="hist-title">HISTORY</div><div class="hist-list" id="hist"></div></div></div><div class="modal" id="modal"><div class="mc"><h3 id="ms">CONFIRM BET</h3><div class="muted">Amount / ပမာဏ</div><input id="money" class="input" type="number" min="1" step="1" value="100"><div style="display:flex;gap:7px;margin-top:12px"><button class="btn dark" style="flex:1" onclick="closeBet()">CANCEL</button><button class="btn gold" style="flex:1" onclick="place()">CONFIRM</button></div></div></div><div class="toast" id="toast"></div><script>let rid={{room_id}},side='',amt=100,lastRound=null,lastResult=null,lastRevealRound=null;const fmt=n=>Number(n||0).toLocaleString();function pop(x){let t=document.getElementById('toast');t.textContent=x;t.classList.add('on');clearTimeout(window.tt);window.tt=setTimeout(()=>t.classList.remove('on'),2200)}function playAudio(type){fetch('/api/play-audio',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({event:type})})}function openBet(s){side=s;playAudio('bet_click');document.getElementById('ms').textContent='BET '+s.toUpperCase()+(s==='draw'?' · သရေ':'');document.getElementById('money').value=amt;document.getElementById('modal').classList.add('show')}function closeBet(){document.getElementById('modal').classList.remove('show')}async function place(){let a=parseInt(document.getElementById('money').value);if(!Number.isInteger(a)||a<1){pop('Invalid amount');return}let r=await fetch('/api/bet',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({room_id:rid,side,amount:a})}),j=await r.json();if(!j.ok){pop(j.error);return}closeBet();pop('✓ Bet placed');refresh()}async function sw(id){let r=await fetch('/api/switch',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({room_id:id})}),j=await r.json();if(!j.ok){pop(j.error);return}rid=id;lastRound=null;loadHistory();refresh()}function drawSeats(ps){document.querySelectorAll('.seat').forEach(x=>x.remove());let cl=['s1','s2','s3','s4','s5','s6','s7','s8'];ps.forEach((p,i)=>{let d=document.createElement('div');d.className='seat '+cl[i]+' '+(p.me?'me':'');d.innerHTML='<div class="av">'+p.username[0].toUpperCase()+'</div>'+p.username;document.querySelector('.table').appendChild(d)})}function animateCards(j){let tc=document.getElementById('tc'),dc=document.getElementById('dc');let rr=j.reveal&&j.round?j.round:null;let rn=rr?Number(rr.round_no):null;let show=!!(rr&&rr.tiger_card&&rr.dragon_card&&rn!==null);if(show){if(lastRevealRound!==rn){lastRevealRound=rn;tc.className='cardx back flip';dc.className='cardx back flip';tc.textContent='';dc.textContent='';setTimeout(()=>{tc.className='cardx revealed';dc.className='cardx revealed';tc.textContent=rr.tiger_card;dc.textContent=rr.dragon_card},390)}else{tc.className='cardx revealed';dc.className='cardx revealed';tc.textContent=rr.tiger_card;dc.textContent=rr.dragon_card}}else{tc.className='cardx back';dc.className='cardx back';tc.textContent='';dc.textContent=''}}function renderHistory(rows){let h=document.getElementById('hist');h.innerHTML=rows.map(x=>{let cls=x.result==='TIGER WIN'?'twin':x.result==='DRAGON WIN'?'gwin':'drawwin';let short=x.result==='TIGER WIN'?'T':x.result==='DRAGON WIN'?'D':'DRAW';return '<div class="hitem '+cls+'"><b>#'+x.round_no+' · '+short+'</b><span>'+x.tiger_card+' / '+x.dragon_card+'</span></div>'}).join('')}async function loadHistory(){let r=await fetch('/api/round-history?room_id='+rid+'&_='+Date.now()),j=await r.json();if(j.ok)renderHistory(j.history)}async function refresh(){let r=await fetch('/api/state?room_id='+rid+'&_='+Date.now()),j=await r.json();if(!j.ok){pop(j.error);return}document.getElementById('u').textContent=j.user.username+' · '+j.user.user_id;document.getElementById('bal').textContent='Credits '+fmt(j.user.balance);document.getElementById('tm').textContent=j.reveal?'00:00':j.timer;document.getElementById('tl').textContent=j.reveal?'RESULT REVEAL':(j.open?'BETTING OPEN':'BETTING CLOSED');document.getElementById('tm').classList.toggle('closed',!j.open);document.getElementById('tp').textContent='My Bet '+fmt(j.my_bets.tiger);document.getElementById('dp').textContent='My Bet '+fmt(j.my_bets.draw);document.getElementById('gp').textContent='My Bet '+fmt(j.my_bets.dragon);document.getElementById('bt').textContent=fmt(j.my_bets.tiger);document.getElementById('bd').textContent=fmt(j.my_bets.draw);document.getElementById('bg').textContent=fmt(j.my_bets.dragon);animateCards(j);let res=document.getElementById('res');let displayResult=j.reveal&&j.round?j.round.result:null;if(displayResult){res.textContent=displayResult+(displayResult==='DRAW'?' · 5×':' · 2×');if(lastResult!==displayResult){res.classList.remove('win');void res.offsetWidth;res.classList.add('win');lastResult=displayResult;if(displayResult==='TIGER WIN'){playAudio('win')}else if(displayResult==='DRAGON WIN'){playAudio('win')}else if(displayResult==='DRAW'){playAudio('draw')}}}else{res.textContent='ROUND IN PROGRESS';lastResult=null}if(lastRound!==j.round.round_no){lastRound=j.round.round_no;loadHistory()}drawSeats(j.players);document.querySelectorAll('.bb button').forEach(x=>x.disabled=!j.open||j.players.length===0)}setInterval(refresh,1000);setInterval(loadHistory,5000);loadHistory();refresh();</script>'''

@app.route('/game')
@user_required
def game():
    c=db();rooms=c.execute('SELECT * FROM rooms WHERE active=1 ORDER BY id').fetchall();r=rooms[0];c.execute('INSERT INTO room_players VALUES(?,?,?,?) ON CONFLICT(room_id,user_id) DO UPDATE SET last_seen=excluded.last_seen',(r['id'],session['uid'],now(),time.time()));c.commit();c.close();return page('Game',render_template_string(GAME,rooms=rooms,room_id=r['id']))

def get_round(c,rid):
    now_ts=time.time()
    n=int(now_ts//120)
    st=n*120

    r=c.execute(
        'SELECT * FROM rounds WHERE room_id=? AND round_no=?',
        (rid,n)
    ).fetchone()

    if not r:
        prev=c.execute(
            'SELECT * FROM rounds WHERE room_id=? AND round_no<? ORDER BY round_no DESC LIMIT 1',
            (rid,n)
        ).fetchone()

        if prev and prev['status'] != 'settled':
            settle(c,prev)

        c.execute(
            "INSERT INTO rounds(room_id,round_no,started_at,status) VALUES(?,?,?,'open')",
            (rid,n,st)
        )
        c.commit()

        r=c.execute(
            'SELECT * FROM rounds WHERE room_id=? AND round_no=?',
            (rid,n)
        ).fetchone()

    if r and r['status'] == 'open' and now_ts >= r['started_at'] + 120:
        settle(c,r)
        r=c.execute('SELECT * FROM rounds WHERE id=?',(r['id'],)).fetchone()

    return r,now_ts-st

def settle(c,r):
    if r['status']=='settled':return
    import random
    
    # Check if admin overrode the result
    if r['admin_overridden'] == 1 and r['result'] is not None:
        # Use admin-set result
        res = r['result']
        # Cards might be pre-set or random
        if r['tiger_card'] is None:
            t = random.choice(list(CARDS))
            d = random.choice(list(CARDS))
        else:
            t = r['tiger_card']
            d = r['dragon_card']
    else:
        # Random generation
        t = random.choice(list(CARDS))
        d = random.choice(list(CARDS))
        res = 'DRAW' if CARDS[t] == CARDS[d] else ('TIGER WIN' if CARDS[t] > CARDS[d] else 'DRAGON WIN')
    
    c.execute('UPDATE rounds SET tiger_card=?,dragon_card=?,result=?,status="settled",admin_overridden=0 WHERE id=?',(t,d,res,r['id']))
    
    for b in c.execute('SELECT * FROM bets WHERE round_id=? AND status="pending"',(r['id'],)).fetchall():
        win=(res=='TIGER WIN' and b['side']=='tiger') or (res=='DRAGON WIN' and b['side']=='dragon') or (res=='DRAW' and b['side']=='draw')
        c.execute('UPDATE bets SET status=? WHERE id=?',('won' if win else 'lost',b['id']))
        if win:
            u=c.execute('SELECT balance FROM users WHERE id=?',(b['user_id'],)).fetchone();before=u['balance'];gain=b['amount'] * (5 if res=='DRAW' else 2);after=before+gain;c.execute('UPDATE users SET balance=? WHERE id=?',(after,b['user_id']));c.execute('INSERT INTO transactions(user_id,type,amount,before_balance,after_balance,description,created_at) VALUES(?,?,?,?,?,?,?)',(b['user_id'],'WIN',gain,before,after,res,now()))
    c.commit()

@app.route('/api/state')
@user_required
def state():
    try:rid=int(request.args.get('room_id',1))
    except:return jsonify(ok=False,error='Invalid room')
    c=db();r,el=get_round(c,rid)
    if el>=120:settle(c,r);r=c.execute('SELECT * FROM rounds WHERE id=?',(r['id'],)).fetchone()
    c.execute('INSERT INTO room_players VALUES(?,?,?,?) ON CONFLICT(room_id,user_id) DO UPDATE SET last_seen=excluded.last_seen',(rid,session['uid'],now(),time.time()));c.commit()
    ps=c.execute('SELECT u.id,u.user_id,u.username FROM room_players rp JOIN users u ON u.id=rp.user_id WHERE rp.room_id=? AND rp.last_seen>=? AND u.status="active" ORDER BY rp.joined_at LIMIT 8',(rid,time.time()-12)).fetchall()
    my_bets={'tiger':0,'draw':0,'dragon':0}
    for x in c.execute('SELECT side,SUM(amount) n FROM bets WHERE round_id=? AND user_id=? GROUP BY side',(r['id'],session['uid'])).fetchall():
        my_bets[x['side']]=x['n'] or 0
    last_settled=c.execute('SELECT round_no,tiger_card,dragon_card,result FROM rounds WHERE room_id=? AND status="settled" ORDER BY round_no DESC LIMIT 1',(rid,)).fetchone()
    u=c.execute('SELECT * FROM users WHERE id=?',(session['uid'],)).fetchone();c.close();rem=max(0,120-int(el));m,s=divmod(rem,60);reveal_now=bool(last_settled and last_settled['round_no'] < r['round_no'] and el < 5)
    return jsonify(ok=True,user={'username':u['username'],'user_id':u['user_id'],'balance':u['balance']},timer=f'{m:02d}:{s:02d}',open=(el<100 and not reveal_now),reveal=(r['status']=='settled' or reveal_now),reveal_previous=bool(last_settled and last_settled['round_no'] < r['round_no'] and el < 5),round={'round_no':(r['round_no'] if r['status']=='settled' else (last_settled['round_no'] if last_settled and last_settled['round_no'] < r['round_no'] and el < 5 else r['round_no'])),'tiger_card':(r['tiger_card'] if r['status']=='settled' else (last_settled['tiger_card'] if last_settled and last_settled['round_no'] < r['round_no'] and el < 5 else None)),'dragon_card':(r['dragon_card'] if r['status']=='settled' else (last_settled['dragon_card'] if last_settled and last_settled['round_no'] < r['round_no'] and el < 5 else None)),'result':(r['result'] if r['status']=='settled' else (last_settled['result'] if last_settled and last_settled['round_no'] < r['round_no'] and el < 5 else None))},last_result={'round_no':last_settled['round_no'],'tiger_card':last_settled['tiger_card'],'dragon_card':last_settled['dragon_card'],'result':last_settled['result']} if last_settled else None,my_bets=my_bets,players=[{'username':p['username'],'user_id':p['user_id'],'me':p['id']==session['uid']} for p in ps])

@app.route('/api/bet',methods=['POST'])
@user_required
def place_bet():
    d=request.get_json(silent=True) or {};side=str(d.get('side','')).lower()
    try:a=int(d.get('amount',0));rid=int(d.get('room_id',1))
    except:return jsonify(ok=False,error='Invalid request')
    if side not in ('tiger','draw','dragon') or a<1 or a>1000000:return jsonify(ok=False,error='Invalid bet')
    c=db()
    try:
        r,el=get_round(c,rid)
        if el>=100:return jsonify(ok=False,error='Betting is closed')
        u=c.execute('SELECT * FROM users WHERE id=?',(session['uid'],)).fetchone()
        if u['balance']<a:return jsonify(ok=False,error='Insufficient credits')
        before=u['balance'];after=before-a;c.execute('UPDATE users SET balance=? WHERE id=? AND balance>=?',(after,u['id'],a))
        if c.total_changes!=1:return jsonify(ok=False,error='Balance changed; retry')
        c.execute('INSERT INTO bets(round_id,user_id,side,amount,created_at) VALUES(?,?,?,?,?)',(r['id'],u['id'],side,a,now()));c.execute('INSERT INTO transactions(user_id,type,amount,before_balance,after_balance,description,created_at) VALUES(?,?,?,?,?,?,?)',(u['id'],'BET',-a,before,after,side.upper(),now()));c.commit();session['balance']=after;return jsonify(ok=True,balance=after)
    finally:c.close()

@app.route('/api/switch',methods=['POST'])
@user_required
def switch_room():
    try:rid=int((request.get_json(silent=True) or {}).get('room_id'))
    except:return jsonify(ok=False,error='Invalid room')
    c=db();r=c.execute('SELECT * FROM rooms WHERE id=? AND active=1',(rid,)).fetchone()
    if not r:c.close();return jsonify(ok=False,error='Table not found')
    ps=c.execute('SELECT user_id FROM room_players WHERE room_id=? AND last_seen>=?',(rid,time.time()-12)).fetchall()
    if len(ps)>=8 and not any(x['user_id']==session['uid'] for x in ps):c.close();return jsonify(ok=False,error='Table is full')
    c.execute('INSERT INTO room_players VALUES(?,?,?,?) ON CONFLICT(room_id,user_id) DO UPDATE SET last_seen=excluded.last_seen',(rid,session['uid'],now(),time.time()));c.commit();c.close();return jsonify(ok=True)

@app.route('/api/play-audio', methods=['POST'])
def play_audio():
    """API endpoint to trigger audio playback for specific events"""
    data = request.get_json(silent=True) or {}
    event = data.get('event', '')
    
    c = db()
    audio = c.execute('SELECT file_path FROM audio_files WHERE event_type=? AND active=1', (event,)).fetchone()
    c.close()
    
    if audio and audio['file_path']:
        return jsonify(ok=True, audio_url=f'/audio/{secure_filename(audio["file_path"])}')
    return jsonify(ok=False, error='No audio configured for this event')

# ---------------- ADMIN ----------------
def admin_nav(): return render_template_string('''<div class="nav2"><a class="btn dark" href="/admin">{{a|safe}} Dashboard</a><a class="btn dark" href="/admin/users">{{u|safe}} Users</a><a class="btn dark" href="/admin/cards">{{c|safe}} Cards</a><a class="btn dark" href="/admin/settings">{{s|safe}} Settings</a><a class="btn dark" href="/admin/game-control">{{g|safe}} Game Control</a><a class="btn dark" href="/admin/audio">{{v|safe}} Audio</a><a class="btn dark" href="/admin/logs">{{h|safe}} Logs</a><a class="btn red" href="/admin/logout">{{o|safe}} Logout</a></div>''',a=svg('home',16),u=svg('user',16),c=svg('card',16),s=svg('settings',16),g=svg('game',16),v=svg('volume',16),h=svg('history',16),o=svg('logout',16))

@app.route('/api/round-history')
@user_required
def round_history():
    try: rid=int(request.args.get('room_id',1))
    except: return jsonify(ok=False,error='Invalid room')
    c=db(); rows=c.execute('SELECT round_no,tiger_card,dragon_card,result,status FROM rounds WHERE room_id=? AND status="settled" ORDER BY round_no DESC LIMIT 12',(rid,)).fetchall(); c.close()
    return jsonify(ok=True,history=[dict(x) for x in rows])

@app.route('/admin/login',methods=['GET','POST'])
def admin_login():
    if request.method=='POST':
        if secrets.compare_digest(request.form.get('username',''),ADMIN_USER) and secrets.compare_digest(request.form.get('password',''),ADMIN_PASS):session['admin']=True;return redirect('/admin')
        flash('Admin credentials မမှန်ပါ','error')
    return page('Admin Login','''<div class="card form"><div class="k">RT777 · ADMIN</div><h1>Admin Login</h1><form method="post"><div class="field"><label>Username</label><input class="input" name="username" required></div><div class="field"><label>Password</label><input class="input" name="password" type="password" required></div><button class="btn gold" style="width:100%">ADMIN LOGIN</button></form></div>''')
@app.route('/admin/logout')
def admin_logout():session.pop('admin',None);return redirect('/admin/login')

@app.route('/admin')
@admin_required
def admin():
    c=db();vals=[c.execute('SELECT COUNT(*) n FROM users').fetchone()['n'],c.execute('SELECT COUNT(*) n FROM users WHERE status="active"').fetchone()['n'],c.execute('SELECT COUNT(*) n FROM bets').fetchone()['n'],c.execute('SELECT COALESCE(SUM(balance),0) n FROM users').fetchone()['n']];logs=c.execute('SELECT * FROM admin_logs ORDER BY id DESC LIMIT 10').fetchall();c.close()
    return page('Admin',admin_nav()+render_template_string('''<h1>Admin Dashboard</h1><div class="grid g4">{% for x in vals %}<div class="card stat"><div class="muted">{{['USERS','ACTIVE','BETS','CREDITS'][loop.index0]}}</div><div class="v">{{"{:,}".format(x)}}</div></div>{% endfor %}</div><div class="card" style="margin-top:15px"><h3>Recent Logs</h3><div class="tw"><table><tr><th>Action</th><th>User</th><th>Details</th><th>Time</th></tr>{% for x in logs %}<tr><td>{{x.action}}</td><td>{{x.user_id or '-'}}</td><td>{{x.details or '-'}}</td><td>{{x.created_at}}</td></tr>{% endfor %}</table></div></div>''',vals=vals,logs=logs))

@app.route('/admin/users')
@admin_required
def admin_users():
    c=db();us=c.execute('SELECT * FROM users ORDER BY id DESC').fetchall();c.close()
    return page('Users',admin_nav()+render_template_string('''<h1>User Management</h1><div class="card"><div class="tw"><table><tr><th>Username</th><th>User ID</th><th>Balance</th><th>Status</th><th>Actions</th></tr>{% for u in us %}<tr><td>{{u.username}}</td><td>{{u.user_id}}</td><td>{{"{:,}".format(u.balance)}}</td><td>{{u.status}}</td><td><form method="post" action="/admin/user/{{u.id}}" style="display:flex;gap:4px;flex-wrap:wrap"><input class="input" style="width:100px;height:36px" type="number" name="amount" min="1" required><button class="btn gold" name="act" value="add">{{p|safe}}</button><button class="btn dark" name="act" value="remove">{{m|safe}}</button><button class="btn red" name="act" value="toggle">{{'Ban' if u.status=='active' else 'Unban'}}</button></form></td></tr>{% endfor %}</table></div></div>''',us=us,p=svg('plus',14),m=svg('minus',14)))

@app.route('/admin/user/<int:uid>',methods=['POST'])
@admin_required
def admin_user(uid):
    c=db();u=c.execute('SELECT * FROM users WHERE id=?',(uid,)).fetchone();act=request.form.get('act')
    if not u:c.close();flash('User not found','error');return redirect('/admin/users')
    if act=='toggle': new='banned' if u['status']=='active' else 'active';c.execute('UPDATE users SET status=? WHERE id=?',(new,uid));detail='status='+new
    else:
        try:a=int(request.form.get('amount',0))
        except:a=0
        if a<1:c.close();flash('Invalid amount','error');return redirect('/admin/users')
        before=u['balance'];after=before+a if act=='add' else max(0,before-a);c.execute('UPDATE users SET balance=? WHERE id=?',(after,uid));c.execute('INSERT INTO transactions(user_id,type,amount,before_balance,after_balance,description,created_at) VALUES(?,?,?,?,?,?,?)',(uid,'ADMIN',after-before,before,after,'Admin adjustment',now()));detail=f'{before} -> {after}'
    c.execute('INSERT INTO admin_logs(admin,action,user_id,details,created_at) VALUES(?,?,?,?,?)',(ADMIN_USER,'USER UPDATE',u['user_id'],detail,now()));c.commit();c.close();flash('Updated');return redirect('/admin/users')

@app.route('/admin/cards',methods=['GET','POST'])
@admin_required
def admin_cards():
    c=db()
    if request.method=='POST':
        side=request.form.get('side');card=request.form.get('card')
        if side not in ('tiger','dragon') or card not in CARDS:c.close();flash('Invalid card','error');return redirect('/admin/cards')
        c.execute('UPDATE cards SET card_name=?,card_value=?,updated_at=? WHERE side=?',(card,CARDS[card],now(),side));c.execute('INSERT INTO admin_logs(admin,action,details,created_at) VALUES(?,?,?,?)',(ADMIN_USER,'CARD SET',side+'='+card,now()));c.commit()
    cs=c.execute('SELECT * FROM cards').fetchall();c.close();cur={x['side']:x['card_name'] for x in cs}
    return page('Cards',admin_nav()+render_template_string('''<h1>Card Management</h1><div class="grid g2">{% for side in ['tiger','dragon'] %}<div class="card"><div class="k">{{side|upper}}</div><h3>Set Next Card</h3><form method="post"><input type="hidden" name="side" value="{{side}}"><select class="input" name="card">{% for x in vals %}<option {% if cur[side]==x %}selected{% endif %}>{{x}}</option>{% endfor %}</select><button class="btn gold" style="margin-top:10px;width:100%">SET {{side|upper}}</button></form></div>{% endfor %}</div>''',cur=cur,vals=list(CARDS)))

@app.route('/admin/settings',methods=['GET','POST'])
@admin_required
def admin_settings():
    c=db()
    if request.method=='POST':
        name=(request.form.get('site_name') or 'RT777').strip()[:40];maint=1 if request.form.get('maintenance') else 0;f=request.files.get('logo');lp=c.execute('SELECT logo_path FROM settings WHERE id=1').fetchone()['logo_path']
        if f and f.filename:
            ext=secure_filename(f.filename).rsplit('.',1)[-1].lower() if '.' in f.filename else ''
            if ext not in ALLOWED:c.close();flash('Invalid image type','error');return redirect('/admin/settings')
            lp='logo_'+secrets.token_hex(5)+'.'+ext;f.save(os.path.join(UPLOADS,lp))
        c.execute('UPDATE settings SET site_name=?,logo_path=?,maintenance=? WHERE id=1',(name,lp,maint));c.execute('INSERT INTO admin_logs(admin,action,details,created_at) VALUES(?,?,?,?)',(ADMIN_USER,'SETTINGS',name,now()));c.commit()
    s=c.execute('SELECT * FROM settings WHERE id=1').fetchone();c.close()
    return page('Settings',admin_nav()+render_template_string('''<h1>Site Settings</h1><div class="card"><form method="post" enctype="multipart/form-data"><div class="field"><label>Website Name</label><input class="input" name="site_name" value="{{s.site_name}}"></div><div class="field"><label>Logo · max 2MB</label><input class="input" type="file" name="logo" accept=".png,.jpg,.jpeg,.webp,.gif"></div><div class="field"><label><input type="checkbox" name="maintenance" {% if s.maintenance %}checked{% endif %}> Maintenance Mode</label></div><button class="btn gold">SAVE SETTINGS</button></form></div>''',s=s))

# ============= ADMIN GAME CONTROL =============
@app.route('/admin/game-control', methods=['GET', 'POST'])
@admin_required
def admin_game_control():
    c = db()
    rooms = c.execute('SELECT * FROM rooms WHERE active=1').fetchall()
    
    if request.method == 'POST':
        room_id = int(request.form.get('room_id', 1))
        action = request.form.get('action')
        
        if action == 'set_result':
            result = request.form.get('result')
            tiger_card = request.form.get('tiger_card')
            dragon_card = request.form.get('dragon_card')
            
            if result not in ('TIGER WIN', 'DRAGON WIN', 'DRAW'):
                flash('Invalid result selection', 'error')
                c.close()
                return redirect('/admin/game-control')
            
            # Get current open round
            r, _ = get_round(c, room_id)
            
            # Check if round is open
            if r['status'] == 'settled':
                flash('Current round is already settled', 'error')
                c.close()
                return redirect('/admin/game-control')
            
            # Update round with admin override
            c.execute('''UPDATE rounds 
                        SET tiger_card=?, dragon_card=?, result=?, 
                            status='settled', admin_overridden=1 
                        WHERE id=?''',
                     (tiger_card, dragon_card, result, r['id']))
            
            # Settle the round
            settle(c, r)
            
            c.execute('INSERT INTO admin_logs(admin,action,details,created_at) VALUES(?,?,?,?)',
                     (ADMIN_USER, 'GAME RESULT SET', f'Room {room_id}: {result} ({tiger_card}/{dragon_card})', now()))
            c.commit()
            flash(f'Result set to {result} successfully!', 'success')
            
        elif action == 'close_betting':
            # Force close betting for current round
            r, _ = get_round(c, room_id)
            if r['status'] == 'open':
                c.execute('UPDATE rounds SET started_at=? WHERE id=?', (time.time() - 120, r['id']))
                c.commit()
                flash('Betting closed for current round', 'success')
            else:
                flash('Round is already settled', 'error')
    
    # Get current state for each room
    room_states = []
    for room in rooms:
        r, el = get_round(c, room['id'])
        room_states.append({
            'id': room['id'],
            'name': room['name'],
            'round_no': r['round_no'],
            'status': r['status'],
            'elapsed': int(el),
            'remaining': max(0, 120 - int(el))
        })
    
    c.close()
    
    return page('Game Control', admin_nav() + render_template_string('''
    <h1>Game Control</h1>
    
    <div class="grid g2" style="margin-bottom:20px">
        {% for room in rooms %}
        <div class="card">
            <div class="k">ROOM {{room.id}}</div>
            <h2>{{room.name}}</h2>
            <div class="grid g2" style="margin:10px 0">
                <div class="stat"><div class="muted">Round</div><div class="v">#{{room.round_no}}</div></div>
                <div class="stat"><div class="muted">Status</div><div class="v" style="font-size:16px">{{room.status|upper}}</div></div>
                <div class="stat"><div class="muted">Time Left</div><div class="v">{{room.remaining}}s</div></div>
            </div>
        </div>
        {% endfor %}
    </div>
    
    <div class="card">
        <h2>Set Round Result (Admin Override)</h2>
        <p class="sub">Manually set the result for the current open round. This will force-settle the round immediately.</p>
        <form method="post">
            <input type="hidden" name="action" value="set_result">
            <div class="grid g3">
                <div class="field">
                    <label>Room</label>
                    <select class="input" name="room_id">
                    {% for room in rooms %}
                        <option value="{{room.id}}">{{room.name}}</option>
                    {% endfor %}
                    </select>
                </div>
                <div class="field">
                    <label>Tiger Card</label>
                    <select class="input" name="tiger_card">
                    {% for card in cards %}
                        <option value="{{card}}">{{card}}</option>
                    {% endfor %}
                    </select>
                </div>
                <div class="field">
                    <label>Dragon Card</label>
                    <select class="input" name="dragon_card">
                    {% for card in cards %}
                        <option value="{{card}}">{{card}}</option>
                    {% endfor %}
                    </select>
                </div>
            </div>
            <div class="field">
                <label>Result</label>
                <div class="grid g3">
                    <button class="btn gold" name="result" value="TIGER WIN">🐯 TIGER WIN</button>
                    <button class="btn gold" name="result" value="DRAW">⚖️ DRAW</button>
                    <button class="btn gold" name="result" value="DRAGON WIN">🐉 DRAGON WIN</button>
                </div>
            </div>
        </form>
    </div>
    
    <div class="card" style="margin-top:15px">
        <h2>Quick Actions</h2>
        <div class="grid g2">
            <form method="post">
                <input type="hidden" name="action" value="close_betting">
                <input type="hidden" name="room_id" value="1">
                <button class="btn red" style="width:100%">⏹️ Force Close Betting</button>
            </form>
        </div>
    </div>
    ''', rooms=rooms, room_states=room_states, cards=list(CARDS)))

# ============= ADMIN AUDIO MANAGEMENT =============
@app.route('/admin/audio', methods=['GET', 'POST'])
@admin_required
def admin_audio():
    c = db()
    
    if request.method == 'POST':
        event = request.form.get('event')
        action = request.form.get('action')
        
        if action == 'upload' and event:
            f = request.files.get('audio_file')
            if f and f.filename:
                ext = secure_filename(f.filename).rsplit('.', 1)[-1].lower() if '.' in f.filename else ''
                if ext not in AUDIO_ALLOWED:
                    flash('Invalid audio format. Allowed: mp3, wav, ogg', 'error')
                else:
                    # Delete old file if exists
                    old = c.execute('SELECT file_path FROM audio_files WHERE event_type=?', (event,)).fetchone()
                    if old and old['file_path']:
                        old_path = os.path.join(AUDIO_UPLOADS, old['file_path'])
                        if os.path.exists(old_path):
                            os.remove(old_path)
                    
                    filename = f'{event}_{secrets.token_hex(4)}.{ext}'
                    f.save(os.path.join(AUDIO_UPLOADS, filename))
                    c.execute('UPDATE audio_files SET file_path=?, updated_at=? WHERE event_type=?', 
                             (filename, now(), event))
                    c.execute('INSERT INTO admin_logs(admin,action,details,created_at) VALUES(?,?,?,?)',
                             (ADMIN_USER, 'AUDIO UPLOAD', f'{event}: {filename}', now()))
                    c.commit()
                    flash(f'Audio uploaded for {event}', 'success')
        
        elif action == 'toggle' and event:
            current = c.execute('SELECT active FROM audio_files WHERE event_type=?', (event,)).fetchone()
            new_active = 0 if current and current['active'] else 1
            c.execute('UPDATE audio_files SET active=? WHERE event_type=?', (new_active, event))
            c.execute('INSERT INTO admin_logs(admin,action,details,created_at) VALUES(?,?,?,?)',
                     (ADMIN_USER, 'AUDIO TOGGLE', f'{event}: {"on" if new_active else "off"}', now()))
            c.commit()
            flash(f'Audio {"enabled" if new_active else "disabled"} for {event}', 'success')
        
        elif action == 'delete' and event:
            old = c.execute('SELECT file_path FROM audio_files WHERE event_type=?', (event,)).fetchone()
            if old and old['file_path']:
                old_path = os.path.join(AUDIO_UPLOADS, old['file_path'])
                if os.path.exists(old_path):
                    os.remove(old_path)
            c.execute('UPDATE audio_files SET file_path=NULL, updated_at=? WHERE event_type=?', (now(), event))
            c.execute('INSERT INTO admin_logs(admin,action,details,created_at) VALUES(?,?,?,?)',
                     (ADMIN_USER, 'AUDIO DELETE', event, now()))
            c.commit()
            flash(f'Audio deleted for {event}', 'success')
    
    audio_files = c.execute('SELECT * FROM audio_files ORDER BY event_type').fetchall()
    c.close()
    
    event_names = {
        'bet_click': 'Bet Click Sound',
        'win': 'Win Sound',
        'lose': 'Lose Sound',
        'draw': 'Draw Sound',
        'bet_close': 'Bet Close Sound'
    }
    
    return page('Audio Settings', admin_nav() + render_template_string('''
    <h1>Audio Settings</h1>
    <p class="sub">Upload audio files for different game events. Supported formats: MP3, WAV, OGG</p>
    
    <div class="grid g2">
        {% for audio in audio_files %}
        <div class="card">
            <div class="k">{{audio.event_type|upper}}</div>
            <h3>{{event_names.get(audio.event_type, audio.event_type)}}</h3>
            <div style="display:flex;gap:10px;align-items:center;flex-wrap:wrap">
                <span class="pill" style="{% if audio.active %}border-color:#4caf50{% else %}border-color:#666{% endif %}">
                    {{'🟢 Active' if audio.active else '🔴 Disabled'}}
                </span>
                {% if audio.file_path %}
                <span class="pill">📁 {{audio.file_path}}</span>
                <button onclick="playTest('{{audio.event_type}}')" class="btn dark">▶ Test</button>
                {% else %}
                <span class="muted">No audio uploaded</span>
                {% endif %}
            </div>
            <form method="post" enctype="multipart/form-data" style="margin-top:12px">
                <input type="hidden" name="event" value="{{audio.event_type}}">
                <div style="display:flex;gap:8px;flex-wrap:wrap">
                    <input type="file" name="audio_file" accept=".mp3,.wav,.ogg" class="input" style="flex:1;min-width:120px">
                    <button class="btn gold" name="action" value="upload">Upload</button>
                    <button class="btn dark" name="action" value="toggle">
                        {{'Disable' if audio.active else 'Enable'}}
                    </button>
                    {% if audio.file_path %}
                    <button class="btn red" name="action" value="delete" onclick="return confirm('Delete this audio file?')">Delete</button>
                    {% endif %}
                </div>
            </form>
        </div>
        {% endfor %}
    </div>
    
    <script>
    function playTest(eventType) {
        fetch('/api/play-audio', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({event: eventType})
        })
        .then(r => r.json())
        .then(data => {
            if (data.ok && data.audio_url) {
                let audio = new Audio(data.audio_url);
                audio.play().catch(e => console.log('Audio play error:', e));
            } else {
                alert('No audio configured for this event');
            }
        });
    }
    </script>
    ''', audio_files=audio_files, event_names=event_names))

@app.route('/audio/<path:filename>')
def serve_audio(filename):
    """Serve audio files"""
    return send_from_directory(AUDIO_UPLOADS, secure_filename(filename))

@app.route('/admin/logs')
@admin_required
def admin_logs():
    c=db();ls=c.execute('SELECT * FROM admin_logs ORDER BY id DESC LIMIT 200').fetchall();c.close();return page('Logs',admin_nav()+render_template_string('''<h1>Audit Logs</h1><div class="card"><div class="tw"><table><tr><th>Admin</th><th>Action</th><th>User</th><th>Details</th><th>Time</th></tr>{% for x in ls %}<tr><td>{{x.admin}}</td><td>{{x.action}}</td><td>{{x.user_id or '-'}}</td><td>{{x.details or '-'}}</td><td>{{x.created_at}}</td></tr>{% endfor %}</table></div></div>''',ls=ls))

@app.route('/uploads/<name>')
def uploads(name): return send_from_directory(UPLOADS,secure_filename(name))
@app.errorhandler(404)
def not_found(e): return page('404','<div class="card hero"><div class="k">404</div><h1>Page Not Found</h1><div class="sub">စာမျက်နှာမတွေ့ပါ။</div><a class="btn gold" href="/">Home</a></div>'),404
@app.errorhandler(413)
def too_large(e): return page('Upload Error','<div class="card hero"><h1>File Too Large</h1><div class="sub">Maximum upload size is 2MB.</div></div>'),413

if __name__=='__main__': app.run(host='0.0.0.0',port=int(os.environ.get('PORT','5000')),debug=False)