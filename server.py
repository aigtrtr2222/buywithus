"""나 혼자 안산다 | Buy With Us — 공동구매 게시판 서버 (FastAPI + SQLite).

로그인 없이 브라우저마다 만든 무작위 토큰(X-BWU-Token)으로 작성자/참여자를 구분한다.
모집글마다 참여자끼리만 쓰는 '수다방'(채팅)이 있고, 오픈채팅 링크(선택)도 참여자에게만 응답한다.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import sqlite3
import threading
import time
from collections import defaultdict, deque
from contextlib import contextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = Path(os.environ.get("BWU_DATA_DIR", BASE_DIR / "data"))
DB_PATH = DATA_DIR / "buywithus.sqlite3"
PUBLIC_DIR = BASE_DIR / "public"

CATS = {"veg", "fruit", "meat", "dairy", "daily"}
KAKAO_RE = re.compile(r"^https://open\.kakao\.com/[A-Za-z0-9/_\-?=&.%]+$")
TOKEN_RE = re.compile(r"^[A-Za-z0-9_-]{32,128}$")
DAY_MS = 24 * 3600 * 1000
KEEP_AFTER_MEET_MS = DAY_MS      # 만남 시간 하루 뒤까지는 게시판에 남김
ROOM_KEEP_MS = 3 * DAY_MS        # 수다방은 만남 후 3일까지 (정산 이야기용)
CHAT_KEEP = 300                  # 방마다 남길 최근 메시지 수
CHAT_PAGE = 80                   # 방을 처음 열 때 보여줄 메시지 수
CHAT_MAX_LEN = 300

SCHEMA = """
CREATE TABLE IF NOT EXISTS posts (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  cat        TEXT NOT NULL,
  title      TEXT NOT NULL,
  item       TEXT NOT NULL,
  price      INTEGER NOT NULL,
  max        INTEGER NOT NULL,
  place      TEXT NOT NULL,
  area       TEXT NOT NULL,
  meet       INTEGER NOT NULL,
  deadline   INTEGER NOT NULL,
  leader     TEXT NOT NULL,
  kakao      TEXT NOT NULL DEFAULT '',
  memo       TEXT NOT NULL DEFAULT '',
  owner      TEXT NOT NULL,
  created    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS members (
  post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  token      TEXT NOT NULL,
  joined_at  INTEGER NOT NULL,
  name       TEXT NOT NULL DEFAULT '',
  emoji      TEXT NOT NULL DEFAULT '',
  PRIMARY KEY (post_id, token)
);
CREATE INDEX IF NOT EXISTS idx_posts_meet ON posts(meet);
CREATE INDEX IF NOT EXISTS idx_members_token ON members(token);
CREATE TABLE IF NOT EXISTS room_messages (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  token      TEXT NOT NULL DEFAULT '',
  name       TEXT NOT NULL DEFAULT '',
  emoji      TEXT NOT NULL DEFAULT '',
  kind       TEXT NOT NULL DEFAULT 'msg',
  text       TEXT NOT NULL,
  created    INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_room_messages ON room_messages(post_id, id);
CREATE TABLE IF NOT EXISTS unlocks (
  token      TEXT PRIMARY KEY,
  created    INTEGER NOT NULL
);
DROP TABLE IF EXISTS messages;
"""
# kind: msg(사람이 쓴 말) | sys(입장·퇴장 안내).  messages = 예전 전체 공개 채팅 테이블(폐기)

# ---------- 수다방 닉네임: 랜덤 형용사 + 야채/과일 (한 방 안에서 겹치지 않게) ----------
ADJECTIVES = [
    "아삭한", "싱싱한", "새콤한", "달콤한", "말랑한", "통통한", "수줍은", "용감한",
    "졸린", "배고픈", "반짝이는", "느긋한", "부지런한", "씩씩한", "엉뚱한", "다정한",
    "포근한", "시원한", "상큼한", "고소한", "동글동글한", "튼튼한", "명랑한", "조용한",
    "알뜰한", "꼼꼼한", "수다쟁이", "멋쟁이", "깔끔한", "행복한",
]
PRODUCE = [
    ("당근", "🥕"), ("양파", "🧅"), ("토마토", "🍅"), ("브로콜리", "🥦"), ("감자", "🥔"),
    ("고구마", "🍠"), ("옥수수", "🌽"), ("가지", "🍆"), ("오이", "🥒"), ("파프리카", "🫑"),
    ("마늘", "🧄"), ("버섯", "🍄"), ("양배추", "🥬"), ("고추", "🌶️"), ("완두콩", "🫛"),
    ("사과", "🍎"), ("배", "🍐"), ("귤", "🍊"), ("레몬", "🍋"), ("바나나", "🍌"),
    ("수박", "🍉"), ("포도", "🍇"), ("딸기", "🍓"), ("블루베리", "🫐"), ("체리", "🍒"),
    ("복숭아", "🍑"), ("망고", "🥭"), ("파인애플", "🍍"), ("키위", "🥝"), ("아보카도", "🥑"),
]


# 🥚 이스터에그(바구니 합치기)에서 🎃 호박을 만든 사람은 수다방 프로필이 동물로 바뀜
ANIMALS = [
    ("강아지", "🐶"), ("고양이", "🐱"), ("토끼", "🐰"), ("햄스터", "🐹"), ("다람쥐", "🐿️"),
    ("고슴도치", "🦔"), ("곰", "🐻"), ("판다", "🐼"), ("코알라", "🐨"), ("호랑이", "🐯"),
    ("사자", "🦁"), ("돼지", "🐷"), ("개구리", "🐸"), ("원숭이", "🐵"), ("병아리", "🐤"),
    ("펭귄", "🐧"), ("여우", "🦊"), ("너구리", "🦝"), ("수달", "🦦"), ("거북이", "🐢"),
    ("부엉이", "🦉"), ("고래", "🐳"), ("오리", "🦆"), ("양", "🐑"),
]


def is_unlocked(db: sqlite3.Connection, token_h: str) -> bool:
    return db.execute("SELECT 1 FROM unlocks WHERE token=?", (token_h,)).fetchone() is not None


def pick_nickname(db: sqlite3.Connection, post_id: int, token_h: str | None = None, adjective: str | None = None) -> dict:
    pool = ANIMALS if token_h and is_unlocked(db, token_h) else PRODUCE
    used = {r[0] for r in db.execute("SELECT emoji FROM members WHERE post_id=?", (post_id,))}
    choices = [p for p in pool if p[1] not in used] or pool
    name, emoji = secrets.choice(choices)
    return {"name": f"{adjective or secrets.choice(ADJECTIVES)} {name}", "emoji": emoji}


def now_ms() -> int:
    return int(time.time() * 1000)


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute("PRAGMA journal_mode=WAL")
        cols = {r[1] for r in db.execute("PRAGMA table_info(members)")}
        if cols and "name" not in cols:  # 예전 DB 업그레이드
            db.execute("ALTER TABLE members ADD COLUMN name TEXT NOT NULL DEFAULT ''")
            db.execute("ALTER TABLE members ADD COLUMN emoji TEXT NOT NULL DEFAULT ''")
        db.executescript(SCHEMA)
        for post_id, token in db.execute("SELECT post_id, token FROM members WHERE name = ''").fetchall():
            who = pick_nickname(db, post_id)
            db.execute("UPDATE members SET name=?, emoji=? WHERE post_id=? AND token=?",
                       (who["name"], who["emoji"], post_id, token))


@contextmanager
def connect(write: bool = False):
    db = sqlite3.connect(DB_PATH, timeout=10, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA foreign_keys=ON")
    try:
        if write:
            db.execute("BEGIN IMMEDIATE")  # 동시 참여 시 인원 초과 방지
        yield db
        if write:
            db.execute("COMMIT")
    except BaseException:
        if write and db.in_transaction:
            db.execute("ROLLBACK")
        raise
    finally:
        db.close()


# ---------- 간단한 IP별 요청 제한 ----------
_hits: dict[tuple[str, str], deque] = defaultdict(deque)
_hits_lock = threading.Lock()
LIMITS = {"post": (5, 3600), "join": (30, 3600), "chat": (30, 60)}  # (횟수, 초)


def rate_limit(request: Request, kind: str) -> None:
    count, window = LIMITS[kind]
    key = (request.client.host if request.client else "?", kind)
    t = time.monotonic()
    with _hits_lock:
        q = _hits[key]
        while q and t - q[0] > window:
            q.popleft()
        if len(q) >= count:
            raise HTTPException(429, "요청이 너무 많아요. 잠시 후 다시 시도해주세요.")
        q.append(t)


def token_hash(token: str | None) -> str:
    if not token or not TOKEN_RE.match(token):
        raise HTTPException(400, "브라우저 식별값이 없어요. 새로고침 후 다시 시도해주세요.")
    return hashlib.sha256(token.encode()).hexdigest()


def optional_hash(token: str | None) -> str | None:
    return hashlib.sha256(token.encode()).hexdigest() if token and TOKEN_RE.match(token) else None


# ---------- 모집글 ----------
def serialize(row: sqlite3.Row, me: str | None) -> dict:
    mine = bool(row["mine"])
    return {
        "id": row["id"],
        "cat": row["cat"],
        "title": row["title"],
        "item": row["item"],
        "price": row["price"],
        "max": row["max"],
        "joined": row["joined"],
        "place": row["place"],
        "area": row["area"],
        "meet": row["meet"],
        "deadline": row["deadline"],
        "leader": row["leader"],
        "memo": row["memo"],
        "created": row["created"],
        "mine": mine,
        "isLeader": me is not None and row["owner"] == me,
        "kakao": (row["kakao"] or None) if mine else None,  # 참여자에게만 공개
    }


POST_QUERY = """
SELECT p.*,
       (SELECT COUNT(*) FROM members m WHERE m.post_id = p.id) AS joined,
       EXISTS(SELECT 1 FROM members m WHERE m.post_id = p.id AND m.token = :me) AS mine
FROM posts p
"""


def fetch_post(db: sqlite3.Connection, post_id: int, me: str | None) -> sqlite3.Row:
    row = db.execute(POST_QUERY + " WHERE p.id = :id", {"me": me, "id": post_id}).fetchone()
    if not row:
        raise HTTPException(404, "없는 모집글이에요.")
    return row


def system_message(db: sqlite3.Connection, post_id: int, text: str) -> None:
    db.execute("INSERT INTO room_messages (post_id, kind, text, created) VALUES (?,?,?,?)",
               (post_id, "sys", text, now_ms()))


def add_member(db: sqlite3.Connection, post_id: int, token_h: str, leader: bool = False) -> None:
    who = pick_nickname(db, post_id, token_h)
    db.execute("INSERT INTO members (post_id, token, joined_at, name, emoji) VALUES (?,?,?,?,?)",
               (post_id, token_h, now_ms(), who["name"], who["emoji"]))
    if leader:
        system_message(db, post_id, f"👑 리더 {who['emoji']} {who['name']}님이 수다방을 열었어요. 참여한 사람끼리만 보여요.")
    else:
        system_message(db, post_id, f"{who['emoji']} {who['name']}님이 들어왔어요")


class PostIn(BaseModel):
    cat: str
    title: str = Field(min_length=1, max_length=40)
    item: str = Field(min_length=1, max_length=60)
    price: int = Field(ge=0, le=10_000_000)
    max: int = Field(ge=2, le=10)
    place: str = Field(min_length=1, max_length=60)
    area: str = Field(min_length=1, max_length=20)
    meet: int
    deadline: int
    leader: str = Field(min_length=1, max_length=12)
    kakao: str = Field(default="", max_length=200)  # 선택: 수다방이 기본 연락 수단
    memo: str = Field(default="", max_length=200)


app = FastAPI(title="Buy With Us", docs_url=None, redoc_url=None, openapi_url=None)
init_db()


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["X-Frame-Options"] = "DENY"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


@app.exception_handler(HTTPException)
async def http_error(_: Request, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/posts")
def list_posts(x_bwu_token: str | None = Header(default=None)):
    me = optional_hash(x_bwu_token)
    with connect() as db:
        rows = db.execute(
            POST_QUERY + " WHERE p.meet > :since ORDER BY p.deadline",
            {"me": me, "since": now_ms() - KEEP_AFTER_MEET_MS},
        ).fetchall()
    return {"posts": [serialize(r, me) for r in rows], "now": now_ms()}


@app.post("/api/posts", status_code=201)
def create_post(body: PostIn, request: Request, x_bwu_token: str | None = Header(default=None)):
    me = token_hash(x_bwu_token)
    data = body.model_dump()
    for k in ("title", "item", "place", "area", "leader", "kakao", "memo"):
        data[k] = data[k].strip()
    for k in ("title", "item", "place", "area", "leader"):
        if not data[k]:
            raise HTTPException(422, "빈 칸을 채워주세요.")
    if data["cat"] not in CATS:
        raise HTTPException(422, "카테고리를 골라주세요.")
    if data["kakao"] and not KAKAO_RE.match(data["kakao"]):
        raise HTTPException(422, "오픈카카오톡 링크는 https://open.kakao.com/... 형식이어야 해요.")
    t = now_ms()
    if data["deadline"] <= t:
        raise HTTPException(422, "모집 마감 시간은 지금 이후여야 해요.")
    if data["meet"] <= data["deadline"]:
        raise HTTPException(422, "만날 시간은 모집 마감 이후여야 해요.")
    if data["meet"] > t + 30 * DAY_MS:
        raise HTTPException(422, "만날 시간은 30일 이내로 잡아주세요.")
    rate_limit(request, "post")

    with connect(write=True) as db:
        cur = db.execute(
            """INSERT INTO posts (cat,title,item,price,max,place,area,meet,deadline,leader,kakao,memo,owner,created)
               VALUES (:cat,:title,:item,:price,:max,:place,:area,:meet,:deadline,:leader,:kakao,:memo,:owner,:created)""",
            {**data, "owner": me, "created": t},
        )
        post_id = cur.lastrowid
        add_member(db, post_id, me, leader=True)  # 작성자 = 리더
        row = fetch_post(db, post_id, me)
    return serialize(row, me)


@app.post("/api/posts/{post_id}/join")
def join_post(post_id: int, request: Request, x_bwu_token: str | None = Header(default=None)):
    me = token_hash(x_bwu_token)
    with connect(write=True) as db:
        row = fetch_post(db, post_id, me)
        if not row["mine"]:
            if row["deadline"] <= now_ms():
                raise HTTPException(409, "이미 마감된 공구예요.")
            if row["joined"] >= row["max"]:
                raise HTTPException(409, "인원이 다 찼어요.")
            rate_limit(request, "join")
            add_member(db, post_id, me)
            row = fetch_post(db, post_id, me)
    return serialize(row, me)


@app.delete("/api/posts/{post_id}/join")
def leave_post(post_id: int, x_bwu_token: str | None = Header(default=None)):
    me = token_hash(x_bwu_token)
    with connect(write=True) as db:
        row = fetch_post(db, post_id, me)
        if row["owner"] == me:
            raise HTTPException(409, "리더는 참여 취소 대신 모집글을 삭제해주세요.")
        who = db.execute("SELECT name, emoji FROM members WHERE post_id=? AND token=?", (post_id, me)).fetchone()
        if who:
            db.execute("DELETE FROM members WHERE post_id=? AND token=?", (post_id, me))
            system_message(db, post_id, f"{who['emoji']} {who['name']}님이 나갔어요")
        row = fetch_post(db, post_id, me)
    return serialize(row, me)


@app.delete("/api/posts/{post_id}")
def delete_post(post_id: int, x_bwu_token: str | None = Header(default=None)):
    me = token_hash(x_bwu_token)
    with connect(write=True) as db:
        row = fetch_post(db, post_id, me)
        if row["owner"] != me:
            raise HTTPException(403, "작성자만 삭제할 수 있어요.")
        db.execute("DELETE FROM posts WHERE id=?", (post_id,))  # 수다방·참여자도 함께 삭제
    return {"ok": True}


# ---------- 공구별 수다방 (참여자끼리만) ----------
def require_member(db: sqlite3.Connection, post_id: int, me: str) -> sqlite3.Row:
    post = db.execute("SELECT id, owner FROM posts WHERE id=?", (post_id,)).fetchone()
    if not post:
        raise HTTPException(404, "없는 모집글이에요.")
    if not db.execute("SELECT 1 FROM members WHERE post_id=? AND token=?", (post_id, me)).fetchone():
        raise HTTPException(403, "이 공구에 참여한 사람만 수다방에 들어갈 수 있어요.")
    return post


def msg_row(row: sqlite3.Row, me: str, owner: str) -> dict:
    is_msg = row["kind"] == "msg"
    return {"id": row["id"], "kind": row["kind"], "name": row["name"], "emoji": row["emoji"],
            "text": row["text"], "ts": row["created"],
            "mine": is_msg and row["token"] == me, "leader": is_msg and row["token"] == owner}


class ChatIn(BaseModel):
    text: str = Field(min_length=1, max_length=CHAT_MAX_LEN)


@app.get("/api/rooms")
def my_rooms(x_bwu_token: str | None = Header(default=None)):
    """내가 참여한 공구 수다방 목록 + 마지막 메시지."""
    me = optional_hash(x_bwu_token)
    if not me:
        return {"rooms": []}
    with connect() as db:
        rows = db.execute(
            """SELECT p.id, p.title, p.cat, p.max, p.meet, p.owner, m.name AS my_name, m.emoji AS my_emoji,
                      (SELECT COUNT(*) FROM members x WHERE x.post_id = p.id) AS joined,
                      (SELECT MAX(id) FROM room_messages r WHERE r.post_id = p.id) AS last_id
               FROM members m JOIN posts p ON p.id = m.post_id
               WHERE m.token = ? AND p.meet > ?""",
            (me, now_ms() - ROOM_KEEP_MS),
        ).fetchall()
        rooms = []
        for r in rows:
            last = db.execute("SELECT * FROM room_messages WHERE id=?", (r["last_id"],)).fetchone() if r["last_id"] else None
            rooms.append({
                "id": r["id"], "title": r["title"], "cat": r["cat"], "joined": r["joined"], "max": r["max"],
                "meet": r["meet"], "isLeader": r["owner"] == me,
                "me": {"name": r["my_name"], "emoji": r["my_emoji"]},
                "last": msg_row(last, me, r["owner"]) if last else None,
            })
    rooms.sort(key=lambda x: -(x["last"]["id"] if x["last"] else 0))
    return {"rooms": rooms}


@app.get("/api/posts/{post_id}/chat")
def room_messages(post_id: int, after: int = 0, x_bwu_token: str | None = Header(default=None)):
    me = token_hash(x_bwu_token)
    with connect() as db:
        post = require_member(db, post_id, me)
        if after > 0:
            rows = db.execute("SELECT * FROM room_messages WHERE post_id=? AND id>? ORDER BY id LIMIT 200",
                              (post_id, after)).fetchall()
        else:
            rows = db.execute("SELECT * FROM room_messages WHERE post_id=? ORDER BY id DESC LIMIT ?",
                              (post_id, CHAT_PAGE)).fetchall()[::-1]
        members = [
            {"name": m["name"], "emoji": m["emoji"], "leader": m["token"] == post["owner"], "me": m["token"] == me}
            for m in db.execute("SELECT token, name, emoji FROM members WHERE post_id=? ORDER BY joined_at", (post_id,))
        ]
    return {"members": members, "messages": [msg_row(r, me, post["owner"]) for r in rows]}


@app.post("/api/posts/{post_id}/chat", status_code=201)
def room_send(post_id: int, body: ChatIn, request: Request, x_bwu_token: str | None = Header(default=None)):
    me = token_hash(x_bwu_token)
    text = " ".join(body.text.split())  # 줄바꿈·연속 공백 정리
    if not text:
        raise HTTPException(422, "메시지를 입력해주세요.")
    rate_limit(request, "chat")
    with connect(write=True) as db:
        post = require_member(db, post_id, me)
        who = db.execute("SELECT name, emoji FROM members WHERE post_id=? AND token=?", (post_id, me)).fetchone()
        cur = db.execute(
            "INSERT INTO room_messages (post_id, token, name, emoji, kind, text, created) VALUES (?,?,?,?,?,?,?)",
            (post_id, me, who["name"], who["emoji"], "msg", text, now_ms()))
        db.execute("""DELETE FROM room_messages WHERE post_id=? AND id NOT IN
                      (SELECT id FROM room_messages WHERE post_id=? ORDER BY id DESC LIMIT ?)""",
                   (post_id, post_id, CHAT_KEEP))
        row = db.execute("SELECT * FROM room_messages WHERE id=?", (cur.lastrowid,)).fetchone()
    return msg_row(row, me, post["owner"])


# ---------- 🥚 이스터에그 클리어 보상 ----------
@app.get("/api/egg")
def egg_status(x_bwu_token: str | None = Header(default=None)):
    me = optional_hash(x_bwu_token)
    with connect() as db:
        return {"unlocked": bool(me) and is_unlocked(db, me)}


@app.post("/api/egg/clear")
def egg_clear(x_bwu_token: str | None = Header(default=None)):
    """🎃 호박을 만들면 호출. 참여 중인 모든 수다방 프로필을 동물로 바꾸고 방에 안내."""
    me = token_hash(x_bwu_token)
    with connect(write=True) as db:
        if is_unlocked(db, me):
            return {"unlocked": True, "already": True}
        db.execute("INSERT INTO unlocks (token, created) VALUES (?,?)", (me, now_ms()))
        rows = db.execute("SELECT post_id, name, emoji FROM members WHERE token=?", (me,)).fetchall()
        for r in rows:
            adjective = r["name"].split(" ")[0] if " " in r["name"] else None
            # 내 자리는 빼고 겹치지 않는 동물 고르기
            db.execute("UPDATE members SET emoji='' WHERE post_id=? AND token=?", (r["post_id"], me))
            who = pick_nickname(db, r["post_id"], me, adjective)
            db.execute("UPDATE members SET name=?, emoji=? WHERE post_id=? AND token=?",
                       (who["name"], who["emoji"], r["post_id"], me))
            db.execute("UPDATE room_messages SET name=?, emoji=? WHERE post_id=? AND token=? AND kind='msg'",
                       (who["name"], who["emoji"], r["post_id"], me))
            system_message(db, r["post_id"],
                           f"🎃 {r['emoji']} {r['name']}님이 숨은 게임을 클리어하고 {who['emoji']} {who['name']}(으)로 변신했어요!")
    return {"unlocked": True, "already": False, "rooms": len(rows)}


app.mount("/", StaticFiles(directory=PUBLIC_DIR, html=True), name="public")
