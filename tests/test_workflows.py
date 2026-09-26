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
    bid=int(response.location.split('/')[2])
    assert query(app,'SELECT status FROM batches WHERE id=%s',(bid,))['status']=='draft'
    assert post(owner,f'/recruitment/{bid}/publish').status_code==400
    assert post(owner,f'/recruitment/{bid}/questions/0',dict(title='加入原因',kind='long',required='on')).status_code==302
    assert post(owner,f'/recruitment/{bid}/publish').status_code==302
    assert query(app,'SELECT status FROM batches WHERE id=%s',(bid,))['status']=='published'
    assert post(owner,f'/recruitment/{bid}/close').status_code==302
    with app.app_context():
        aid=execute("INSERT INTO activities(club_id,created_by,title,description,location,starts_at,ends_at,deadline,capacity,status) VALUES(1,2,'旧待审批活动','兼容现有数据','教室',%s,%s,%s,10,'pending')",(datetime.now()+timedelta(days=2),datetime.now()+timedelta(days=3),datetime.now()+timedelta(days=1)))
        get_db().commit()
    assert owner.get(f'/activities/{aid}/edit').status_code==200
    assert post(owner,f'/activities/{aid}/state',dict(action='publish')).status_code==302


def test_custom_questionnaire_build_publish_answer_and_export(app):
    import csv, io
    owner=login(app)
    fmt=lambda d:d.strftime('%Y-%m-%dT%H:%M')
    result=post(owner,'/recruitment/new',dict(club_id=1,title='自定义招新测试',description='可自定义题目',
        starts_at=fmt(datetime.now()-timedelta(hours=1)),ends_at=fmt(datetime.now()+timedelta(days=3)),departments=['1']))
    assert result.status_code==302 and '/questions' in result.location
    bid=int(result.location.split('/')[2])
    assert query(app,'SELECT status FROM batches WHERE id=%s',(bid,))['status']=='draft'
    assert query(app,'SELECT batch_id FROM batch_questionnaires WHERE batch_id=%s',(bid,))
    assert post(owner,f'/recruitment/{bid}/publish').status_code==400
    guest=app.test_client()
    assert guest.get(f'/recruitment/{bid}').status_code==403
    assert guest.get(f'/recruitment/{bid}/questions').status_code==302
    admin=login(app,'admin','Admin123!')
    assert admin.get(f'/recruitment/{bid}/questions').status_code==403
    assert post(admin,f'/recruitment/{bid}/questions/0',dict(title='越权',kind='short')).status_code==403

    definitions=[('short','会用什么语言？',None),('long','项目经历',None),('single','首选方向','开发\n设计'),
                 ('multiple','感兴趣的活动','编程\n摄影\n讲座'),('select','可参加的部门','技术部\n宣传部'),
                 ('number','每周可投入小时数',None),('date','预计开始日期',None)]
    for kind,title,options in definitions:
        data=dict(kind=kind,title=title,description='请按实际情况填写',required='on')
        if options:data['options']=options
        assert post(owner,f'/recruitment/{bid}/questions/0',data).status_code==302
    questions=query(app,'SELECT COUNT(*) n FROM questionnaire_questions WHERE batch_id=%s',(bid,))
    assert questions['n']==7
    first=query(app,'SELECT id FROM questionnaire_questions WHERE batch_id=%s ORDER BY position LIMIT 1',(bid,))['id']
    assert post(owner,f'/recruitment/{bid}/questions/{first}',dict(kind='short',title='掌握的语言',required='on')).status_code==302
    assert post(owner,f'/recruitment/{bid}/questions/{first}/move',dict(direction='down')).status_code==302
    assert query(app,'SELECT position FROM questionnaire_questions WHERE id=%s',(first,))['position']==2
    assert post(owner,f'/recruitment/{bid}/questions/0',dict(kind='single',title='重复选项',options='相同\n相同')).status_code==400
    assert post(owner,f'/recruitment/{bid}/questions/0',dict(kind='unknown',title='非法题型')).status_code==400
    assert post(owner,f'/recruitment/{bid}/questions/0',dict(kind='short',title='临时题')).status_code==302
    temporary=query(app,'SELECT MAX(id) id FROM questionnaire_questions WHERE batch_id=%s',(bid,))['id']
    assert post(owner,f'/recruitment/{bid}/questions/{temporary}/delete').status_code==302
    assert not query(app,'SELECT id FROM questionnaire_questions WHERE id=%s',(temporary,))
    preview=owner.get(f'/recruitment/{bid}').get_data(as_text=True)
    assert '问卷预览' in preview and '掌握的语言' in preview
    assert post(owner,f'/recruitment/{bid}/publish').status_code==302
    assert post(owner,f'/recruitment/{bid}/questions/{first}',dict(kind='short',title='发布后改题')).status_code==400
    assert post(owner,f'/recruitment/{bid}/questions/{first}/delete').status_code==400
    assert query(app,'SELECT title FROM questionnaire_questions WHERE id=%s',(first,))['title']=='掌握的语言'
    assert guest.get(f'/recruitment/{bid}').status_code==200
    applicant=login(app,'2025003')
    questions=[]
    with app.app_context():
        from clubapp.custom import questions_for_batch
        questions=questions_for_batch(bid)
    option=query(app,'SELECT id FROM batch_options WHERE batch_id=%s',(bid,))['id']
    payload={'option_id':str(option),'name':'申请学生','major':'计算机','grade':'2025','phone':'123'}
    for q in questions:
        values={'short':'=1+1','long':'使用 Python 完成课程项目','number':'12.5','date':'2026-10-01'}
        if q['kind']=='multiple':payload[f"q_{q['id']}"]=[str(o['id']) for o in q['options'][:2]]
        elif q['kind'] in ('single','select'):payload[f"q_{q['id']}"]=str(q['options'][0]['id'])
        else:payload[f"q_{q['id']}"]=values[q['kind']]
    missing={k:v for k,v in payload.items() if k!=f'q_{first}'}
    assert post(applicant,f'/recruitment/{bid}',missing).status_code==400
    assert not query(app,'SELECT id FROM applications WHERE batch_id=%s',(bid,))
    invalid={**payload}
    single=next(q for q in questions if q['kind']=='single')
    invalid[f"q_{single['id']}"]='999999'
    assert post(applicant,f'/recruitment/{bid}',invalid).status_code==400
    invalid={**payload}
    number=next(q for q in questions if q['kind']=='number')
    invalid[f"q_{number['id']}"]='not a number'
    assert post(applicant,f'/recruitment/{bid}',invalid).status_code==400
    response=post(applicant,f'/recruitment/{bid}',payload)
    assert response.status_code==302
    aid=int(response.location.rsplit('/',1)[1])
    assert query(app,'SELECT COUNT(*) n FROM questionnaire_answers WHERE application_id=%s',(aid,))['n']==7
    detail=applicant.get(f'/applications/{aid}').get_data(as_text=True)
    assert '掌握的语言' in detail and '使用 Python 完成课程项目' in detail
    assert '编程、摄影' in detail
    assert post(applicant,f'/recruitment/{bid}',payload).status_code==400
    assert applicant.get(f'/recruitment/{bid}/results').status_code==403
    assert admin.get(f'/recruitment/{bid}/results').status_code==403
    results=owner.get(f'/recruitment/{bid}/results').get_data(as_text=True)
    assert '已提交' in results or '作答 1 人' in results
    csv_text=owner.get(f'/recruitment/{bid}/results?export=csv').get_data(as_text=True).lstrip('\ufeff')
    records=list(csv.reader(io.StringIO(csv_text)))
    assert len(records)==2 and '掌握的语言' in records[0]
    assert "'=1+1" in records[1]
    assert post(owner,f'/applications/{aid}/review',dict(decision='accepted')).status_code==302
    assert query(app,'SELECT status FROM applications WHERE id=%s',(aid,))['status']=='accepted'


