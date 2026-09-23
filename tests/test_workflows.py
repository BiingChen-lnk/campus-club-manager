"""Integration tests use a fresh MySQL database. No SQLite or model calls."""
import uuid
from datetime import datetime, timedelta
import pytest
from clubapp import create_app
from clubapp.db import init_db, get_db, one, execute, connect
from clubapp.seed import seed_demo

@pytest.fixture(scope='module')
def app(tmp_path_factory):
    name='dbxm_test_'+uuid.uuid4().hex[:12]
    app=create_app({'TESTING':True,'MYSQL_DATABASE':name,'UPLOAD_FOLDER':str(tmp_path_factory.mktemp('receipts'))})
    with app.app_context():
        init_db();seed_demo()
    yield app
    with app.app_context():
        assert name.startswith('dbxm_test_')
        conn=connect(False)
        with conn.cursor() as cur:cur.execute(f'DROP DATABASE `{name}`')
        conn.commit();conn.close()

def login(app,no='2025001',password='Club123!'):
    c=app.test_client();c.get('/login')
    with c.session_transaction() as s:token=s['csrf_token']
    result=c.post('/login',data={'csrf_token':token,'student_no':no,'password':password})
    assert result.status_code==302
    return c

def post(c,path,data=None):
    with c.session_transaction() as s:token=s['csrf_token']
    return c.post(path,data={**(data or {}),'csrf_token':token},follow_redirects=False)

def query(app,sql,args=()):
    with app.app_context():return one(sql,args)

def test_pages_and_privacy(app):
    owner=login(app)
    for path in ['/','/clubs','/clubs/1','/recruitment','/recruitment/1','/activities','/activities/1','/activities/new','/finance','/finance/funds/1','/finance/transactions/1','/reports','/reports?export=csv','/audit','/ai','/notifications','/profile']:
        assert owner.get(path).status_code==200,path
    student=login(app,'2025003')
    assert student.get('/finance/funds/1').status_code==403
    assert student.get('/reports?club_id=1').status_code==403
    assert owner.get('/reports?club_id=2').status_code==403
    assert owner.post('/clubs/1',data={'action':'department','name':'x'}).status_code==400

def test_recruitment_workflow(app):
    c=login(app,'2025003')
    payload=dict(option_id='1',name='测试申请人',major='计算机',grade='2025',phone='123',experience='用 Python 写过课程练习',reason='希望学习',interests='技术分享',skill_text='Python,摄影',slots=['周六上午'])
    assert post(c,'/recruitment/1',payload).status_code==302
    a=query(app,"SELECT * FROM applications WHERE user_id=4")
    assert post(c,'/recruitment/1',payload).status_code==400
    outsider=login(app,'2025002')
    assert outsider.get(f'/applications/{a["id"]}').status_code==403
    owner=login(app)
    assert post(owner,f'/applications/{a["id"]}/review',{'decision':'accepted'}).status_code==302
    assert query(app,'SELECT status FROM memberships WHERE user_id=4 AND club_id=1')['status']=='active'
    assert post(owner,f'/applications/{a["id"]}/review',{'decision':'accepted'}).status_code==400

def test_activity_capacity_and_cancel(app):
    c=login(app,'2025002')
    with app.app_context():execute('UPDATE activities SET capacity=1 WHERE id=1');get_db().commit()
    assert post(c,'/activities/1/join',{'action':'join'}).status_code==302
    assert post(c,'/activities/1/join',{'action':'join'}).status_code==400
    other=login(app,'2025001')
    assert post(other,'/activities/1/join',{'action':'join'}).status_code==400
    assert post(c,'/activities/1/join',{'action':'cancel'}).status_code==302
    assert post(other,'/activities/1/join',{'action':'join'}).status_code==302

def test_checkin_feedback(app):
    student=login(app,'2025002');rid=query(app,'SELECT id FROM registrations WHERE activity_id=2 AND user_id=3')['id']
    assert post(student,f'/registrations/{rid}/checkin').status_code==302
    assert post(student,f'/registrations/{rid}/checkin').status_code==400
    assert post(student,'/activities/2/feedback',dict(organization=5,content=5,venue=5)).status_code==400
    owner=login(app)
    assert post(owner,'/activities/2/state',{'action':'end'}).status_code==302
    assert post(student,'/activities/2/feedback',dict(organization=5,content=4,venue=5,comment='学到不少东西')).status_code==302
    assert post(student,'/activities/2/feedback',dict(organization=5,content=4,venue=5)).status_code==400

