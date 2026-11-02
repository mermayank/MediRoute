from flask import Flask, render_template, request, jsonify, session, redirect, url_for, send_from_directory
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename
import sqlite3, os, csv, io, re, math, uuid, json, hashlib, tempfile
from cryptography.fernet import Fernet
from dotenv import load_dotenv
load_dotenv()
from safety import validate_online_item, can_dispatch
from datetime import datetime, timedelta, date
from difflib import SequenceMatcher
from functools import wraps

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.environ.get('DATABASE_PATH', os.path.join(BASE, 'mediroute.db'))
UPLOAD_DIR = os.environ.get('UPLOAD_DIR', os.path.join(BASE, 'private_uploads'))
os.makedirs(UPLOAD_DIR, exist_ok=True)
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'dev-only-change-this-before-deployment')
if os.environ.get('APP_ENV')=='production' and app.secret_key.startswith('dev-only'): raise RuntimeError('Set SECRET_KEY before running in production')
app.config['MAX_CONTENT_LENGTH'] = 8 * 1024 * 1024
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = os.environ.get('APP_ENV') == 'production'
FERNET = Fernet(__import__('base64').urlsafe_b64encode(hashlib.sha256(app.secret_key.encode()).digest()))
ALLOWED = {'png','jpg','jpeg','webp','pdf'}

STORES = [
 ('Salt Lake','Kolkata',22.5867,88.4170),('Behala','Kolkata',22.4986,88.3090),('Howrah Maidan','Howrah',22.5892,88.3103),
 ('Park Street','Kolkata',22.5535,88.3530),('Gariahat','Kolkata',22.5186,88.3650),('Shyambazar','Kolkata',22.6010,88.3730),
 ('New Town','Kolkata',22.5800,88.4590),('Dum Dum','Kolkata',22.6330,88.4220),('Ballygunge','Kolkata',22.5290,88.3640),
 ('Serampore','Howrah',22.7520,88.3420),('Central Warehouse','Kolkata',22.5700,88.3900)
]
MEDICINES = [
 ('Metformin 500 mg','MET500','strip of 15','H',30.00,'Metformin','Prescription required'),
 ('Telmisartan 40 mg','TEL40','strip of 10','H',95.00,'Telmisartan','Prescription required'),
 ('Levothyroxine 50 mcg','LEV50','bottle of 100','H',190.00,'Levothyroxine','Prescription required'),
 ('Amlodipine 5 mg','AML5','strip of 10','H',42.00,'Amlodipine','Prescription required'),
 ('Vitamin D3 1000 IU','VITD3','strip of 10','OTC',65.00,'Cholecalciferol','General sale'),
 ('Pantoprazole 40 mg','PAN40','strip of 10','H',55.00,'Pantoprazole','Prescription required'),
 ('Atorvastatin 10 mg','ATO10','strip of 10','H',78.00,'Atorvastatin','Prescription required'),
 ('Insulin Glargine 100 IU','INS100','vial','H1',520.00,'Insulin glargine','Enhanced register required'),
 ('Cetirizine 10 mg','CET10','strip of 10','OTC',22.00,'Cetirizine','General sale')
]

def db():
    c=sqlite3.connect(DB_PATH); c.row_factory=sqlite3.Row; c.execute('PRAGMA foreign_keys=ON'); return c

