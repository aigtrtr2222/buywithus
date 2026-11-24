"""나 혼자 안산다 | Buy With Us — 공동구매 게시판 서버 (FastAPI + SQLite).

로그인 없이 브라우저마다 만든 무작위 토큰(X-BWU-Token)으로 작성자/참여자를 구분한다.
오픈채팅 링크는 그 글에 참여한 토큰에게만 응답한다.
"""
from __future__ import annotations

import hashlib
import os
import re
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
KEEP_AFTER_MEET_MS = DAY_MS  # 만남 시간 하루 뒤까지는 목록에 남김

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
  kakao      TEXT NOT NULL,
  memo       TEXT NOT NULL DEFAULT '',
  owner      TEXT NOT NULL,
  created    INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS members (
  post_id    INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
  token      TEXT NOT NULL,
  joined_at  INTEGER NOT NULL,
  PRIMARY KEY (post_id, token)
);
CREATE INDEX IF NOT EXISTS idx_posts_meet ON posts(meet);
CREATE INDEX IF NOT EXISTS idx_members_token ON members(token);
"""


def now_ms() -> int:
    return int(time.time() * 1000)


def init_db() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(DB_PATH) as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.executescript(SCHEMA)


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
LIMITS = {"post": (5, 3600), "join": (30, 3600)}  # (횟수, 초)


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
        "kakao": row["kakao"] if mine else None,  # 참여자에게만 공개
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
    kakao: str = Field(max_length=200)
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
    if not KAKAO_RE.match(data["kakao"]):
        raise HTTPException(422, "오픈카카오톡 링크(https://open.kakao.com/...)를 넣어주세요.")
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
        db.execute("INSERT INTO members VALUES (?,?,?)", (post_id, me, t))  # 작성자 = 리더
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
            db.execute("INSERT INTO members VALUES (?,?,?)", (post_id, me, now_ms()))
            row = fetch_post(db, post_id, me)
    return serialize(row, me)


@app.delete("/api/posts/{post_id}/join")
def leave_post(post_id: int, x_bwu_token: str | None = Header(default=None)):
    me = token_hash(x_bwu_token)
    with connect(write=True) as db:
        row = fetch_post(db, post_id, me)
        if row["owner"] == me:
            raise HTTPException(409, "리더는 참여 취소 대신 모집글을 삭제해주세요.")
        db.execute("DELETE FROM members WHERE post_id=? AND token=?", (post_id, me))
        row = fetch_post(db, post_id, me)
    return serialize(row, me)


@app.delete("/api/posts/{post_id}")
def delete_post(post_id: int, x_bwu_token: str | None = Header(default=None)):
    me = token_hash(x_bwu_token)
    with connect(write=True) as db:
        row = fetch_post(db, post_id, me)
        if row["owner"] != me:
            raise HTTPException(403, "작성자만 삭제할 수 있어요.")
        db.execute("DELETE FROM posts WHERE id=?", (post_id,))
    return {"ok": True}


app.mount("/", StaticFiles(directory=PUBLIC_DIR, html=True), name="public")