def test_finance_limits(app):
    owner=login(app)
    base=dict(club_id=1,direction='expense',amount='200.00',category='打印',happened_on=datetime.now().date().isoformat(),fund_id=1)
    assert post(owner,'/finance/transactions',base).status_code==400
    assert post(owner,'/finance/transactions',{**base,'amount':'10.001'}).status_code==400
    assert post(owner,'/finance/transactions',{**base,'amount':'50.00'}).status_code==302
    assert post(owner,'/finance/transactions',{**base,'club_id':2}).status_code==403

def test_fund_approval_permissions(app):
    owner=login(app)
    assert post(owner,'/finance/funds',{'club_id':1,'purpose':'测试预算','item_name':['打印'],'quantity':['2'],'unit_price':['5.00']}).status_code==302
    f=query(app,'SELECT max(id) id FROM fund_applications')['id']
    assert post(owner,f'/finance/funds/{f}',{'decision':'approved'}).status_code==403
    admin=login(app,'admin','Admin123!')
    assert post(admin,f'/finance/funds/{f}',{'decision':'approved'}).status_code==302
    assert post(admin,f'/finance/funds/{f}',{'decision':'approved'}).status_code==400

def test_ai_requires_config_and_confirmation(app,monkeypatch):
    c=login(app,'2025003');a=query(app,'SELECT id FROM applications WHERE user_id=4')['id']
    monkeypatch.delenv('AI_API_KEY',raising=False)
    assert post(c,'/ai/generate',dict(kind='recruit',application_id=a,consent='on')).status_code==400

def test_ai_extraction_keeps_evidence_and_needs_confirmation(app,monkeypatch):
    import clubapp.ai as module
    monkeypatch.setattr(module,'configured',lambda:True)
    monkeypatch.setattr(module,'ask_model',lambda *a:'{"summary":"做过课程练习","skills":[{"name":"编程","evidence":"用 Python 写过课程练习"},{"name":"领导力","evidence":"不存在的经历"}]}')
    c=login(app,'2025003');a=query(app,'SELECT id FROM applications WHERE user_id=4')['id']
    assert post(c,'/ai/generate',dict(kind='recruit',application_id=a,consent='on')).status_code==302
    skill=query(app,"SELECT x.id,x.confirmed FROM application_skills x JOIN skills s ON s.id=x.skill_id WHERE x.application_id=%s AND s.name='编程'",(a,))
    assert skill['confirmed']==0
    assert not query(app,"SELECT id FROM skills WHERE name='领导力'")
    assert post(c,f'/applications/{a}/skills',{'skills':[str(skill['id'])]}).status_code==302
    assert query(app,'SELECT confirmed FROM application_skills WHERE id=%s',(skill['id'],))['confirmed']==1

def test_last_owner_protected(app):
    c=login(app)
    assert post(c,'/members/1',dict(role='member',status='left')).status_code==400

def test_database_foreign_keys(app):
    keys=query(app,"SELECT COUNT(*) n FROM information_schema.REFERENTIAL_CONSTRAINTS WHERE CONSTRAINT_SCHEMA=%s",(app.config['MYSQL_DATABASE'],))
    assert keys['n']>=35

def test_owner_publishes_activity_and_prevents_early_checkin(app):
    c=login(app);now=datetime.now();fmt=lambda d:d.strftime('%Y-%m-%dT%H:%M')
    result=post(c,'/activities/new',dict(club_id=1,title='审批流程测试',description='测试活动',location='教室',capacity=3,
        starts_at=fmt(now+timedelta(days=2)),ends_at=fmt(now+timedelta(days=2,hours=1)),deadline=fmt(now+timedelta(days=1))))
    assert result.status_code==302
    aid=query(app,'SELECT max(id) id FROM activities')['id']
    admin=login(app,'admin','Admin123!')
    assert post(admin,f'/activities/{aid}/state',{'action':'publish'}).status_code==403
    assert post(admin,f'/activities/{aid}/state',{'action':'approve'}).status_code==403
    assert post(c,f'/activities/{aid}/state',{'action':'publish'}).status_code==302
    assert query(app,'SELECT status FROM activities WHERE id=%s',(aid,))['status']=='published'
    assert query(app,'SELECT COUNT(*) n FROM activity_approvals WHERE activity_id=%s',(aid,))['n']==0
    assert post(c,f'/activities/{aid}/join',{'action':'join'}).status_code==302
    rid=query(app,'SELECT id FROM registrations WHERE activity_id=%s',(aid,))['id']
    assert post(c,f'/registrations/{rid}/checkin').status_code==400