def init_db():
    c=db(); c.executescript('''
    CREATE TABLE IF NOT EXISTS users(id INTEGER PRIMARY KEY, name TEXT NOT NULL, email TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('customer','pharmacist','admin')), phone TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS profiles(id INTEGER PRIMARY KEY, user_id INTEGER NOT NULL REFERENCES users(id), name TEXT NOT NULL, relation TEXT DEFAULT 'Self');
    CREATE TABLE IF NOT EXISTS stores(id INTEGER PRIMARY KEY, name TEXT UNIQUE, city TEXT, lat REAL, lon REAL);
    CREATE TABLE IF NOT EXISTS medicines(id INTEGER PRIMARY KEY, name TEXT UNIQUE, sku TEXT, pack TEXT, schedule TEXT, price REAL, generic_name TEXT, note TEXT);
    CREATE TABLE IF NOT EXISTS inventory(id INTEGER PRIMARY KEY, store_id INTEGER REFERENCES stores(id), medicine_id INTEGER REFERENCES medicines(id), stock INTEGER NOT NULL DEFAULT 0, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, UNIQUE(store_id,medicine_id));
    CREATE TABLE IF NOT EXISTS prescriptions(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), profile_id INTEGER REFERENCES profiles(id), filename TEXT, stored_name TEXT, status TEXT DEFAULT 'uploaded', extracted_text TEXT, ai_draft TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS orders(id INTEGER PRIMARY KEY, order_code TEXT UNIQUE, user_id INTEGER REFERENCES users(id), profile_id INTEGER REFERENCES profiles(id), store_id INTEGER REFERENCES stores(id), status TEXT DEFAULT 'awaiting_verification', payment_method TEXT DEFAULT 'COD_TEST', total REAL DEFAULT 0, prescription_id INTEGER REFERENCES prescriptions(id), created_at TEXT DEFAULT CURRENT_TIMESTAMP, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, invoice_no TEXT, delivery_note TEXT);
    CREATE TABLE IF NOT EXISTS order_items(id INTEGER PRIMARY KEY, order_id INTEGER REFERENCES orders(id), medicine_id INTEGER REFERENCES medicines(id), qty INTEGER NOT NULL, unit_price REAL NOT NULL, schedule TEXT NOT NULL, approval_status TEXT DEFAULT 'pending', approved_qty INTEGER, pharmacist_note TEXT);
    CREATE TABLE IF NOT EXISTS verifications(id INTEGER PRIMARY KEY, order_item_id INTEGER REFERENCES order_items(id), pharmacist_id INTEGER REFERENCES users(id), decision TEXT, reason TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS h1_register(id INTEGER PRIMARY KEY, order_item_id INTEGER REFERENCES order_items(id), prescriber_name TEXT NOT NULL, patient_name TEXT NOT NULL, pharmacist_id INTEGER REFERENCES users(id), created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS refill_subscriptions(id INTEGER PRIMARY KEY, user_id INTEGER REFERENCES users(id), profile_id INTEGER REFERENCES profiles(id), medicine_id INTEGER REFERENCES medicines(id), qty INTEGER, daily_dose REAL, start_date TEXT, active INTEGER DEFAULT 1, last_reminded TEXT);
    CREATE TABLE IF NOT EXISTS audit_logs(id INTEGER PRIMARY KEY, actor_id INTEGER REFERENCES users(id), action TEXT, entity_type TEXT, entity_id INTEGER, detail TEXT, created_at TEXT DEFAULT CURRENT_TIMESTAMP);
    ''')
    if c.execute('SELECT COUNT(*) FROM users').fetchone()[0]==0:
        c.execute('INSERT INTO users(name,email,password_hash,role,phone) VALUES(?,?,?,?,?)',('Demo Customer','customer@mediroute.demo',generate_password_hash('Customer123!'),'customer','9000000001'))
        c.execute('INSERT INTO users(name,email,password_hash,role,phone) VALUES(?,?,?,?,?)',('Demo Pharmacist','pharmacist@mediroute.demo',generate_password_hash('Pharmacist123!'),'pharmacist','9000000002'))
        c.execute('INSERT INTO users(name,email,password_hash,role,phone) VALUES(?,?,?,?,?)',('Operations Admin','admin@mediroute.demo',generate_password_hash('Admin123!'),'admin','9000000003'))
        c.execute("INSERT INTO profiles(user_id,name,relation) VALUES(1,'Debasish Ghosh','Self')")
        c.execute("INSERT INTO profiles(user_id,name,relation) VALUES(1,'Debasish Ghosh - Mother','Mother')")
        for s in STORES: c.execute('INSERT INTO stores(name,city,lat,lon) VALUES(?,?,?,?)',s)
        for m in MEDICINES: c.execute('INSERT INTO medicines(name,sku,pack,schedule,price,generic_name,note) VALUES(?,?,?,?,?,?,?)',m)
        stores=c.execute('SELECT id FROM stores').fetchall(); meds=c.execute('SELECT id,schedule FROM medicines').fetchall()
        for si,s in enumerate(stores):
            for mi,m in enumerate(meds): c.execute('INSERT INTO inventory(store_id,medicine_id,stock) VALUES(?,?,?)',(s['id'],m['id'], 0 if (si+mi)%11==0 else 18+((si*7+mi*3)%45)))
        # Seed three sample-order states matching the brief.
        p=c.execute("INSERT INTO prescriptions(user_id,profile_id,filename,status,extracted_text,ai_draft) VALUES(1,2,'sample-prescription.jpg','approved','Metformin 500 mg, 1 tablet twice daily','[]')").lastrowid
        sid=c.execute("SELECT id FROM stores WHERE name='Salt Lake'").fetchone()[0]
        oid=c.execute("INSERT INTO orders(order_code,user_id,profile_id,store_id,status,total,prescription_id,payment_method) VALUES('RX-50211',1,2,?,'packed',120,?,'COD_TEST')",(sid,p)).lastrowid
        mid=c.execute("SELECT id FROM medicines WHERE sku='MET500'").fetchone()[0]
        c.execute("INSERT INTO order_items(order_id,medicine_id,qty,unit_price,schedule,approval_status,approved_qty) VALUES(?,?,4,30,'H','approved',4)",(oid,mid))
        p2=c.execute("INSERT INTO prescriptions(user_id,profile_id,filename,status,extracted_text,ai_draft) VALUES(1,1,'telmisartan.jpg','pending','Telmisartan 40 mg once daily','[]')").lastrowid
        sid2=c.execute("SELECT id FROM stores WHERE name='Behala'").fetchone()[0]
        oid2=c.execute("INSERT INTO orders(order_code,user_id,profile_id,store_id,status,total,prescription_id) VALUES('RX-50214',1,1,?,'awaiting_verification',285,?)",(sid2,p2)).lastrowid
        mid2=c.execute("SELECT id FROM medicines WHERE sku='TEL40'").fetchone()[0]
        c.execute("INSERT INTO order_items(order_id,medicine_id,qty,unit_price,schedule) VALUES(?,?,3,95,'H')",(oid2,mid2))
        p3=c.execute("INSERT INTO prescriptions(user_id,profile_id,filename,status,extracted_text,ai_draft) VALUES(1,1,'thyroid.jpg','reupload_requested','Unreadable image','[]')").lastrowid
        sid3=c.execute("SELECT id FROM stores WHERE name='Howrah Maidan'").fetchone()[0]
        oid3=c.execute("INSERT INTO orders(order_code,user_id,profile_id,store_id,status,total,prescription_id) VALUES('RX-50219',1,1,?,'on_hold',190,?)",(sid3,p3)).lastrowid
        mid3=c.execute("SELECT id FROM medicines WHERE sku='LEV50'").fetchone()[0]
        c.execute("INSERT INTO order_items(order_id,medicine_id,qty,unit_price,schedule,approval_status,pharmacist_note) VALUES(?,?,1,190,'H','pending','Please upload a clearer prescription')",(oid3,mid3))
        c.execute("INSERT INTO refill_subscriptions(user_id,profile_id,medicine_id,qty,daily_dose,start_date) VALUES(1,2,?,60,2,?)",(mid, (date.today()-timedelta(days=25)).isoformat()))
        c.commit()
    c.close()

