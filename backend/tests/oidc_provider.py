"""Disposable HTTP identity provider used only by the browser test harness."""

import secrets
from urllib.parse import urlencode

from fastapi import FastAPI, Form, Header, HTTPException
from fastapi.responses import RedirectResponse

app = FastAPI()
ISSUER = "http://127.0.0.1:38602"
CALLBACK = "http://127.0.0.1:38600/api/auth/oidc/callback"
codes: set[str] = set()
tokens: set[str] = set()


@app.get("/.well-known/openid-configuration")
async def discovery():
    return {
        "issuer": ISSUER,
        "authorization_endpoint": ISSUER + "/authorize",
        "token_endpoint": ISSUER + "/token",
        "userinfo_endpoint": ISSUER + "/userinfo",
    }


@app.get("/authorize")
async def authorize(state: str, redirect_uri: str, client_id: str, response_type: str):
    if (
        redirect_uri != CALLBACK
        or client_id != "browser-test-client"
        or response_type != "code"
    ):
        raise HTTPException(400, "Invalid test authorization request")
    code = secrets.token_urlsafe(24)
    codes.add(code)
    return RedirectResponse(
        CALLBACK + "?" + urlencode({"code": code, "state": state}), status_code=302
    )


@app.post("/token")
async def token(
    code: str = Form(),
    client_id: str = Form(),
    client_secret: str = Form(),
    grant_type: str = Form(),
    redirect_uri: str = Form(),
):
    if (
        code not in codes
        or client_id != "browser-test-client"
        or client_secret != "browser-tests-only"
        or grant_type != "authorization_code"
        or redirect_uri != CALLBACK
    ):
        raise HTTPException(400, "Invalid test token exchange")
    codes.remove(code)
    credential = secrets.token_urlsafe(32)
    tokens.add(credential)
    return {"access_token": credential, "token_type": "Bearer"}


@app.get("/userinfo")
async def userinfo(authorization: str = Header()):
    if authorization.removeprefix("Bearer ") not in tokens:
        raise HTTPException(401, "Invalid test provider token")
    return {
        "sub": "browser-editor",
        "email": "editor@example.test",
        "name": "Browser Editor",
        "email_verified": True,
    }