def test_receipt_upload_download_is_private(app):
    import io
    c=login(app)
    assert post(c,'/finance/transactions/2',{'receipt':(io.BytesIO(b'not an image'),'bad.png')}).status_code==400
    assert post(c,'/finance/transactions/2',{'receipt':(io.BytesIO(b'%PDF-1.4\n test fixture'),'receipt.pdf')}).status_code==302
    rid=query(app,'SELECT max(id) id FROM receipts')['id']
    assert c.get(f'/receipts/{rid}').status_code==200
    other=login(app,'2025002')
    assert other.get(f'/receipts/{rid}').status_code==403

def test_concurrent_registration_respects_capacity(app):
    from concurrent.futures import ThreadPoolExecutor
    now=datetime.now();fmt=lambda d:d.strftime('%Y-%m-%d %H:%M:%S')
    with app.app_context():
        aid=execute("INSERT INTO activities(club_id,created_by,title,description,location,starts_at,ends_at,deadline,capacity,status) VALUES(1,2,'并发报名测试','测试','教室',%s,%s,%s,1,'published')",(fmt(now+timedelta(days=1)),fmt(now+timedelta(days=1,hours=1)),fmt(now+timedelta(hours=2))))
        get_db().commit()
    clients=[login(app,'2025001'),login(app,'2025002')]
    with ThreadPoolExecutor(max_workers=2) as pool:
        results=list(pool.map(lambda c:post(c,f'/activities/{aid}/join',{'action':'join'}).status_code,clients))
    assert sorted(results)==[302,400]
    assert query(app,"SELECT count(*) n FROM registrations WHERE activity_id=%s AND status='registered'",(aid,))['n']==1


def test_public_student_registration_returns_to_questionnaire(app):
    client=app.test_client()
    assert '学生注册' in client.get('/').get_data(as_text=True)
    assert client.get('/recruitment').status_code==200
    detail=client.get('/recruitment/1').get_data(as_text=True)
    assert '/register?next=/recruitment/1' in detail
    assert '已提交问卷' not in detail
    payload=dict(student_no='test-new-student',name='注册测试',major='计算机',grade='2026',phone='示例联系方式',password='TestStudent123!',password_confirm='TestStudent123!',next='/recruitment/1',role='admin')
    response=post(client,'/register',payload)
    assert response.status_code==302 and response.location=='/login?next=/recruitment/1'
    user=query(app,'SELECT id,role FROM users WHERE student_no=%s',(payload['student_no'],))
    assert user['role']=='student'
    assert query(app,'SELECT count(*) n FROM memberships WHERE user_id=%s',(user['id'],))['n']==0
    response=post(client,'/login',dict(student_no=payload['student_no'],password=payload['password'],next='/recruitment/1'))
    assert response.location=='/recruitment/1'
    assert client.get(response.location).status_code==200
    assert client.get('/recruitment/new?club_id=1').status_code==403
    assert post(client,'/clubs/1/owner',{'owner_no':payload['student_no']}).status_code==403


def test_registration_validation_and_redirect_safety(app):
    client=app.test_client();client.get('/register')
    payload=dict(student_no='test-invalid-student',name='注册验证',major='计算机',grade='2026',phone='示例联系方式',password='TestStudent123!',password_confirm='Different123!')
    assert post(client,'/register',payload).status_code==400
    assert not query(app,'SELECT id FROM users WHERE student_no=%s',(payload['student_no'],))
    assert post(client,'/register',{**payload,'student_no':'2025001','password_confirm':payload['password']}).status_code==400
    response=post(client,'/login',dict(student_no='2025001',password='Club123!',next='//external.example/steal'))
    assert response.location=='/'