init_db()

def login_required(fn):
    @wraps(fn)
    def wrap(*a,**kw):
        if not session.get('user_id'): return jsonify({'error':'Sign in required'}),401
        return fn(*a,**kw)
    return wrap

def roles(*allowed):
    def deco(fn):
        @wraps(fn)
        def wrap(*a,**kw):
            if not session.get('user_id'): return jsonify({'error':'Sign in required'}),401
            if session.get('role') not in allowed: return jsonify({'error':'You do not have permission for this action'}),403
            return fn(*a,**kw)
        return wrap
    return deco

def audit(c, action, entity, eid, detail=''):
    c.execute('INSERT INTO audit_logs(actor_id,action,entity_type,entity_id,detail) VALUES(?,?,?,?,?)',(session.get('user_id'),action,entity,eid,detail[:500]))

def haversine(a,b,c_,d):
    r=6371; p1,p2=math.radians(a),math.radians(c_); dp=math.radians(c_-a); dl=math.radians(d-b)
    x=math.sin(dp/2)**2+math.cos(p1)*math.cos(p2)*math.sin(dl/2)**2
    return 2*r*math.asin(math.sqrt(x))

def route_store(c, items):
    # Central routing uses the nearest store that has every requested item in sufficient quantity.
    customer=(22.5726,88.3639) # Demo origin: central Kolkata; replace with consented address geocoding in production.
    stores=c.execute('SELECT * FROM stores WHERE name != "Central Warehouse"').fetchall(); choices=[]
    for s in stores:
        totaldist=haversine(customer[0],customer[1],s['lat'],s['lon']); ok=True
        for it in items:
            row=c.execute('SELECT stock FROM inventory WHERE store_id=? AND medicine_id=?',(s['id'],it['medicine_id'])).fetchone()
            if not row or row['stock']<it['qty']: ok=False; break
        if ok: choices.append((totaldist,s))
    if not choices: return None
    return sorted(choices,key=lambda x:x[0])[0][1]

def extract_prescription(path, filename):
    """OCR draft extraction. Tesseract is optional; never returns a clinical approval."""
    text=''; engine='unavailable'
    try:
        if filename.lower().endswith('.pdf'):
            return {'text':'PDF uploaded. OCR preview is unavailable for this demo; pharmacist must inspect the document.','engine':'pdf_manual_review','items':[],'confidence':0.0,'needs_review':True}
        import pytesseract
        from PIL import Image
        text=pytesseract.image_to_string(Image.open(path))
        engine='tesseract'
    except Exception:
        text=''
    c=db(); meds=c.execute('SELECT * FROM medicines').fetchall(); c.close(); found=[]
    normalized=re.sub(r'[^a-z0-9. ]',' ',text.lower())
    for m in meds:
        target=m['name'].lower(); generic=m['generic_name'].lower()
        score=max(SequenceMatcher(None,target,normalized).ratio(),SequenceMatcher(None,generic,normalized).ratio())
        if target in normalized or generic in normalized or score>.48:
            
            qty=1
            nearby=normalized[max(0,normalized.find(target)-35):normalized.find(target)+len(target)+45] if target in normalized else normalized
            qmatch=re.search(r'(?:qty|quantity|packs?|strips?|x)\s*[:=-]?\s*(\d{1,3})',nearby)
            if qmatch: qty=max(1,min(100,int(qmatch.group(1))))
            found.append({'medicine_id':m['id'],'name':m['name'],'schedule':m['schedule'],'suggested_qty':qty,'confidence':round(min(.97,score),2),'source':'OCR draft'})
    return {'text':text or 'No readable text detected. Please upload a clearer image.','engine':engine,'items':found,'confidence':max([x['confidence'] for x in found],default=0),'needs_review':True}

@app.route('/')
def index(): return render_template('index.html')

