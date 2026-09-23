import os, json, hmac, hashlib, sqlite3, time, asyncio
from urllib.parse import parse_qsl
from pathlib import Path
import httpx
from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

BASE = Path(__file__).parent
DB = BASE / "ikosy.db"
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
BOT_USERNAME = os.getenv("BOT_USERNAME", "ikosy_bot")
WEBAPP_URL = os.getenv("WEBAPP_URL", "")

app = FastAPI(title="ikosy")
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")

def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c

def init_db():
    c = db()
    c.executescript("""
    CREATE TABLE IF NOT EXISTS users(
      id INTEGER PRIMARY KEY, username TEXT, first_name TEXT, photo_url TEXT,
      city TEXT DEFAULT 'Москва', created_at INTEGER
    );
    CREATE TABLE IF NOT EXISTS ads(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, title TEXT, price INTEGER,
      category TEXT, city TEXT, description TEXT, image TEXT, status TEXT DEFAULT 'active',
      created_at INTEGER
    );
    CREATE TABLE IF NOT EXISTS favorites(
      user_id INTEGER, ad_id INTEGER, PRIMARY KEY(user_id, ad_id)
    );
    CREATE TABLE IF NOT EXISTS notifications(
      id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, text TEXT, created_at INTEGER,
      read INTEGER DEFAULT 0
    );
    """)
    c.commit()
    c.close()

def validate_init_data(init_data: str):
    if not init_data or not BOT_TOKEN:
        return None
    try:
        pairs = dict(parse_qsl(init_data, keep_blank_values=True))
        received = pairs.pop("hash", None)
        if not received:
            return None
        data_check = "\n".join(f"{k}={pairs[k]}" for k in sorted(pairs))
        secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, received):
            return None
        auth_date = int(pairs.get("auth_date", "0"))
        if time.time() - auth_date > 86400:
            return None
        return json.loads(pairs.get("user", "{}"))
    except Exception:
        return None

def demo_user():
    return {"id": 100001, "first_name": "Гость", "username": "guest"}

def ensure_user(u):
    c = db()
    c.execute("""INSERT INTO users(id,username,first_name,photo_url,created_at)
                VALUES(?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET username=excluded.username,
                first_name=excluded.first_name, photo_url=excluded.photo_url""",
              (u["id"], u.get("username"), u.get("first_name",""), u.get("photo_url"), int(time.time())))
    c.commit(); c.close()

@app.on_event("startup")
async def startup():
    init_db()
    if BOT_TOKEN and WEBAPP_URL:
        asyncio.create_task(bot_loop())

@app.get("/", response_class=HTMLResponse)
async def index():
    return (BASE/"static"/"index.html").read_text(encoding="utf-8")

async def get_user(request):
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    u = validate_init_data(init_data) or demo_user()
    ensure_user(u)
    return u

@app.get("/api/bootstrap")
async def bootstrap(request: Request):
    u = await get_user(request)
    c = db()
    ads = c.execute("SELECT * FROM ads WHERE status='active' ORDER BY created_at DESC LIMIT 30").fetchall()
    favs = [r["ad_id"] for r in c.execute("SELECT ad_id FROM favorites WHERE user_id=?", (u["id"],))]
    cats = ["Авто","Телефоны","Электроника","Одежда","Недвижимость","Услуги","Игры","Для дома","Хобби","Другое"]
    return {"user":u, "ads":[dict(x) for x in ads], "favorites":favs, "categories":cats}

@app.get("/api/search")
async def search(request: Request, q: str="", category: str="", city: str=""):
    await get_user(request)
    c=db()
    sql="SELECT * FROM ads WHERE status='active'"
    args=[]
    if q:
        sql += " AND (title LIKE ? OR description LIKE ?)"
        args += [f"%{q}%", f"%{q}%"]
    if category:
        sql += " AND category=?"; args.append(category)
    if city:
        sql += " AND city=?"; args.append(city)
    sql += " ORDER BY created_at DESC LIMIT 50"
    return {"ads":[dict(x) for x in c.execute(sql,args).fetchall()]}