def test_admin_has_oversight_without_recruitment_or_activity_control(app):
    admin=login(app,'admin','Admin123!')
    assert '社团总览' in admin.get('/').get_data(as_text=True)
    for path in ['/reports?club_id=1','/finance?club_id=1','/finance/funds/1','/finance/transactions/1','/audit']:
        assert admin.get(path).status_code==200,path
    a=query(app,'SELECT id FROM applications WHERE user_id=4')['id']
    assert admin.get(f'/applications/{a}').status_code==403
    assert post(admin,f'/applications/{a}/review',{'decision':'accepted'}).status_code==403
    assert admin.get('/recruitment/new?club_id=1').status_code==403
    assert post(admin,'/recruitment/new',{'club_id':1}).status_code==403
    assert post(admin,'/recruitment/1/close').status_code==403
    assert post(admin,'/recruitment/1').status_code==403
    assert query(app,'SELECT status FROM batches WHERE id=1')['status']=='published'
    detail=admin.get('/recruitment/1').get_data(as_text=True)
    assert '已提交问卷' not in detail and 'name="option_id"' not in detail
    assert admin.get('/activities/new').status_code==403
    assert admin.get('/activities/1/edit').status_code==403
    assert post(admin,'/activities/1/state',{'action':'cancel'}).status_code==403
    assert post(admin,'/activities/1/join',{'action':'join'}).status_code==403
    assert post(admin,'/registrations/1/checkin').status_code==403
    assert post(admin,'/activities/2/feedback').status_code==403
    assert post(admin,'/clubs/1',{'action':'department','name':'不应创建'}).status_code==403
    assert post(admin,'/members/1',dict(role='member',status='left')).status_code==403
    assert post(admin,'/finance/funds',{'club_id':1}).status_code==403
    assert post(admin,'/ai/generate',dict(kind='plan',activity_id=1,consent='on')).status_code==403


def test_admin_owner_assignment_and_legacy_membership_do_not_bypass_roles(app):
    admin=login(app,'admin','Admin123!')
    with app.app_context():
        cid=execute("INSERT INTO clubs(name,description) VALUES('权限测试社团','用于权限回归')")
        execute("INSERT INTO memberships(club_id,user_id,role) VALUES(%s,1,'owner')",(cid,))
        get_db().commit()
    # Old installations may still contain an admin-as-owner membership.
    assert admin.get(f'/recruitment/new?club_id={cid}').status_code==403
    assert post(admin,f'/clubs/{cid}',dict(action='department',name='旧角色不能操作')).status_code==403
    assert post(admin,f'/clubs/{cid}/owner',dict(owner_no='admin')).status_code==400
    assert post(admin,f'/clubs/{cid}/owner',dict(owner_no='2025003')).status_code==302
    owner=login(app,'2025003')
    assert post(owner,f'/clubs/{cid}',dict(action='department',name='招新部')).status_code==302
    assert owner.get(f'/recruitment/new?club_id={cid}').status_code==200
    assert post(admin,'/clubs',dict(name='不可指定管理员',owner_no='admin')).status_code==400


def test_owner_controls_recruitment_and_old_pending_activities(app):
    owner=login(app)
    fmt=lambda d:d.strftime('%Y-%m-%dT%H:%M')
    response=post(owner,'/recruitment/new',dict(club_id=1,title='负责人自主招新',description='无需管理员审批',starts_at=fmt(datetime.now()-timedelta(hours=1)),ends_at=fmt(datetime.now()+timedelta(days=3)),departments=['1']))
    assert response.status_code==302
    bid=int(response.location.rsplit('/',1)[1])
    assert query(app,'SELECT status FROM batches WHERE id=%s',(bid,))['status']=='published'
    assert post(owner,f'/recruitment/{bid}/close').status_code==302
    with app.app_context():
        aid=execute("INSERT INTO activities(club_id,created_by,title,description,location,starts_at,ends_at,deadline,capacity,status) VALUES(1,2,'旧待审批活动','兼容现有数据','教室',%s,%s,%s,10,'pending')",(datetime.now()+timedelta(days=2),datetime.now()+timedelta(days=3),datetime.now()+timedelta(days=1)))
        get_db().commit()
    assert owner.get(f'/activities/{aid}/edit').status_code==200
    assert post(owner,f'/activities/{aid}/state',dict(action='publish')).status_code==302
