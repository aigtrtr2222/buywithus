"""공구별 수다방: 참여자끼리만 대화."""
import sqlite3

from test_api import client, new_post, tok  # noqa: F401  (fixture 재사용)


def make(client, n=1, **kw):
    r = client.post("/api/posts", json=new_post(**kw), headers=tok(n))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def chat(client, pid, n, after=0):
    return client.get(f"/api/posts/{pid}/chat?after={after}", headers=tok(n))


def say(client, pid, n, text):
    return client.post(f"/api/posts/{pid}/chat", json={"text": text}, headers=tok(n))


def test_kakao_is_optional(client):
    pid = make(client, kakao="")
    p = client.get("/api/posts", headers=tok(1)).json()["posts"][0]
    assert p["id"] == pid and p["kakao"] is None


def test_only_members_can_read_and_write(client):
    pid = make(client, 1)
    # 참여 안 한 사람 / 토큰 없는 사람은 못 봄
    assert chat(client, pid, 2).status_code == 403
    assert say(client, pid, 2, "몰래").status_code == 403
    assert client.get(f"/api/posts/{pid}/chat").status_code == 400
    assert chat(client, 999, 1).status_code == 404

    # 리더는 바로 수다방 사용 (개설 안내 메시지 있음)
    first = chat(client, pid, 1).json()
    assert first["messages"][0]["kind"] == "sys" and "리더" in first["messages"][0]["text"]
    assert say(client, pid, 1, "  내일   7시에\n만나요 ").json()["text"] == "내일 7시에 만나요"

    client.post(f"/api/posts/{pid}/join", headers=tok(2))
    data = chat(client, pid, 2).json()
    texts = [m["text"] for m in data["messages"]]
    assert "내일 7시에 만나요" in texts and any("들어왔어요" in t for t in texts)
    leader_msg = next(m for m in data["messages"] if m["kind"] == "msg")
    assert leader_msg["leader"] and not leader_msg["mine"] and "token" not in leader_msg
    assert [m["leader"] for m in data["members"]] == [True, False]
    assert [m["me"] for m in data["members"]] == [False, True]

    # 다른 공구 수다방은 못 봄
    other = make(client, 3)
    assert chat(client, other, 2).status_code == 403

    # 나가면 더 이상 못 봄, 퇴장 안내 남음
    client.delete(f"/api/posts/{pid}/join", headers=tok(2))
    assert chat(client, pid, 2).status_code == 403
    assert "나갔어요" in chat(client, pid, 1).json()["messages"][-1]["text"]


def test_nicknames_unique_within_room(client):
    pid = make(client, 1, max=10)
    for n in range(2, 11):
        assert client.post(f"/api/posts/{pid}/join", headers=tok(n)).status_code == 200
    members = chat(client, pid, 1).json()["members"]
    assert len(members) == 10
    assert len({m["emoji"] for m in members}) == 10
    assert all(" " in m["name"] for m in members)


def test_after_and_rooms_list(client):
    a = make(client, 1, title="양파")
    b = make(client, 1, title="계란")
    client.post(f"/api/posts/{a}/join", headers=tok(2))
    m = say(client, a, 2, "안녕하세요").json()
    assert m["mine"] and not m["leader"]

    rooms = client.get("/api/rooms", headers=tok(1)).json()["rooms"]
    assert [r["id"] for r in rooms] == [a, b]  # 최근 대화 순
    assert rooms[0]["last"]["text"] == "안녕하세요" and rooms[0]["isLeader"]
    assert client.get("/api/rooms", headers=tok(2)).json()["rooms"][0]["id"] == a
    assert len(client.get("/api/rooms", headers=tok(2)).json()["rooms"]) == 1
    assert client.get("/api/rooms").json()["rooms"] == []

    say(client, a, 1, "반가워요")
    newer = chat(client, a, 2, after=m["id"]).json()["messages"]
    assert [x["text"] for x in newer] == ["반가워요"]


def test_delete_post_removes_room(client):
    pid = make(client, 1)
    client.post(f"/api/posts/{pid}/join", headers=tok(2))
    say(client, pid, 2, "hi")
    client.delete(f"/api/posts/{pid}", headers=tok(1))
    assert chat(client, pid, 2).status_code == 404
    assert client.get("/api/rooms", headers=tok(2)).json()["rooms"] == []
    with client.server.connect() as db:
        assert db.execute("SELECT COUNT(*) FROM room_messages").fetchone()[0] == 0


