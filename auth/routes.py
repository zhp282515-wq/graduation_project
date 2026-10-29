import hashlib
import hmac
from typing import Literal

import jwt
from argon2.exceptions import VerificationError, InvalidHashError
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator
from psycopg.errors import UniqueViolation

from .repository import UserRepository, public_user
from .security import COOKIE, PASSWORDS, SESSION_SECONDS

router = APIRouter(prefix='/api')
_DUMMY_HASH = PASSWORDS.hash('not-a-user-password')


def repository(request: Request):
    with request.app.state.pg_pool.connection() as conn:
        yield UserRepository(conn)


def check_origin(request):
    if not request.app.state.auth.trusted_origin(request.headers.get('origin', '')):
        raise HTTPException(403, '请求来源不受信任')


def get_current_user(request: Request):
    settings = request.app.state.auth
    try:
        claims = settings.decode(request.cookies.get(COOKIE, ''))
    except jwt.PyJWTError:
        raise HTTPException(401, '登录已失效，请重新登录')
    with request.app.state.pg_pool.connection() as conn:
        user = UserRepository(conn).session_user(claims['jti'], claims['sub'])
    if not user:
        raise HTTPException(401, '登录已失效，请重新登录')
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        check_origin(request)
        if not hmac.compare_digest(request.headers.get('x-csrf-token', ''), settings.csrf(claims['jti'])):
            raise HTTPException(403, '安全校验失败，请刷新页面后重试')
    allowed = ('/api/auth/me', '/api/auth/password', '/api/auth/logout')
    if user['must_change_password'] and request.url.path not in allowed:
        raise HTTPException(403, '请先修改临时密码')
    return {**user, '_sid': claims['jti']}


def require_admin(user=Depends(get_current_user)):
    if user['role'] != 'admin':
        raise HTTPException(403, '此功能仅管理员可用')
    return user


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=3, max_length=32, pattern=r'^[A-Za-z0-9_\-]+$')
    password: str = Field(min_length=8, max_length=128)

    @field_validator('username', mode='before')
    @classmethod
    def trim_username(cls, value):
        return value.strip() if isinstance(value, str) else value


class NewUser(Credentials):
    role: Literal['user', 'admin'] = 'user'


class UserPatch(BaseModel):
    model_config = ConfigDict(extra='forbid')
    role: Literal['user', 'admin'] | None = None
    enabled: bool | None = None


class PasswordChange(BaseModel):
    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=8, max_length=128)


class PasswordReset(BaseModel):
    password: str = Field(min_length=8, max_length=128)


def logged_in(request, response, repo, user):
    sid = repo.new_session(user['id'])
    settings = request.app.state.auth
    response.set_cookie(COOKIE, settings.issue(user['id'], sid), max_age=SESSION_SECONDS,
                        httponly=True, secure=settings.secure, samesite='lax', path='/')
    response.headers['Cache-Control'] = 'no-store'
    return {'user': public_user(user), 'csrf_token': settings.csrf(sid)}


@router.post('/auth/register', status_code=201)
def register(body: Credentials, request: Request, response: Response, repo=Depends(repository)):
    check_origin(request)
    try:
        user = repo.create(body.username, PASSWORDS.hash(body.password))
    except UniqueViolation:
        raise HTTPException(409, '该用户名已被使用，请换一个')
    return logged_in(request,response,repo,user)


@router.post('/auth/login')
def login(body: Credentials, request: Request, response: Response, repo=Depends(repository)):
    check_origin(request)
    ip = request.client.host if request.client else 'unknown'
    key = hashlib.sha256(f'{ip}:{body.username.lower()}'.encode()).hexdigest()
    if repo.attempt(key) > 5:
        raise HTTPException(429, '尝试次数过多，请在15分钟后重试')
    user = repo.by_name(body.username)
    try:
        PASSWORDS.verify(user['password_hash'] if user else _DUMMY_HASH, body.password)
    except (VerificationError, InvalidHashError):
        raise HTTPException(401, '账号或密码错误')
    if not user or not user['enabled']:
        raise HTTPException(401, '账号或密码错误')
    if PASSWORDS.check_needs_rehash(user['password_hash']):
        repo.conn.execute('UPDATE app_users SET password_hash=%s WHERE id=%s', (PASSWORDS.hash(body.password), user['id']))
    repo.clear_attempt(key)
    return logged_in(request,response,repo,user)


@router.get('/auth/me')
def me(request: Request, response: Response, user=Depends(get_current_user)):
    response.headers['Cache-Control'] = 'no-store'
    return {'user': public_user(user), 'csrf_token': request.app.state.auth.csrf(user['_sid'])}


@router.post('/auth/logout')
def logout(response: Response, user=Depends(get_current_user), repo=Depends(repository)):
    repo.revoke(user['id'], user['_sid'])
    response.delete_cookie(COOKIE, path='/')
    return {'ok': True}


@router.post('/auth/password')
def password(body: PasswordChange, response: Response, user=Depends(get_current_user), repo=Depends(repository)):
    try:
        PASSWORDS.verify(user['password_hash'], body.current_password)
    except (VerificationError, InvalidHashError):
        raise HTTPException(400, '当前密码不正确')
    if body.new_password == body.current_password:
        raise HTTPException(400, '新密码不能与当前密码相同')
    with repo.conn.transaction():
        repo.change_password(user['id'], PASSWORDS.hash(body.new_password))
    response.delete_cookie(COOKIE, path='/')
    return {'ok': True}


@router.get('/admin/users')
def users(q: str='', page: int=Query(1,ge=1), user=Depends(require_admin), repo=Depends(repository)):
    return repo.list_page(q,page)


@router.post('/admin/users', status_code=201)
def add_user(body: NewUser, user=Depends(require_admin), repo=Depends(repository)):
    try:
        return repo.create(body.username,PASSWORDS.hash(body.password),body.role,must_change=True)
    except UniqueViolation:
        raise HTTPException(409, '该用户名已被使用')


@router.patch('/admin/users/{user_id}')
def update_user(user_id: str, body: UserPatch, user=Depends(require_admin), repo=Depends(repository)):
    with repo.conn.transaction():
        try:
            result = repo.update(user_id,role=body.role,enabled=body.enabled)
        except ValueError as exc:
            raise HTTPException(409,str(exc))
        if not result:
            raise HTTPException(404,'账号不存在')
        return result


@router.post('/admin/users/{user_id}/reset-password')
def reset_password(user_id: str, body: PasswordReset, user=Depends(require_admin), repo=Depends(repository)):
    if not repo.by_id(user_id):
        raise HTTPException(404,'账号不存在')
    with repo.conn.transaction():
        repo.change_password(user_id,PASSWORDS.hash(body.password),must_change=True)
    return {'ok':True}


@router.delete('/admin/users/{user_id}')
def delete_user(user_id: str, user=Depends(require_admin), repo=Depends(repository)):
    if user_id == user['id']:
        raise HTTPException(409,'不能注销当前登录的账号')
    with repo.conn.transaction():
        try:
            removed = repo.delete(user_id)
        except ValueError as exc:
            raise HTTPException(409,str(exc))
        if removed is None:
            raise HTTPException(404,'账号不存在')
    return {'deleted': user_id, 'username': removed['username']}
