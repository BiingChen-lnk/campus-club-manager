from datetime import datetime
from decimal import Decimal, InvalidOperation
from functools import wraps
from flask import g, request, redirect, url_for, abort
from .db import one

class ValidationError(Exception):
    pass

def now():
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

def field(name, maximum=200, required=True):
    value = request.form.get(name, '').strip()
    if required and not value:
        raise ValidationError('请填写所有必填项。')
    if len(value) > maximum:
        raise ValidationError(f'输入内容过长（最多 {maximum} 字）。')
    return value

def integer(value, minimum=1, maximum=1000000):
    try:
        number = int(value)
    except (ValueError, TypeError):
        raise ValidationError('请输入有效整数。')
    if not minimum <= number <= maximum:
        raise ValidationError(f'数字应在 {minimum} 到 {maximum} 之间。')
    return number

def cents(value):
    try:
        amount = Decimal(value)
        if not amount.is_finite() or amount <= 0 or amount > 10000000 or amount != amount.quantize(Decimal('.01')):
            raise ValueError()
        return int(amount * 100)
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError('金额须大于 0，最多保留两位小数，且不超过一千万元。')

def moment(name):
    try:
        return datetime.strptime(field(name), '%Y-%m-%dT%H:%M').strftime('%Y-%m-%d %H:%M:%S')
    except ValueError:
        raise ValidationError('日期时间格式不正确。')

def login_required(fn):
    @wraps(fn)
    def wrapped(*args, **kwargs):
        if not g.user:
            return redirect(url_for('auth.login'))
        return fn(*args, **kwargs)
    return wrapped

def is_admin():
    return bool(g.get('user') and g.user['role'] == 'admin')

def can_manage(club_id):
    return bool(g.get('user') and (is_admin() or one("SELECT id FROM memberships WHERE user_id=%s AND club_id=%s AND status='active' AND role='owner'", (g.user['id'],club_id))))

def manage_required(club_id):
    if not can_manage(club_id):
        abort(403)

def admin_required():
    if not is_admin():
        abort(403)

def member(club_id):
    return g.get('user') and one("SELECT * FROM memberships WHERE user_id=%s AND club_id=%s AND status='active'", (g.user['id'],club_id))

def visible_clubs():
    from .db import rows
    if is_admin():
        return rows('SELECT * FROM clubs ORDER BY id')
    return rows("SELECT c.* FROM clubs c JOIN memberships m ON m.club_id=c.id WHERE m.user_id=%s AND m.role='owner' AND m.status='active'", (g.user['id'],))
