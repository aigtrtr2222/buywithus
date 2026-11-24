import importlib
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
H = 3600 * 1000


def tok(n):
    return {"X-BWU-Token": f"test-token-{n:024d}"}


@pytest.fixture()
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("BWU_DATA_DIR", str(tmp_path))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    server.LIMITS["join"] = (1000, 3600)
    with TestClient(server.app) as c:
        c.server = server
        yield c


def new_post(**kw):
    now = int(time.time() * 1000)
    body = dict(cat="veg", title="양파 나눠요", item="양파 3kg", price=6900, max=3,
                place="화양동 마트 앞", area="화양동", meet=now + 30 * H, deadline=now + 2 * H,
                leader="자취생", kakao="https://open.kakao.com/o/abc123", memo="")
    body.update(kw)
    return body


def test_static_page_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "Buy With Us" in r.text


def test_create_join_leave_flow(client):
    r = client.post("/api/posts", json=new_post(), headers=tok(1))
    assert r.status_code == 201, r.text
    p = r.json()
    assert p["joined"] == 1 and p["isLeader"] and p["kakao"]

    # 참여 전에는 오픈채팅 링크 비공개
    other = client.get("/api/posts", headers=tok(2)).json()["posts"][0]
    assert other["kakao"] is None and not other["mine"]
    anon = client.get("/api/posts").json()["posts"][0]
    assert anon["kakao"] is None

    j = client.post(f"/api/posts/{p['id']}/join", headers=tok(2)).json()
    assert j["joined"] == 2 and j["mine"] and j["kakao"] == "https://open.kakao.com/o/abc123"
    # 중복 참여는 인원 증가 없음
    assert client.post(f"/api/posts/{p['id']}/join", headers=tok(2)).json()["joined"] == 2

    assert client.delete(f"/api/posts/{p['id']}/join", headers=tok(2)).json()["joined"] == 1
    # 리더는 참여 취소 불가, 남은 삭제 불가
    assert client.delete(f"/api/posts/{p['id']}/join", headers=tok(1)).status_code == 409
    assert client.delete(f"/api/posts/{p['id']}", headers=tok(2)).status_code == 403
    assert client.delete(f"/api/posts/{p['id']}", headers=tok(1)).status_code == 200
    assert client.get("/api/posts").json()["posts"] == []


def test_full_post_rejects_and_no_overbooking(client):
    p = client.post("/api/posts", json=new_post(max=3), headers=tok(1)).json()
    with ThreadPoolExecutor(8) as ex:
        codes = list(ex.map(lambda n: client.post(f"/api/posts/{p['id']}/join", headers=tok(n)).status_code, range(10, 30)))
    assert codes.count(200) == 2 and codes.count(409) == 18
    assert client.get("/api/posts").json()["posts"][0]["joined"] == 3


def test_validation(client):
    now = int(time.time() * 1000)
    bad = [
        new_post(kakao="https://evil.example/o/x"),
        new_post(deadline=now - 1000),
        new_post(meet=now + H, deadline=now + 2 * H),
        new_post(max=11), new_post(max=1), new_post(price=-1),
        new_post(cat="weapon"), new_post(title="   "), new_post(title="가" * 41),
        new_post(meet=now + 40 * 24 * H),
    ]
    for b in bad:
        assert client.post("/api/posts", json=b, headers=tok(1)).status_code == 422, b
    assert client.post("/api/posts", json=new_post()).status_code == 400  # 토큰 없음
    assert client.post("/api/posts", json=new_post(), headers={"X-BWU-Token": "short"}).status_code == 400


def test_closed_deadline_rejects_join(client):
    p = client.post("/api/posts", json=new_post(), headers=tok(1)).json()
    with client.server.connect(write=True) as db:
        db.execute("UPDATE posts SET deadline=? WHERE id=?", (int(time.time() * 1000) - 1, p["id"]))
    assert client.post(f"/api/posts/{p['id']}/join", headers=tok(2)).status_code == 409


def test_post_rate_limit(client):
    for _ in range(5):
        assert client.post("/api/posts", json=new_post(), headers=tok(1)).status_code == 201
    r = client.post("/api/posts", json=new_post(), headers=tok(1))
    assert r.status_code == 429 and "error" in r.json()


def test_data_persists_across_restart(client, tmp_path):
    client.post("/api/posts", json=new_post(), headers=tok(1))
    sys.modules.pop("server", None)
    server = importlib.import_module("server")
    with TestClient(server.app) as c2:
        assert len(c2.get("/api/posts").json()["posts"]) == 1


def test_chat_identity_and_messages(client):
    me1 = client.get("/api/chat", headers=tok(1)).json()["me"]
    assert me1 == client.get("/api/chat", headers=tok(1)).json()["me"]  # 같은 브라우저 = 같은 닉네임
    assert client.get("/api/chat").json()["me"] is None
    names = {client.get("/api/chat", headers=tok(n)).json()["me"]["name"] for n in range(40)}
    assert len(names) > 20  # 닉네임이 골고루 섞임

    r = client.post("/api/chat", json={"text": "  안녕\n\n<b>하세요</b>  "}, headers=tok(1))
    assert r.status_code == 201
    m = r.json()
    assert m["text"] == "안녕 <b>하세요</b>" and m["mine"] and m["name"] == me1["name"]
    client.post("/api/chat", json={"text": "반가워요"}, headers=tok(2))

    other = client.get("/api/chat", headers=tok(2)).json()["messages"]
    assert [x["mine"] for x in other] == [False, True]
    assert "token" not in other[0]
    assert len(client.get(f"/api/chat?after={m['id']}").json()["messages"]) == 1

    assert client.post("/api/chat", json={"text": "   "}, headers=tok(1)).status_code == 422
    assert client.post("/api/chat", json={"text": "가" * 201}, headers=tok(1)).status_code == 422
    assert client.post("/api/chat", json={"text": "hi"}).status_code == 400


def test_chat_keeps_recent_only(client):
    client.server.CHAT_KEEP = 5
    client.server.LIMITS["chat"] = (1000, 60)
    for i in range(12):
        client.post("/api/chat", json={"text": f"m{i}"}, headers=tok(1))
    msgs = client.get("/api/chat").json()["messages"]
    assert [x["text"] for x in msgs] == [f"m{i}" for i in range(7, 12)]
