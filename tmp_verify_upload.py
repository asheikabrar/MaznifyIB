import http.client
import os
from app.auth import make_session_token, SESSION_COOKIE
from app.auth import hash_password
from app.db import SessionLocal
from app.models import User
from sqlalchemy import select

with SessionLocal() as db:
    user = db.scalar(select(User).where(User.username == 'testuser'))
    if not user:
        user = User(username='testuser', password_hash=hash_password('test123'), is_admin=True)
        db.add(user)
        db.commit()
        db.refresh(user)

    boundary = '----uploadtest'
    body = (
        f'--{boundary}\r\n'
        'Content-Disposition: form-data; name="file"; filename="test.txt"\r\n'
        'Content-Type: text/plain\r\n\r\n'
        'hello world\r\n'
        f'--{boundary}--\r\n'
    ).encode('utf-8')
    headers = {
        'Content-Type': f'multipart/form-data; boundary={boundary}',
        'Cookie': f'{SESSION_COOKIE}={make_session_token(user.id)}',
    }

    conn = http.client.HTTPConnection('127.0.0.1', 8000, timeout=5)
    conn.request('POST', '/revision-desk/attachments/upload', body=body, headers=headers)
    response = conn.getresponse()
    print(response.status)
    print(response.read().decode('utf-8'))
