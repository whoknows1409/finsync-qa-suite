"""Stand-in FinSync service: auth, transactions, assistant chat, tiny web UI.

This is the *system under test* for the QA suite in this repo. It exists so the
suite can run anywhere (CI, a laptop) without depending on a live deployment.
Point the suite at the real FinSync with FINSYNC_BASE_URL once its API matches.

Optional bug injection (for proving the suite catches regressions):
  FINSYNC_BUGS=idor,no_rate_limit,hallucination,no_refusal,pii_leak,injection,jailbreak,multiturn,tool_failure
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import tempfile
import time
from contextlib import asynccontextmanager
from typing import List, Literal, Optional

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

from .assistant import ToolError, answer
from .db import Store, init_db
from .seed import hash_pw

Category = Literal["Groceries", "Dining", "Transport", "Entertainment",
                   "Utilities", "Rent", "Shopping", "Subscriptions"]

SECRET = os.environ.get("FINSYNC_SECRET", "dev-secret-change-me").encode()
TOKEN_TTL = int(os.environ.get("FINSYNC_TOKEN_TTL", "3600"))
BUGS = {b.strip() for b in os.environ.get("FINSYNC_BUGS", "").split(",") if b.strip()}
MAX_FAILED_LOGINS, LOCKOUT_SECONDS = 5, 60
_failed: dict = {}

DB_PATH = os.environ.get("FINSYNC_DB") or os.path.join(tempfile.mkdtemp(prefix="finsync-"), "finsync.db")
store = Store(DB_PATH)


@asynccontextmanager
async def lifespan(_app):
    init_db(DB_PATH)
    yield


app = FastAPI(title="FinSync (QA target)", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ----------------------------------------------------------------- models --
class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=50)
    password: str = Field(min_length=1, max_length=100)


class TokenResponse(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int
    user_id: str


class Transaction(BaseModel):
    id: int
    date: str
    merchant: str
    category: Category
    amount: float
    description: str


class TransactionList(BaseModel):
    items: List[Transaction]
    count: int
    total: float


class Message(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    messages: List[Message] = Field(min_length=1, max_length=20)


class ToolCall(BaseModel):
    name: str
    args: dict


class ChatResponse(BaseModel):
    reply: str
    tool_calls: List[ToolCall]
    latency_ms: float


# ------------------------------------------------------------------- auth --
def _b64(b: bytes) -> str:
    return base64.urlsafe_b64encode(b).decode().rstrip("=")


def make_token(user_id: str) -> str:
    payload = _b64(json.dumps({"u": user_id, "exp": int(time.time()) + TOKEN_TTL}).encode())
    sig = hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def current_user(authorization: Optional[str] = Header(default=None)) -> str:
    unauth = HTTPException(401, "Invalid or missing token", headers={"WWW-Authenticate": "Bearer"})
    if not authorization or not authorization.startswith("Bearer "):
        raise unauth
    token = authorization[7:]
    try:
        payload, sig = token.rsplit(".", 1)
        good = hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(sig, good):
            raise unauth
        data = json.loads(base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
        if data["exp"] < time.time():
            raise unauth
        return data["u"]
    except HTTPException:
        raise
    except Exception:
        raise unauth


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/auth/login", response_model=TokenResponse)
def login(body: LoginRequest):
    now = time.time()
    attempts = [t for t in _failed.get(body.username, []) if now - t < LOCKOUT_SECONDS]
    if "no_rate_limit" not in BUGS and len(attempts) >= MAX_FAILED_LOGINS:
        raise HTTPException(429, "Too many failed attempts", headers={"Retry-After": str(LOCKOUT_SECONDS)})
    user = store.user(body.username)
    if not user or user["password_hash"] != hash_pw(body.password):
        _failed[body.username] = attempts + [now]
        raise HTTPException(401, "Invalid credentials")
    _failed.pop(body.username, None)
    return TokenResponse(access_token=make_token(user["user_id"]), expires_in=TOKEN_TTL, user_id=user["user_id"])


@app.get("/users/{user_id}/transactions", response_model=TransactionList)
def list_transactions(user_id: str, category: Optional[Category] = None,
                      month: Optional[str] = Query(default=None, pattern=r"^\d{4}-(0[1-9]|1[0-2])$"),
                      me: str = Depends(current_user)):
    if "idor" not in BUGS and me != user_id:
        raise HTTPException(403, "Forbidden")
    if not store.user(user_id):
        raise HTTPException(404, "Unknown user")
    rows = store.transactions(user_id, month, category)
    return TransactionList(items=rows, count=len(rows), total=round(sum(r["amount"] for r in rows), 2))


@app.post("/assistant/chat", response_model=ChatResponse)
def chat(body: ChatRequest, me: str = Depends(current_user),
         x_simulate_tool_failure: Optional[str] = Header(default=None)):
    if body.messages[-1].role != "user":
        raise HTTPException(422, "Last message must be from the user")
    user = store.user(me)

    def fetch(uid, month=None, category=None):
        if x_simulate_tool_failure:
            raise ToolError("simulated outage")
        return store.transactions(uid, month, category)

    t0 = time.perf_counter()
    reply, calls = answer(me, [m.model_dump() for m in body.messages], fetch, user,
                          store.user_ids(), BUGS)
    return ChatResponse(reply=reply, tool_calls=calls, latency_ms=round((time.perf_counter() - t0) * 1000, 2))


# --------------------------------------------------------------------- UI --
UI = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>FinSync</title></head><body>
<h1>FinSync <small>(QA target)</small></h1>
<section id="login-view">
  <label>Username <input id="username" autocomplete="username"></label>
  <label>Password <input id="password" type="password" autocomplete="current-password"></label>
  <button id="login-btn">Log in</button>
  <p id="login-error" role="alert"></p>
</section>
<section id="app-view" hidden>
  <p>Signed in as <strong id="welcome"></strong> <button id="logout-btn">Log out</button></p>
  <h2>October transactions</h2>
  <table id="tx-table"><thead><tr><th>Date</th><th>Merchant</th><th>Category</th><th>Amount</th></tr></thead><tbody></tbody></table>
  <h2>Assistant</h2>
  <div id="chat-log" aria-live="polite"></div>
  <input id="chat-input" placeholder="Ask about your spending" size="50">
  <button id="send-btn">Send</button>
</section>
<script>
let token=null, uid=null, history=[];
const $=id=>document.getElementById(id);
function addMsg(role,text){const d=document.createElement('div');d.className='msg '+role;d.textContent=text;$('chat-log').appendChild(d);}
$('login-btn').onclick=async()=>{
  $('login-error').textContent='';
  const r=await fetch('/auth/login',{method:'POST',headers:{'Content-Type':'application/json'},
    body:JSON.stringify({username:$('username').value,password:$('password').value})});
  if(!r.ok){$('login-error').textContent=r.status===429?'Too many attempts. Try again later.':'Invalid username or password';return;}
  const j=await r.json(); token=j.access_token; uid=j.user_id;
  $('welcome').textContent=uid; $('login-view').hidden=true; $('app-view').hidden=false;
  const t=await fetch('/users/'+uid+'/transactions?month=2026-10',{headers:{Authorization:'Bearer '+token}});
  const body=await t.json(); const tb=document.querySelector('#tx-table tbody'); tb.innerHTML='';
  body.items.forEach(x=>{const tr=document.createElement('tr');
    [x.date,x.merchant,x.category,x.amount].forEach(v=>{const td=document.createElement('td');td.textContent=v;tr.appendChild(td);});tb.appendChild(tr);});
};
$('send-btn').onclick=async()=>{
  const text=$('chat-input').value.trim(); if(!text) return; $('chat-input').value='';
  addMsg('user',text); history.push({role:'user',content:text});
  const r=await fetch('/assistant/chat',{method:'POST',headers:{'Content-Type':'application/json',Authorization:'Bearer '+token},
    body:JSON.stringify({messages:history})});
  if(!r.ok){addMsg('assistant','Something went wrong. Please try again.');return;}
  const j=await r.json(); history.push({role:'assistant',content:j.reply}); addMsg('assistant',j.reply);
};
$('logout-btn').onclick=()=>{token=null;uid=null;history=[];$('chat-log').innerHTML='';$('password').value='';
  $('app-view').hidden=true;$('login-view').hidden=false;};
</script></body></html>"""


@app.get("/", response_class=HTMLResponse)
def index():
    return UI
