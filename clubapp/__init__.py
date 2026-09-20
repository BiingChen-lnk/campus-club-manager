import os
import secrets
import pymysql
from dotenv import load_dotenv
from pathlib import Path
from flask import Flask, session, request, g, render_template
from .db import close_db, init_db, one, get_db
from .common import ValidationError, can_manage, is_admin

def create_app(config=None):
    load_dotenv(Path(__file__).resolve().parents[1]/'.env',encoding='utf-8-sig')
    app = Flask(__name__, instance_relative_config=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    secret_path = Path(app.instance_path)/'secret.key'
    if not secret_path.exists():
        secret_path.write_text(secrets.token_hex(32), encoding='utf-8')
    app.config.update(SECRET_KEY=os.getenv('DBXM_SECRET_KEY') or secret_path.read_text(encoding='utf-8'),
                      MYSQL_HOST=os.getenv('MYSQL_HOST','127.0.0.1'),MYSQL_PORT=int(os.getenv('MYSQL_PORT','3306')),
                      MYSQL_USER=os.getenv('MYSQL_USER','root'),MYSQL_PASSWORD=os.getenv('MYSQL_PASSWORD',''),
                      MYSQL_DATABASE=os.getenv('MYSQL_DATABASE','dbxm'),UPLOAD_FOLDER=str(Path(app.instance_path)/'uploads'),
                      MAX_CONTENT_LENGTH=10*1024*1024, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE='Lax')
    if config:
        app.config.update(config)
    Path(app.config['UPLOAD_FOLDER']).mkdir(parents=True, exist_ok=True)
    app.teardown_appcontext(close_db)

    @app.before_request
    def load_user_and_csrf():
        g.user = None
        if session.get('user_id'):
            g.user = one('SELECT * FROM users WHERE id=%s', (session['user_id'],))
        if 'csrf_token' not in session:
            session['csrf_token'] = secrets.token_hex(32)
        if request.method == 'POST':
            token=request.form.get('csrf_token','')
            if not secrets.compare_digest(token, session['csrf_token']):
                return render_template('error.html', code=400, message='页面已过期，请刷新后重试。'),400

    @app.context_processor
    def context():
        unread=one('SELECT count(*) n FROM notifications WHERE recipient_id=%s AND read_at IS NULL',(g.user['id'],))['n'] if g.user else 0
        return dict(can_manage=can_manage, is_admin=is_admin, unread=unread, csrf_token=lambda:session.get('csrf_token',''))

    app.jinja_env.filters['money'] = lambda value: f'{(value or 0)/100:,.2f}'
    status_names={'draft':'草稿','pending':'待审核','published':'已发布','closed':'已关闭','accepted':'已录取',
        'rejected':'已驳回','approved':'已通过','cancelled':'已取消','ended':'已结束','registered':'已报名',
        'active':'在社','left':'已退出','success':'成功','failed':'失败','owner':'负责人','member':'成员',
        'income':'收入','expense':'支出','recruit':'问卷整理','plan':'活动策划','review':'活动复盘'}
    app.jinja_env.filters['status'] = lambda value:status_names.get(value,value)

    @app.errorhandler(ValidationError)
    def validation(error):
        get_db().rollback()
        return render_template('error.html',code=400,message=str(error)),400

    @app.errorhandler(pymysql.IntegrityError)
    def integrity(error):
        get_db().rollback()
        app.logger.info('Integrity validation: %s',error)
        return render_template('error.html',code=400,message='记录已存在，或填写的数据不符合要求，请检查后重试。'),400

    @app.errorhandler(pymysql.OperationalError)
    def database_unavailable(error):
        app.logger.error('MySQL operation failed, error code %s',error.args[0])
        return render_template('error.html',code=503,message='暂时无法访问 MySQL。请检查 .env 中的连接信息，并确认已运行数据库初始化命令。'),503

    for code,message in [(403,'你没有权限查看或操作这项资料。'),(404,'没有找到这项记录。'),(413,'文件太大，上传内容不能超过 10 MB。')]:
        app.register_error_handler(code,lambda error,code=code,message=message:(render_template('error.html',code=code,message=message),code))

    from . import auth, main, recruitment, activities, finance, ai
    for module in (auth,main,recruitment,activities,finance,ai):
        app.register_blueprint(module.bp)
    return app