@app.post('/api/login')
def login():
    data=request.get_json(force=True); email=(data.get('email') or '').strip().lower(); otp=(data.get('otp') or '').strip()
    if os.environ.get('APP_ENV')=='production': return jsonify({'error':'Configure a real OTP provider before enabling production sign-in'}),503
    expected=os.environ.get('DEMO_OTP','246810')
    if otp != expected: return jsonify({'error':'Invalid demo OTP'}),401
    c=db(); u=c.execute('SELECT * FROM users WHERE email=?',(email,)).fetchone(); c.close()
    if not u: return jsonify({'error':'No demo account exists for this email'}),401
    session.clear(); session.update(user_id=u['id'],name=u['name'],role=u['role'])
    return jsonify({'user':{'name':u['name'],'role':u['role']}})

@app.post('/api/auth/request-otp')
def request_otp():
    data=request.get_json(force=True); email=(data.get('email') or '').strip().lower(); c=db(); u=c.execute('SELECT id FROM users WHERE email=?',(email,)).fetchone(); c.close()
    if not u: return jsonify({'error':'No demo account exists for this email'}),404
    # External SMS/WhatsApp is intentionally mocked. Return a fixed test OTP only outside production.
    if os.environ.get('APP_ENV')=='production': return jsonify({'message':'OTP delivery provider must be configured in production'}),503
    return jsonify({'message':'Demo OTP generated. Use the test code shown below.','demo_otp':os.environ.get('DEMO_OTP','246810')})

@app.post('/api/logout')
def logout(): session.clear(); return jsonify({'ok':True})

@app.get('/api/me')
def me():
    if not session.get('user_id'): return jsonify({'user':None})
    return jsonify({'user':{'id':session['user_id'],'name':session['name'],'role':session['role']}})

@app.get('/api/medicines')
@login_required
def medicines():
    q=request.args.get('q','').strip(); c=db(); rows=c.execute('SELECT * FROM medicines WHERE name LIKE ? OR generic_name LIKE ? ORDER BY name',('%'+q+'%','%'+q+'%')).fetchall(); c.close()
    return jsonify([dict(x) for x in rows])

@app.get('/api/profiles')
@roles('customer')
def profiles():
    c=db(); rows=c.execute('SELECT * FROM profiles WHERE user_id=?',(session['user_id'],)).fetchall(); c.close(); return jsonify([dict(x) for x in rows])

@app.post('/api/prescriptions')
@roles('customer')
def upload_prescription():
    f=request.files.get('file'); profile_id=request.form.get('profile_id')
    if not f or not f.filename: return jsonify({'error':'Choose a prescription file'}),400
    ext=f.filename.rsplit('.',1)[-1].lower() if '.' in f.filename else ''
    if ext not in ALLOWED: return jsonify({'error':'Only JPG, PNG, WEBP or PDF files are accepted'}),400
    c=db(); profile=c.execute('SELECT id FROM profiles WHERE id=? AND user_id=?',(profile_id,session['user_id'])).fetchone()
    if not profile: c.close(); return jsonify({'error':'Invalid family profile'}),403
    stored=uuid.uuid4().hex+'.'+ext; path=os.path.join(UPLOAD_DIR,stored); raw=f.read()
    # Encrypt the original before it is persisted. OCR operates on a short-lived temporary copy.
    with tempfile.NamedTemporaryFile(suffix='.'+ext, delete=False) as tmp: tmp.write(raw); tmp_path=tmp.name
    try: draft=extract_prescription(tmp_path,'.'+ext)
    finally:
        try: os.remove(tmp_path)
        except OSError: pass
    with open(path,'wb') as out: out.write(FERNET.encrypt(raw))
    cur=c.execute('INSERT INTO prescriptions(user_id,profile_id,filename,stored_name,status,extracted_text,ai_draft) VALUES(?,?,?,?,?,?,?)',(session['user_id'],profile_id,secure_filename(f.filename),stored,'uploaded',draft['text'],json.dumps(draft['items'])))
    audit(c,'prescription_uploaded','prescription',cur.lastrowid,'OCR engine: '+draft['engine']); c.commit(); pid=cur.lastrowid; c.close()
    return jsonify({'prescription_id':pid,'draft':draft,'message':'AI output is a draft only. A pharmacist must verify every prescription-required item.'})