def test_custom_questionnaire_ai_uses_saved_answers(app,monkeypatch):
    import clubapp.ai as module
    from clubapp.custom import answers_for_application
    owner=login(app)
    fmt=lambda d:d.strftime('%Y-%m-%dT%H:%M')
    created=post(owner,'/recruitment/new',dict(club_id=1,title='AI 问卷测试',
        starts_at=fmt(datetime.now()-timedelta(hours=1)),ends_at=fmt(datetime.now()+timedelta(days=2)),departments=['1']))
    bid=int(created.location.split('/')[2])
    assert post(owner,f'/recruitment/{bid}/questions/0',dict(kind='long',title='项目经历',required='on')).status_code==302
    qid=query(app,'SELECT id FROM questionnaire_questions WHERE batch_id=%s',(bid,))['id']
    assert post(owner,f'/recruitment/{bid}/publish').status_code==302
    option=query(app,'SELECT id FROM batch_options WHERE batch_id=%s',(bid,))['id']
    applicant=login(app,'2025003')
    submitted=post(applicant,f'/recruitment/{bid}',dict(option_id=str(option),name='申请学生',major='计算机',grade='2025',phone='123',
        **{f'q_{qid}':'使用 Python 完成课程项目'}))
    aid=int(submitted.location.rsplit('/',1)[1])
    with app.app_context():
        answers=answers_for_application(aid,bid)
    assert any(q['answer']=='使用 Python 完成课程项目' for q in answers)
    monkeypatch.setattr(module,'configured',lambda:True)
    def fake_model(kind,data):
        assert kind=='recruit' and '使用 Python 完成课程项目' in data['questionnaire_answers']
        assert 'student_no' not in data and 'phone' not in data
        return '{"summary":"有项目经验","skills":[{"name":"Python","evidence":"使用 Python 完成课程项目"}]}'
    monkeypatch.setattr(module,'ask_model',fake_model)
    assert post(applicant,'/ai/generate',dict(kind='recruit',application_id=aid,consent='on')).status_code==302
    assert query(app,"SELECT COUNT(*) n FROM ai_records WHERE application_id=%s AND status='success'",(aid,))['n']==1


