import argparse
from getpass import getpass
from werkzeug.security import generate_password_hash
from clubapp import create_app
from clubapp.db import init_db, execute, get_db
from clubapp.seed import seed_demo

parser=argparse.ArgumentParser(description='社团管理项目数据库工具')
parser.add_argument('command',choices=['init','create-admin'])
parser.add_argument('--demo',action='store_true',help='仅在用户表为空时添加演示数据')
args=parser.parse_args()
app=create_app()
with app.app_context():
    if args.command=='init':
        init_db()
        print('MySQL 数据库与表已就绪。')
        if args.demo:print('演示数据已创建。' if seed_demo() else '数据库中已有用户，未重复添加演示数据。')
    else:
        no=input('管理员账号：').strip();name=input('姓名：').strip();password=getpass('密码（至少 8 位）：')
        if not no or not name or len(password)<8:raise SystemExit('账号、姓名不能为空，密码至少 8 位。')
        execute("INSERT INTO users(student_no,name,password_hash,role) VALUES(%s,%s,%s,'admin')",(no,name,generate_password_hash(password)))
        get_db().commit();print('管理员已创建。')