@app.post('/api/orders/<int:order_id>/replace-prescription')
@roles('customer')
def replace_order_prescription(order_id):
    f=request.files.get('file')
    if not f or not f.filename: return jsonify({'error':'Choose a new prescription PDF or image.'}),400
    ext=f.filename.rsplit('.',1)[-1].lower() if '.' in f.filename else ''
    if ext not in ALLOWED: return jsonify({'error':'Only JPG, PNG, WEBP or PDF files are accepted.'}),400
    c=db(); order=c.execute('SELECT * FROM orders WHERE id=? AND user_id=?',(order_id,session['user_id'])).fetchone()
    if not order: c.close(); return jsonify({'error':'Order not found.'}),404
    if order['status']!='on_hold': c.close(); return jsonify({'error':'This order is not waiting for a replacement prescription.'}),409
    requested=c.execute("SELECT COUNT(*) FROM order_items WHERE order_id=? AND approval_status='reupload_requested'",(order_id,)).fetchone()[0]
    if not requested: c.close(); return jsonify({'error':'The pharmacist must request a clearer upload before a replacement can be submitted.'}),409
    stored=uuid.uuid4().hex+'.'+ext; path=os.path.join(UPLOAD_DIR,stored); raw=f.read()
    with tempfile.NamedTemporaryFile(suffix='.'+ext, delete=False) as tmp: tmp.write(raw); tmp_path=tmp.name
    try: draft=extract_prescription(tmp_path,'.'+ext)
    finally:
        try: os.remove(tmp_path)
        except OSError: pass
    with open(path,'wb') as out: out.write(FERNET.encrypt(raw))
    cur=c.execute("INSERT INTO prescriptions(user_id,profile_id,filename,stored_name,status,extracted_text,ai_draft) VALUES(?,?,?,?,'uploaded',?,?)",(session['user_id'],order['profile_id'],secure_filename(f.filename),stored,draft['text'],json.dumps(draft['items']))); npid=cur.lastrowid
    c.execute("UPDATE orders SET prescription_id=?,status='awaiting_verification',updated_at=CURRENT_TIMESTAMP WHERE id=?",(npid,order_id))
    c.execute("UPDATE order_items SET approval_status='pending',pharmacist_note=NULL,approved_qty=NULL WHERE order_id=? AND approval_status='reupload_requested'",(order_id,))
    audit(c,'replacement_prescription_uploaded','prescription',npid,'Replacement uploaded for order '+order['order_code']); c.commit(); c.close()
    return jsonify({'ok':True,'prescription_id':npid,'draft':draft,'message':'Replacement uploaded. The order has been sent back to the pharmacist for review.'})

@app.post('/api/orders')
@roles('customer')
def create_order():
    data=request.get_json(force=True); items=data.get('items',[]); profile_id=data.get('profile_id'); prescription_id=data.get('prescription_id')
    if not items or len(items)>20: return jsonify({'error':'Add between 1 and 20 items'}),400
    c=db(); profile=c.execute('SELECT id FROM profiles WHERE id=? AND user_id=?',(profile_id,session['user_id'])).fetchone()
    if not profile: c.close(); return jsonify({'error':'Invalid family profile'}),403
    clean=[]; total=0
    for x in items:
        try: mid=int(x['medicine_id']); qty=int(x['qty'])
        except Exception: c.close(); return jsonify({'error':'Invalid item or quantity'}),400
        if qty<1 or qty>100: c.close(); return jsonify({'error':'Quantity must be between 1 and 100'}),400
        m=c.execute('SELECT * FROM medicines WHERE id=?',(mid,)).fetchone()
        if not m: c.close(); return jsonify({'error':'Medicine not found'}),404
        allowed, policy_message=validate_online_item(m['schedule'], bool(prescription_id))
        if not allowed: c.close(); return jsonify({'error':m['name']+': '+policy_message}),400
        clean.append({'medicine_id':mid,'qty':qty,'price':m['price'],'schedule':m['schedule']}); total+=m['price']*qty
    if prescription_id:
        p=c.execute('SELECT id FROM prescriptions WHERE id=? AND user_id=? AND profile_id=?',(prescription_id,session['user_id'],profile_id)).fetchone()
        if not p: c.close(); return jsonify({'error':'Prescription not found for this profile'}),403
    store=route_store(c,clean)
    if not store: c.close(); return jsonify({'error':'No single store currently has all requested items in stock. Please reduce quantities or contact support.'}),409
    code='MR-'+datetime.now().strftime('%y%m%d')+'-'+uuid.uuid4().hex[:5].upper()
    # Any H/H1 line makes the entire order wait for pharmacist review. OTC-only orders can proceed.
    needs=any(i['schedule'] in ('H','H1') for i in clean); status='awaiting_verification' if needs else 'ready_to_pack'
    cur=c.execute('INSERT INTO orders(order_code,user_id,profile_id,store_id,status,total,prescription_id,payment_method) VALUES(?,?,?,?,?,?,?,?)',(code,session['user_id'],profile_id,store['id'],status,total,prescription_id,data.get('payment_method','COD_TEST'))); oid=cur.lastrowid
    for i in clean: c.execute('INSERT INTO order_items(order_id,medicine_id,qty,unit_price,schedule,approval_status) VALUES(?,?,?,?,?,?)',(oid,i['medicine_id'],i['qty'],i['price'],i['schedule'],'pending' if i['schedule'] in ('H','H1') else 'approved'))
    audit(c,'order_created','order',oid,'Routed to '+store['name']); c.commit(); c.close()
    return jsonify({'order_code':code,'status':status,'store':store['name'],'total':round(total,2)})