def test_optional_select_can_be_left_unanswered(app):
    owner=login(app)
    fmt=lambda d:d.strftime('%Y-%m-%dT%H:%M')
    response=post(owner,'/recruitment/new',dict(club_id=1,title='选填下拉题测试',
        starts_at=fmt(datetime.now()-timedelta(hours=1)),ends_at=fmt(datetime.now()+timedelta(days=2)),departments=['1']))
    bid=int(response.location.split('/')[2])
    assert post(owner,f'/recruitment/{bid}/questions/0',dict(kind='select',title='偏好的工作方向',options='开发\n设计')).status_code==302
    qid=query(app,'SELECT id FROM questionnaire_questions WHERE batch_id=%s',(bid,))['id']
    assert post(owner,f'/recruitment/{bid}/publish').status_code==302
    option=query(app,'SELECT id FROM batch_options WHERE batch_id=%s',(bid,))['id']
    applicant=login(app,'2025003')
    payload=dict(option_id=str(option),name='申请学生',major='计算机',grade='2025',phone='123')
    assert post(applicant,f'/recruitment/{bid}',{**payload,f'q_{qid}':''}).status_code==302
    answer=query(app,'SELECT qa.answer_text FROM questionnaire_answers qa JOIN applications a ON a.id=qa.application_id WHERE a.batch_id=%s AND qa.question_id=%s',(bid,qid))
    assert answer['answer_text']=='[]'


def test_owner_can_edit_draft_questionnaire_settings_only_before_publish(app):
    owner=login(app)
    fmt=lambda d:d.strftime('%Y-%m-%dT%H:%M')
    start=fmt(datetime.now()+timedelta(hours=1))
    end=fmt(datetime.now()+timedelta(days=2))
    created=post(owner,'/recruitment/new',dict(club_id=1,title='旧标题',description='旧说明',
        starts_at=start,ends_at=end,departments=['1','2']))
    assert created.status_code==302
    bid=int(created.location.split('/')[2])
    settings=f'/recruitment/{bid}/settings'
    page=owner.get(settings).get_data(as_text=True)
    assert '旧标题' in page and '旧说明' in page and '修改问卷基本信息' in page
    assert owner.get('/recruitment/1/settings').status_code==404
    admin=login(app,'admin','Admin123!')
    student=login(app,'2025003')
    assert admin.get(settings).status_code==403
    assert student.get(settings).status_code==403
    changed=dict(title='新标题',description='新说明',starts_at=fmt(datetime.now()+timedelta(hours=2)),
        ends_at=fmt(datetime.now()+timedelta(days=4)),departments=['2'])
    assert post(owner,settings,{**changed,'departments':[]}).status_code==400
    assert post(owner,settings,{**changed,'departments':['4']}).status_code==400
    assert post(owner,settings,{**changed,'ends_at':start}).status_code==400
    assert post(owner,settings,changed).status_code==302
    updated=query(app,'SELECT title,description,starts_at,ends_at FROM batches WHERE id=%s',(bid,))
    assert updated['title']=='新标题' and updated['description']=='新说明'
    assert updated['starts_at'].startswith(changed['starts_at'].replace('T',' '))
    assert updated['ends_at'].startswith(changed['ends_at'].replace('T',' '))
    assert query(app,'SELECT COUNT(*) n FROM batch_options WHERE batch_id=%s',(bid,))['n']==1
    assert query(app,'SELECT department_id FROM batch_options WHERE batch_id=%s',(bid,))['department_id']==2
    assert '新标题' in owner.get(f'/recruitment/{bid}').get_data(as_text=True)
    assert post(owner,f'/recruitment/{bid}/questions/0',dict(kind='short',title='加入原因')).status_code==302
    assert post(owner,f'/recruitment/{bid}/publish').status_code==302
    assert owner.get(settings).status_code==400
    assert post(owner,settings,changed).status_code==400
    assert query(app,'SELECT title FROM batches WHERE id=%s',(bid,))['title']=='新标题'
