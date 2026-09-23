from datetime import datetime, timedelta
from werkzeug.security import generate_password_hash
from .db import execute, one, get_db

def seed_demo():
    if one('SELECT count(*) n FROM users')['n']:
        return False
    users=[('admin','管理员','Admin123!','admin'),('2025001','林同学','Club123!','student'),('2025002','陈同学','Club123!','student'),('2025003','周同学','Club123!','student')]
    ids=[]
    for no,name,password,role in users:
        ids.append(execute('INSERT INTO users(student_no,name,password_hash,role,major,grade,phone) VALUES(%s,%s,%s,%s,%s,%s,%s)',
            (no,name,generate_password_hash(password),role,'计算机科学与技术','2025 级','示例联系方式')))
    cid=execute('INSERT INTO clubs(name,description) VALUES(%s,%s)',('计算机协会','一起写代码、分享技术，也把有趣的想法做成作品。'))
    cid2=execute('INSERT INTO clubs(name,description) VALUES(%s,%s)',('光影摄影社','用镜头记录校园，交流拍摄技巧与作品。'))
    deps=[execute('INSERT INTO departments(club_id,name) VALUES(%s,%s)',(cid,n)) for n in ['技术部','宣传部','组织部']]
    execute('INSERT INTO departments(club_id,name) VALUES(%s,%s)',(cid2,'摄影部'))
    execute("INSERT INTO memberships(club_id,user_id,department_id,role) VALUES(%s,%s,%s,'owner')",(cid,ids[1],deps[0]))
    execute("INSERT INTO memberships(club_id,user_id,department_id) VALUES(%s,%s,%s)",(cid,ids[2],deps[0]))
    execute("INSERT INTO memberships(club_id,user_id,role) VALUES(%s,%s,'owner')",(cid2,ids[2]))
    now=datetime.now();fmt=lambda d:d.strftime('%Y-%m-%d %H:%M:%S')
    bid=execute("INSERT INTO batches(club_id,title,description,starts_at,ends_at,status,created_by) VALUES(%s,%s,%s,%s,%s,'published',%s)",
        (cid,'秋季招新 · 找到一起做项目的伙伴','不要求已有项目经验。填写你的兴趣、经历和空闲时间，一起从小项目开始。',fmt(now-timedelta(days=1)),fmt(now+timedelta(days=30)),ids[1]))
    for dep in deps:execute('INSERT INTO batch_options(batch_id,department_id) VALUES(%s,%s)',(bid,dep))
    future=execute("INSERT INTO activities(club_id,created_by,title,description,location,starts_at,ends_at,deadline,capacity,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,30,'published')",
        (cid,ids[1],'Python 入门分享会','从变量和函数开始，用一个小练习认识 Python。欢迎带上电脑参加。','教学楼 A203',fmt(now+timedelta(days=7)),fmt(now+timedelta(days=7,hours=2)),fmt(now+timedelta(days=6))))
    live=execute("INSERT INTO activities(club_id,created_by,title,description,location,starts_at,ends_at,deadline,capacity,status) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,20,'published')",
        (cid,ids[1],'项目交流开放日','分享正在做的小项目，并交流课程学习问题。此示例活动用于体验签到流程。','社团活动室',fmt(now-timedelta(minutes=5)),fmt(now+timedelta(hours=6)),fmt(now-timedelta(minutes=10))))
    execute('INSERT INTO registrations(activity_id,user_id) VALUES(%s,%s)',(live,ids[2]))
    for aid in [future,live]:execute("INSERT INTO activity_approvals(activity_id,reviewer_id,decision,note) VALUES(%s,%s,'approved','示例活动已审核')",(aid,ids[0]))
    fid=execute("INSERT INTO fund_applications(club_id,activity_id,applicant_id,purpose,status) VALUES(%s,%s,%s,%s,'approved')",(cid,future,ids[1],'Python 分享会材料与饮用水'))
    execute('INSERT INTO budget_items(fund_id,name,quantity,unit_cents) VALUES(%s,%s,30,500)',(fid,'资料打印'))
    execute('INSERT INTO budget_items(fund_id,name,quantity,unit_cents) VALUES(%s,%s,30,200)',(fid,'饮用水'))
    execute("INSERT INTO fund_approvals(fund_id,reviewer_id,decision,note) VALUES(%s,%s,'approved','按预算使用，保留凭证')",(fid,ids[0]))
    execute("INSERT INTO transactions(club_id,recorded_by,direction,amount_cents,category,happened_on,note) VALUES(%s,%s,'income',100000,'社团活动支持',%s,'示例入账')",(cid,ids[1],now.date()))
    execute("INSERT INTO transactions(club_id,activity_id,fund_id,recorded_by,direction,amount_cents,category,happened_on,note) VALUES(%s,%s,%s,%s,'expense',6000,'饮用水',%s,'示例支出，待补充凭证')",(cid,future,fid,ids[1],now.date()))
    execute('INSERT INTO notifications(recipient_id,content) VALUES(%s,%s)',(ids[2],'欢迎加入计算机协会。你已报名项目交流开放日，可在活动详情页签到。'))
    get_db().commit()
    return True