@app.get('/api/prescriptions/<int:prescription_id>/file')
@login_required
def prescription_file(prescription_id):
    c=db(); p=c.execute('SELECT * FROM prescriptions WHERE id=?',(prescription_id,)).fetchone()
    if not p: c.close(); return jsonify({'error':'Prescription not found'}),404
    if session['role']=='customer' and p['user_id']!=session['user_id']:
        c.close(); return jsonify({'error':'Not allowed'}),403
    if session['role'] not in ('customer','pharmacist','admin'):
        c.close(); return jsonify({'error':'Not allowed'}),403
    if not p['stored_name']: c.close(); return jsonify({'error':'No file is stored for this sample record'}),404
    path=os.path.join(UPLOAD_DIR,p['stored_name'])
    try:
        with open(path,'rb') as f: raw=FERNET.decrypt(f.read())
    except Exception:
        c.close(); return jsonify({'error':'Encrypted prescription could not be opened'}),500
    audit(c,'prescription_viewed','prescription',prescription_id,'Sensitive document decrypted for authorized view'); c.commit(); c.close()
    from flask import Response
    ext=p['stored_name'].rsplit('.',1)[-1].lower(); mime={'jpg':'image/jpeg','jpeg':'image/jpeg','png':'image/png','webp':'image/webp','pdf':'application/pdf'}.get(ext,'application/octet-stream')
    return Response(raw,mimetype=mime,headers={'Cache-Control':'no-store, private','Content-Disposition':'inline; filename="prescription.'+ext+'"'})

@app.get('/api/orders')
@login_required
def orders():
    c=db()
    if session['role']=='customer': rows=c.execute('''SELECT o.*,s.name store_name,p.name profile_name FROM orders o JOIN stores s ON s.id=o.store_id JOIN profiles p ON p.id=o.profile_id WHERE o.user_id=? ORDER BY o.id DESC''',(session['user_id'],)).fetchall()
    else: rows=c.execute('''SELECT o.*,s.name store_name,u.name customer_name,p.name profile_name FROM orders o JOIN stores s ON s.id=o.store_id JOIN users u ON u.id=o.user_id JOIN profiles p ON p.id=o.profile_id ORDER BY o.id DESC''').fetchall()
    result=[]
    for r in rows:
        d=dict(r)
        try: d['ai_draft_items']=json.loads(d.get('ai_draft') or '[]')
        except Exception: d['ai_draft_items']=[]
        d['items']=[dict(x) for x in c.execute('SELECT oi.*,m.name medicine_name FROM order_items oi JOIN medicines m ON m.id=oi.medicine_id WHERE oi.order_id=?',(r['id'],)).fetchall()]; result.append(d)
    c.close(); return jsonify(result)

@app.get('/api/queue')
@roles('pharmacist','admin')
def queue():
    c=db(); rows=c.execute('''SELECT o.*,u.name customer_name,p2.name profile_name,p.id prescription_id,p.filename,p.extracted_text,p.ai_draft,s.name store_name FROM orders o JOIN users u ON u.id=o.user_id JOIN profiles p2 ON p2.id=o.profile_id JOIN prescriptions p ON p.id=o.prescription_id JOIN stores s ON s.id=o.store_id WHERE o.status='awaiting_verification' ORDER BY o.created_at''').fetchall(); out=[]
    for r in rows:
        d=dict(r)
        try: d['ai_draft_items']=json.loads(d.get('ai_draft') or '[]')
        except Exception: d['ai_draft_items']=[]
        d['items']=[dict(x) for x in c.execute('SELECT oi.*,m.name medicine_name,m.generic_name,m.schedule medicine_schedule FROM order_items oi JOIN medicines m ON m.id=oi.medicine_id WHERE oi.order_id=?',(r['id'],)).fetchall()]; out.append(d)
    c.close(); return jsonify(out)

