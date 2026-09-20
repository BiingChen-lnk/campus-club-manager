import re
from pathlib import Path
from datetime import datetime, date
import pymysql
from flask import current_app, g, abort

def connect(database=True):
    cfg=current_app.config
    return pymysql.connect(host=cfg['MYSQL_HOST'],port=cfg['MYSQL_PORT'],user=cfg['MYSQL_USER'],
        password=cfg['MYSQL_PASSWORD'],database=cfg['MYSQL_DATABASE'] if database else None,
        charset='utf8mb4',cursorclass=pymysql.cursors.DictCursor,autocommit=False,
        connect_timeout=5,read_timeout=15,write_timeout=15)

def get_db():
    if 'db' not in g:g.db=connect()
    return g.db

def close_db(error=None):
    db=g.pop('db',None)
    if db is not None:db.close()

def normalized(row):
    if row:
        return {k:(v.strftime('%Y-%m-%d %H:%M:%S') if isinstance(v,datetime) else v.isoformat() if isinstance(v,date) else v) for k,v in row.items()}
    return row

def rows(sql,args=()):
    with get_db().cursor() as cur:
        cur.execute(sql,args)
        return [normalized(r) for r in cur.fetchall()]

def one(sql,args=(),required=False):
    with get_db().cursor() as cur:
        cur.execute(sql,args);result=normalized(cur.fetchone())
    if required and result is None:abort(404)
    return result

def execute(sql,args=()):
    with get_db().cursor() as cur:
        cur.execute(sql,args)
        return cur.lastrowid

def init_db():
    name=current_app.config['MYSQL_DATABASE']
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,63}',name):raise ValueError('Invalid database name')
    conn=connect(False)
    try:
        with conn.cursor() as cur:
            cur.execute(f'CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
        conn.commit()
    finally:conn.close()
    for statement in Path(__file__).with_name('schema.sql').read_text(encoding='utf-8').split(';'):
        if statement.strip():execute(statement)
    get_db().commit()

def audit(action,kind,object_id=None,club_id=None,detail=''):
    execute('INSERT INTO audit_logs(actor_id,club_id,action,object_type,object_id,detail) VALUES(%s,%s,%s,%s,%s,%s)',
            (g.user['id'] if g.get('user') else None,club_id,action,kind,object_id,detail))

def notify(user_id,text):
    execute('INSERT INTO notifications(recipient_id,content) VALUES(%s,%s)',(user_id,text))