def test_validation_and_retention(client):
    pid = make(client, 1)
    assert say(client, pid, 1, "   ").status_code == 422
    assert say(client, pid, 1, "가" * 301).status_code == 422
    client.server.CHAT_KEEP = 5
    client.server.LIMITS["chat"] = (1000, 60)
    for i in range(12):
        say(client, pid, 1, f"m{i}")
    assert [m["text"] for m in chat(client, pid, 1).json()["messages"]] == [f"m{i}" for i in range(7, 12)]


def test_upgrade_old_database(tmp_path, monkeypatch):
    """이미 배포된 예전 DB(닉네임 없는 members, 전체 채팅 messages)도 그대로 올라와야 함."""
    import importlib
    import sys
    db = sqlite3.connect(tmp_path / "buywithus.sqlite3")
    db.executescript("""
      CREATE TABLE posts (id INTEGER PRIMARY KEY AUTOINCREMENT, cat TEXT NOT NULL, title TEXT NOT NULL,
        item TEXT NOT NULL, price INTEGER NOT NULL, max INTEGER NOT NULL, place TEXT NOT NULL, area TEXT NOT NULL,
        meet INTEGER NOT NULL, deadline INTEGER NOT NULL, leader TEXT NOT NULL, kakao TEXT NOT NULL,
        memo TEXT NOT NULL DEFAULT '', owner TEXT NOT NULL, created INTEGER NOT NULL);
      CREATE TABLE members (post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE, token TEXT NOT NULL,
        joined_at INTEGER NOT NULL, PRIMARY KEY (post_id, token));
      CREATE TABLE messages (id INTEGER PRIMARY KEY, token TEXT, name TEXT, emoji TEXT, text TEXT, created INTEGER);
      INSERT INTO posts VALUES (1,'veg','t','i',1000,3,'p','a',9999999999999,9999999999998,'L','',
        '', 'owner', 1);
      INSERT INTO members VALUES (1,'owner',1),(1,'guest',2);
    """)
    db.commit(); db.close()
    monkeypatch.setenv("BWU_DATA_DIR", str(tmp_path))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    with server.connect() as c:
        rows = c.execute("SELECT name, emoji FROM members").fetchall()
        assert all(r["name"] and r["emoji"] for r in rows)
        assert not c.execute("SELECT name FROM sqlite_master WHERE name='messages'").fetchone()


def test_egg_clear_turns_profile_into_animal(client):
    animals = {e for _, e in client.server.ANIMALS}
    produce = {e for _, e in client.server.PRODUCE}
    pid = make(client, 1)
    client.post(f"/api/posts/{pid}/join", headers=tok(2))
    say(client, pid, 2, "전에 쓴 말")
    before = next(m for m in chat(client, pid, 2).json()["members"] if m["me"])
    assert before["emoji"] in produce
    assert client.get("/api/egg", headers=tok(2)).json() == {"unlocked": False}

    r = client.post("/api/egg/clear", headers=tok(2)).json()
    assert r["unlocked"] and not r["already"] and r["rooms"] == 1
    assert client.post("/api/egg/clear", headers=tok(2)).json()["already"]
    assert client.get("/api/egg", headers=tok(2)).json() == {"unlocked": True}

    data = chat(client, pid, 2).json()
    after = next(m for m in data["members"] if m["me"])
    assert after["emoji"] in animals
    assert after["name"].split()[0] == before["name"].split()[0]          # 형용사는 유지
    mine = [m for m in data["messages"] if m["mine"]]
    assert mine and all(m["emoji"] == after["emoji"] for m in mine)       # 예전 말도 동물로
    assert "변신했어요" in data["messages"][-1]["text"]
    # 리더(클리어 안 함)는 그대로, 새로 참여하는 방도 동물
    leader = next(m for m in data["members"] if m["leader"])
    assert leader["emoji"] in produce
    other = make(client, 3)
    client.post(f"/api/posts/{other}/join", headers=tok(2))
    me2 = next(m for m in chat(client, other, 2).json()["members"] if m["me"])
    assert me2["emoji"] in animals
    assert client.post("/api/egg/clear").status_code == 400