@app.post('/api/verify/<int:item_id>')
@roles('pharmacist','admin')
def verify(item_id):
    data=request.get_json(force=True); decision=data.get('decision'); reason=(data.get('reason') or '').strip(); qty=data.get('approved_qty')
    if decision not in ('approve','edit','reject','reupload'): return jsonify({'error':'Invalid decision'}),400
    c=db(); row=c.execute('SELECT oi.*,o.id order_id,o.order_code,o.status order_status,o.prescription_id,m.name medicine_name,m.schedule FROM order_items oi JOIN orders o ON o.id=oi.order_id JOIN medicines m ON m.id=oi.medicine_id WHERE oi.id=?',(item_id,)).fetchone()
    if not row: c.close(); return jsonify({'error':'Order item not found'}),404
    if row['order_status'] not in ('awaiting_verification','on_hold'): c.close(); return jsonify({'error':'This order is no longer open for verification'}),409
    if row['schedule'] in ('X','NARCOTIC'): c.close(); return jsonify({'error':'Prohibited item cannot be approved for online sale'}),403
    if decision in ('edit','reject','reupload') and not reason: c.close(); return jsonify({'error':'A reason is required'}),400
    if decision in ('approve','edit'):
        try: aq=int(qty if qty is not None else row['qty'])
        except: c.close(); return jsonify({'error':'Approved quantity must be numeric'}),400
        if aq<1 or aq>row['qty']: c.close(); return jsonify({'error':'Approved quantity must be between 1 and requested quantity'}),400
        target=row
        if decision=='edit':
            try: new_mid=int(data.get('medicine_id'))
            except: c.close(); return jsonify({'error':'Choose a valid replacement medicine'}),400
            target=c.execute('SELECT * FROM medicines WHERE id=?',(new_mid,)).fetchone()
            if not target: c.close(); return jsonify({'error':'Replacement medicine not found'}),404
            if target['schedule'] in ('X','NARCOTIC'): c.close(); return jsonify({'error':'Prohibited item cannot be selected'}),403
            if target['schedule'] in ('H','H1') and not row['prescription_id']: c.close(); return jsonify({'error':'A prescription is required for the edited item'}),400
        if target['schedule']=='H1':
            prescriber=(data.get('prescriber_name') or '').strip(); patient=(data.get('patient_name') or '').strip()
            if not prescriber or not patient: c.close(); return jsonify({'error':'H1 register requires prescriber and patient details'}),400
            c.execute('INSERT INTO h1_register(order_item_id,prescriber_name,patient_name,pharmacist_id) VALUES(?,?,?,?)',(item_id,prescriber,patient,session['user_id']))
        if decision=='edit':
            c.execute("UPDATE order_items SET medicine_id=?,schedule=?,unit_price=?,approval_status='approved',approved_qty=?,pharmacist_note=? WHERE id=?",(target['id'],target['schedule'],target['price'],aq,reason,item_id)); dec='edited'
        else:
            c.execute("UPDATE order_items SET approval_status='approved',approved_qty=?,pharmacist_note=? WHERE id=?",(aq,reason,item_id)); dec='approved'
    else:
        c.execute('UPDATE order_items SET approval_status=?,pharmacist_note=? WHERE id=?',('rejected' if decision=='reject' else 'reupload_requested',reason,item_id)); dec='rejected' if decision=='reject' else 'reupload_requested'
    c.execute('INSERT INTO verifications(order_item_id,pharmacist_id,decision,reason) VALUES(?,?,?,?)',(item_id,session['user_id'],dec,reason))
    remaining=c.execute("SELECT COUNT(*) FROM order_items WHERE order_id=? AND schedule IN ('H','H1') AND approval_status='pending'",(row['order_id'],)).fetchone()[0]
    bad=c.execute("SELECT COUNT(*) FROM order_items WHERE order_id=? AND approval_status IN ('rejected','reupload_requested')",(row['order_id'],)).fetchone()[0]
    if bad: c.execute("UPDATE orders SET status='on_hold',updated_at=CURRENT_TIMESTAMP WHERE id=?",(row['order_id'],))
    elif remaining==0: c.execute("UPDATE orders SET status='verified',updated_at=CURRENT_TIMESTAMP WHERE id=?",(row['order_id'],))
    audit(c,'prescription_'+dec,'order_item',item_id,reason); c.commit(); c.close()
    return jsonify({'ok':True,'decision':dec,'order_status':'on_hold' if bad else ('verified' if remaining==0 else 'awaiting_verification')})

@app.post('/api/orders/<int:order_id>/dispatch')
@roles('pharmacist','admin')
def dispatch(order_id):
    c=db(); o=c.execute('SELECT * FROM orders WHERE id=?',(order_id,)).fetchone()
    if not o: c.close(); return jsonify({'error':'Order not found'}),404
    policy_items=[dict(x) for x in c.execute('SELECT schedule,approval_status FROM order_items WHERE order_id=?',(order_id,)).fetchall()]
    allowed, policy_message=can_dispatch(policy_items,o['status'])
    if not allowed:
        c.close(); return jsonify({'error':'Dispatch blocked: '+policy_message}),409
    lines=c.execute("SELECT medicine_id,COALESCE(approved_qty,qty) qty FROM order_items WHERE order_id=?",(order_id,)).fetchall()
    for line in lines:
        inv=c.execute('SELECT stock FROM inventory WHERE store_id=? AND medicine_id=?',(o['store_id'],line['medicine_id'])).fetchone()
        if not inv or inv['stock']<line['qty']:
            c.close(); return jsonify({'error':'Dispatch blocked: store stock changed and is no longer sufficient.'}),409
    for line in lines: c.execute('UPDATE inventory SET stock=stock-?,updated_at=CURRENT_TIMESTAMP WHERE store_id=? AND medicine_id=?',(line['qty'],o['store_id'],line['medicine_id']))
    invoice='INV-'+datetime.now().strftime('%y%m%d')+'-'+str(order_id).zfill(4)
    c.execute("UPDATE orders SET status='dispatched',invoice_no=?,updated_at=CURRENT_TIMESTAMP WHERE id=?",(invoice,order_id)); audit(c,'order_dispatched','order',order_id,invoice); c.commit(); c.close(); return jsonify({'ok':True,'invoice_no':invoice})