@app.post("/api/ads")
async def create_ad(request: Request):
    u=await get_user(request)
    data=await request.json()
    required=["title","price","category","city","description"]
    if any(not str(data.get(k,"")).strip() for k in required):
        return JSONResponse({"error":"Заполните все обязательные поля"}, status_code=400)
    c=db()
    cur=c.execute("""INSERT INTO ads(user_id,title,price,category,city,description,image,created_at)
                     VALUES(?,?,?,?,?,?,?,?)""",
        (u["id"],data["title"],int(data["price"]),data["category"],data["city"],
         data["description"],data.get("image",""),int(time.time())))
    c.execute("INSERT INTO notifications(user_id,text,created_at) VALUES(?,?,?)",
              (u["id"],"Объявление опубликовано",int(time.time())))
    c.commit()
    return {"ok":True,"id":cur.lastrowid}

@app.delete("/api/ads/{ad_id}")
async def delete_ad(request: Request, ad_id:int):
    u=await get_user(request); c=db()
    c.execute("UPDATE ads SET status='deleted' WHERE id=? AND user_id=?", (ad_id,u["id"]))
    c.commit(); return {"ok":True}

@app.post("/api/favorites/{ad_id}")
async def favorite(request: Request, ad_id:int):
    u=await get_user(request); c=db()
    exists=c.execute("SELECT 1 FROM favorites WHERE user_id=? AND ad_id=?",(u["id"],ad_id)).fetchone()
    if exists:
        c.execute("DELETE FROM favorites WHERE user_id=? AND ad_id=?",(u["id"],ad_id)); state=False
    else:
        c.execute("INSERT OR IGNORE INTO favorites VALUES(?,?)",(u["id"],ad_id)); state=True
    c.commit(); return {"favorite":state}

@app.get("/api/my-ads")
async def my_ads(request: Request):
    u=await get_user(request); c=db()
    rows=c.execute("SELECT * FROM ads WHERE user_id=? AND status!='deleted' ORDER BY created_at DESC",(u["id"],)).fetchall()
    return {"ads":[dict(x) for x in rows]}

@app.get("/api/notifications")
async def notifications(request: Request):
    u=await get_user(request); c=db()
    rows=c.execute("SELECT * FROM notifications WHERE user_id=? ORDER BY created_at DESC LIMIT 50",(u["id"],)).fetchall()
    return {"notifications":[dict(x) for x in rows]}

@app.get("/api/admin")
async def admin(request: Request):
    u=await get_user(request)
    # Set ADMIN_IDS="123,456" in environment for real admin access.
    admins={x.strip() for x in os.getenv("ADMIN_IDS","").split(",") if x.strip()}
    if str(u["id"]) not in admins: return JSONResponse({"error":"forbidden"},status_code=403)
    c=db()
    return {"users":c.execute("SELECT COUNT(*) n FROM users").fetchone()["n"],
            "ads":c.execute("SELECT COUNT(*) n FROM ads WHERE status='active'").fetchone()["n"],
            "all_ads":[dict(x) for x in c.execute("SELECT * FROM ads ORDER BY created_at DESC LIMIT 100")]}

async def bot_api(method, payload):
    if not BOT_TOKEN: return
    url=f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    async with httpx.AsyncClient(timeout=20) as client:
        await client.post(url,json=payload)

async def bot_loop():
    offset=0
    while True:
        try:
            async with httpx.AsyncClient(timeout=35) as client:
                r=await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                                   params={"timeout":30,"offset":offset})
                data=r.json()
            for upd in data.get("result",[]):
                offset=upd["update_id"]+1
                msg=upd.get("message",{})
                chat=msg.get("chat",{})
                text=msg.get("text","")
                if text.startswith("/start"):
                    keyboard={"inline_keyboard":[[{"text":"📋 Открыть ikosy","web_app":{"url":WEBAPP_URL}}]]}
                    await bot_api("sendMessage",{"chat_id":chat.get("id"),
                      "text":"👋 Добро пожаловать в *ikosy* — сервис объявлений в Telegram.\\n\\nПокупай, продавай и находи нужное рядом с собой.",
                      "parse_mode":"Markdown","reply_markup":keyboard})
        except Exception:
            await asyncio.sleep(3)

if __name__=="__main__":
    import uvicorn
    uvicorn.run("app:app",host="0.0.0.0",port=int(os.getenv("PORT","8000")),reload=True)
