import secrets
from flask import Blueprint, render_template, request, session, redirect, url_for, g, flash
from werkzeug.security import generate_password_hash, check_password_hash
from .db import one, execute, get_db, audit
from .common import field, ValidationError, login_required

bp=Blueprint('auth',__name__)

@bp.route('/login',methods=['GET','POST'])
def login():
    if request.method=='POST':
        user=one('SELECT * FROM users WHERE student_no=%s',(field('student_no'),))
        if not user or not check_password_hash(user['password_hash'],field('password')):
            raise ValidationError('学号或密码不正确。')
        session.clear();session['user_id']=user['id'];session['csrf_token']=secrets.token_hex(32)
        return redirect(url_for('main.dashboard'))
    return render_template('auth.html',mode='login')

@bp.route('/register',methods=['GET','POST'])
def register():
    if request.method=='POST':
        password=field('password',128)
        if len(password)<8:
            raise ValidationError('密码至少需要 8 位。')
        execute('INSERT INTO users(student_no,name,password_hash,major,grade,phone) VALUES(%s,%s,%s,%s,%s,%s)',
                (field('student_no',30),field('name',40),generate_password_hash(password),field('major',80),field('grade',30),field('phone',40)))
        get_db().commit();flash('注册成功，请登录。','success')
        return redirect(url_for('auth.login'))
    return render_template('auth.html',mode='register')

@bp.post('/logout')
def logout():
    session.clear()
    return redirect(url_for('auth.login'))

@bp.route('/profile',methods=['GET','POST'])
@login_required
def profile():
    if request.method=='POST':
        password=field('new_password',128,False)
        if password:
            if not check_password_hash(g.user['password_hash'],field('old_password')):
                raise ValidationError('原密码不正确。')
            if len(password)<8:raise ValidationError('新密码至少需要 8 位。')
            execute('UPDATE users SET password_hash=%s WHERE id=%s',(generate_password_hash(password),g.user['id']))
        execute('UPDATE users SET name=%s,major=%s,grade=%s,phone=%s WHERE id=%s',
                (field('name',40),field('major',80),field('grade',30),field('phone',40),g.user['id']))
        audit('修改个人资料','user',g.user['id']);get_db().commit();flash('资料已保存。','success')
        return redirect(url_for('auth.profile'))
    return render_template('profile.html')