@app.post('/api/refills')
@roles('customer')
def create_refill():
    d=request.get_json(force=True)
    try: mid=int(d['medicine_id']); qty=int(d['qty']); dose=float(d['daily_dose']); profile=int(d['profile_id'])
    except: return jsonify({'error':'Please provide valid medicine, quantity and daily dosage'}),400
    if qty<1 or qty>500 or dose<=0 or dose>20: return jsonify({'error':'Quantity or dosage is outside the supported demo range'}),400
    c=db(); ok=c.execute('SELECT id FROM profiles WHERE id=? AND user_id=?',(profile,session['user_id'])).fetchone(); med=c.execute('SELECT schedule FROM medicines WHERE id=?',(mid,)).fetchone()
    if not ok or not med: c.close(); return jsonify({'error':'Invalid profile or medicine'}),400
    if med['schedule'] in ('X','NARCOTIC'): c.close(); return jsonify({'error':'This item is not eligible for online refill'}),400
    cur=c.execute('INSERT INTO refill_subscriptions(user_id,profile_id,medicine_id,qty,daily_dose,start_date) VALUES(?,?,?,?,?,?)',(session['user_id'],profile,mid,qty,dose,date.today().isoformat())); c.commit(); c.close(); return jsonify({'ok':True,'id':cur.lastrowid})

@app.get('/api/refills')
@roles('customer')
def refills():
    c=db(); rows=c.execute('''SELECT r.*,m.name medicine_name,m.schedule,p.name profile_name,CAST(julianday(date(r.start_date, '+' || CAST(CAST(r.qty/r.daily_dose AS INTEGER) AS TEXT) || ' days'))-julianday('now') AS INTEGER) days_left FROM refill_subscriptions r JOIN medicines m ON m.id=r.medicine_id JOIN profiles p ON p.id=r.profile_id WHERE r.user_id=? AND r.active=1''',(session['user_id'],)).fetchall(); c.close()
    out=[]
    for r in rows:
        x=dict(r); x['days_left']=max(0,x['days_left'] or 0); x['reminder_due']=x['days_left']<=5; out.append(x)
    return jsonify(out)

@app.get('/api/dashboard')
@roles('pharmacist','admin')
def dashboard():
    c=db(); total=c.execute('SELECT COUNT(*) FROM orders').fetchone()[0]; pending=c.execute("SELECT COUNT(*) FROM orders WHERE status='awaiting_verification'").fetchone()[0]; rejected=c.execute("SELECT COUNT(*) FROM order_items WHERE approval_status IN ('rejected','reupload_requested')").fetchone()[0]
    stores=c.execute('SELECT s.name,COUNT(o.id) orders,COALESCE(SUM(o.total),0) revenue FROM stores s LEFT JOIN orders o ON o.store_id=s.id GROUP BY s.id ORDER BY orders DESC').fetchall()
    mins=sorted(r[0] for r in c.execute("SELECT (julianday(MIN(v.created_at))-julianday(o.created_at))*1440 FROM verifications v JOIN order_items oi ON oi.id=v.order_item_id JOIN orders o ON o.id=oi.order_id GROUP BY o.id").fetchall() if r[0] is not None)
    avg=(mins[len(mins)//2] if len(mins)%2 else (mins[len(mins)//2-1]+mins[len(mins)//2])/2) if mins else 0
    c.close(); return jsonify({'total_orders':total,'pending_verification':pending,'rejections':rejected,'median_placeholder_minutes':round(avg,1),'median_verification_minutes':round(avg,1),'stores':[dict(x) for x in stores]})

@app.post('/api/inventory/import')
@roles('pharmacist','admin')
def import_inventory():
    f=request.files.get('file')
    if not f: return jsonify({'error':'Upload a CSV file'}),400
    try:
        text=f.stream.read().decode('utf-8-sig'); reader=csv.DictReader(io.StringIO(text)); required={'store','sku','stock'}
        if not required.issubset(set(reader.fieldnames or [])): return jsonify({'error':'CSV must include store, sku, stock columns'}),400
        c=db(); count=0
        for row in reader:
            try: stock=int(row['stock'])
            except: continue
            if stock<0: continue
            s=c.execute('SELECT id FROM stores WHERE name=?',(row['store'].strip(),)).fetchone(); m=c.execute('SELECT id FROM medicines WHERE sku=?',(row['sku'].strip(),)).fetchone()
            if not s or not m: continue
            c.execute('INSERT INTO inventory(store_id,medicine_id,stock,updated_at) VALUES(?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(store_id,medicine_id) DO UPDATE SET stock=excluded.stock,updated_at=CURRENT_TIMESTAMP',(s['id'],m['id'],stock)); count+=1
        audit(c,'inventory_csv_imported','inventory',0,f'{count} rows'); c.commit(); c.close(); return jsonify({'ok':True,'updated_rows':count})
    except Exception as e: return jsonify({'error':'Could not read CSV: '+str(e)}),400

@app.get('/data/inventory_sample.csv')
def sample_inventory(): return send_from_directory(os.path.join(BASE,'data'),'inventory_sample.csv',as_attachment=True)

@app.get('/api/health')
def health(): return jsonify({'status':'ok','mode':'demo','database':'sqlite'})

@app.errorhandler(500)
def server_error(e):
    app.logger.exception('Unhandled error')
    if request.path.startswith('/api/'): return jsonify({'error':'Server error. Check the server log for details.'}),500
    return 'Server error',500

@app.errorhandler(413)
def too_large(e): return jsonify({'error':'File exceeds the 8 MB upload limit'}),413

if __name__=='__main__': app.run(host='127.0.0.1',port=int(os.environ.get('PORT',5000)),debug=os.environ.get('FLASK_DEBUG')=='1')