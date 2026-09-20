from datetime import datetime, timedelta
from flask import Blueprint, render_template, request, redirect, url_for, g, flash, abort
from .db import rows, one, execute, get_db, audit, notify
from .common import login_required, can_manage, manage_required, admin_required, visible_clubs, member, field, integer, moment, now, ValidationError

bp=Blueprint('activities',__name__)

@bp.get('/activities')
@login_required
def index():
    items=rows('SELECT a.*,c.name club_name,(SELECT count(*) FROM registrations r WHERE r.activity_id=a.id AND r.status=\'registered\') registered FROM activities a JOIN clubs c ON c.id=a.club_id ORDER BY a.id DESC')
    return render_template('activities.html',items=[a for a in items if a['status'] in ('published','ended','cancelled') or can_manage(a['club_id'])],clubs=visible_clubs())

@bp.route('/activities/new',methods=['GET','POST'])
@bp.route('/activities/<int:aid>/edit',methods=['GET','POST'])
@login_required
def edit(aid=None):
    a=one('SELECT * FROM activities WHERE id=%s',(aid,),True) if aid else None
    clubs=visible_clubs()
    if a:manage_required(a['club_id'])
    if not clubs:abort(403)
    if a and a['status'] not in ('draft','rejected','published'):raise ValidationError('当前状态不能修改活动。')
    if request.method=='POST':
        cid=a['club_id'] if a else integer(request.form.get('club_id'));manage_required(cid)
        start=moment('starts_at');end=moment('ends_at');deadline=moment('deadline')
        if not deadline<=start<end:raise ValidationError('报名截止时间不得晚于开始时间，结束时间须晚于开始时间。')
        values=(field('title',120),field('description',10000),field('location',150),start,end,deadline,integer(request.form.get('capacity'),1,10000))
        if a:
            locked=one('SELECT status FROM activities WHERE id=%s FOR UPDATE',(aid,),True)
            if locked['status'] not in ('draft','rejected','published'):
                raise ValidationError('活动状态已经改变，请刷新后重试。')
            used=one("SELECT count(*) n FROM registrations WHERE activity_id=%s AND status='registered'",(aid,))['n']
            if values[-1]<used:raise ValidationError('人数上限不能小于已报名人数。')
            execute('UPDATE activities SET title=%s,description=%s,location=%s,starts_at=%s,ends_at=%s,deadline=%s,capacity=%s WHERE id=%s',values+(aid,))
            for r in rows("SELECT user_id FROM registrations WHERE activity_id=%s AND status='registered'",(aid,)):notify(r['user_id'],f'活动「{values[0]}」信息已更新，请查看新的时间与地点。')
        else:
            aid=execute('INSERT INTO activities(title,description,location,starts_at,ends_at,deadline,capacity,club_id,created_by) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',values+(cid,g.user['id']))
        audit('保存活动','activity',aid,cid);get_db().commit()
        return redirect(url_for('activities.detail',aid=aid))
    return render_template('activity_form.html',a=a,clubs=clubs)

def get_activity(aid):
    a=one('SELECT a.*,c.name club_name FROM activities a JOIN clubs c ON c.id=a.club_id WHERE a.id=%s',(aid,),True)
    if a['status'] not in ('published','ended','cancelled') and not can_manage(a['club_id']):abort(403)
    return a

@bp.get('/activities/<int:aid>')
@login_required
def detail(aid):
    a=get_activity(aid)
    return render_template('activity.html',a=a,registration=one('SELECT * FROM registrations WHERE activity_id=%s AND user_id=%s',(aid,g.user['id'])),
        registrations=rows('SELECT r.*,u.name,u.student_no FROM registrations r JOIN users u ON u.id=r.user_id WHERE r.activity_id=%s',(aid,)) if can_manage(a['club_id']) else [],
        registered=one("SELECT count(*) n FROM registrations WHERE activity_id=%s AND status='registered'",(aid,))['n'],
        approvals=rows('SELECT x.*,u.name FROM activity_approvals x JOIN users u ON u.id=x.reviewer_id WHERE x.activity_id=%s',(aid,)),
        feedback=rows('SELECT f.* FROM feedback f JOIN registrations r ON r.id=f.registration_id WHERE r.activity_id=%s',(aid,)) if can_manage(a['club_id']) else [],
        retrospective=one('SELECT * FROM retrospectives WHERE activity_id=%s',(aid,)),
        records=rows('SELECT * FROM ai_records WHERE activity_id=%s ORDER BY id DESC',(aid,)) if can_manage(a['club_id']) else [])

@bp.post('/activities/<int:aid>/state')
@login_required
def state(aid):
    a=one('SELECT * FROM activities WHERE id=%s FOR UPDATE',(aid,),True);manage_required(a['club_id'])
    action=field('action')
    if action=='submit' and a['status'] in ('draft','rejected'):status='pending'
    elif action in ('approve','reject') and a['status']=='pending':
        admin_required();status='published' if action=='approve' else 'rejected'
        execute('INSERT INTO activity_approvals(activity_id,reviewer_id,decision,note) VALUES(%s,%s,%s,%s)',(aid,g.user['id'],'approved' if action=='approve' else 'rejected',field('note',2000,False)))
        notify(a['created_by'],f'活动「{a["title"]}」审核结果：{"通过" if action=="approve" else "驳回"}。')
    elif action=='cancel' and a['status'] in ('draft','pending','published','rejected'):status='cancelled'
    elif action=='end' and a['status']=='published':
        if now()<a['starts_at']:raise ValidationError('活动尚未开始。')
        status='ended'
    else:raise ValidationError('当前状态不能执行此操作。')
    execute('UPDATE activities SET status=%s WHERE id=%s',(status,aid))
    if status=='cancelled':
        for r in rows("SELECT user_id FROM registrations WHERE activity_id=%s AND status='registered'",(aid,)):notify(r['user_id'],f'活动「{a["title"]}」已取消。')
    audit('活动状态变更','activity',aid,a['club_id'],status);get_db().commit()
    return redirect(url_for('activities.detail',aid=aid))

@bp.post('/activities/<int:aid>/join')
@login_required
def join(aid):
    a=one('SELECT * FROM activities WHERE id=%s FOR UPDATE',(aid,),True)
    if not member(a['club_id']):raise ValidationError('请先加入该社团。')
    if a['status']!='published' or now()>a['deadline']:raise ValidationError('报名已截止或活动未发布。')
    r=one('SELECT * FROM registrations WHERE activity_id=%s AND user_id=%s',(aid,g.user['id']))
    action=field('action')
    if action=='join':
        if r and r['status']=='registered':raise ValidationError('你已经报名。')
        count=one("SELECT count(*) n FROM registrations WHERE activity_id=%s AND status='registered'",(aid,))['n']
        if count>=a['capacity']:raise ValidationError('报名人数已满。')
        execute("INSERT INTO registrations(activity_id,user_id) VALUES(%s,%s) ON DUPLICATE KEY UPDATE status='registered',checked_at=NULL",(aid,g.user['id']))
    elif action=='cancel':
        if not r or r['checked_at']:raise ValidationError('没有可取消的报名。')
        execute("UPDATE registrations SET status='cancelled' WHERE id=%s",(r['id'],))
    else:raise ValidationError('无效操作。')
    audit('报名变更','activity',aid,a['club_id'],action);get_db().commit()
    return redirect(url_for('activities.detail',aid=aid))

@bp.post('/registrations/<int:rid>/checkin')
@login_required
def checkin(rid):
    r=one('SELECT r.*,a.club_id,a.status activity_status,a.starts_at,a.ends_at FROM registrations r JOIN activities a ON a.id=r.activity_id WHERE r.id=%s FOR UPDATE',(rid,),True)
    if r['user_id']!=g.user['id'] and not can_manage(r['club_id']):abort(403)
    start=datetime.strptime(r['starts_at'],'%Y-%m-%d %H:%M:%S')-timedelta(minutes=30)
    if r['activity_status']!='published' or r['status']!='registered' or not start<=datetime.now()<=datetime.strptime(r['ends_at'],'%Y-%m-%d %H:%M:%S'):
        raise ValidationError('仅可在活动开始前 30 分钟至结束时间内签到。')
    if r['checked_at']:raise ValidationError('已经签到。')
    execute('UPDATE registrations SET checked_at=%s WHERE id=%s',(now(),rid));audit('活动签到','registration',rid,r['club_id']);get_db().commit()
    return redirect(url_for('activities.detail',aid=r['activity_id']))

@bp.post('/activities/<int:aid>/feedback')
@login_required
def feedback(aid):
    a=get_activity(aid)
    r=one("SELECT * FROM registrations WHERE activity_id=%s AND user_id=%s AND status='registered' AND checked_at IS NOT NULL",(aid,g.user['id']))
    if a['status']!='ended' or not r:raise ValidationError('活动结束后，已签到的成员才能提交反馈。')
    execute('INSERT INTO feedback(registration_id,organization,content,venue,comment) VALUES(%s,%s,%s,%s,%s)',
        (r['id'],integer(request.form.get('organization'),1,5),integer(request.form.get('content'),1,5),integer(request.form.get('venue'),1,5),field('comment',3000,False)))
    audit('提交反馈','activity',aid,a['club_id']);get_db().commit();flash('感谢你的反馈。','success')
    return redirect(url_for('activities.detail',aid=aid))

@bp.post('/activities/<int:aid>/retrospective')
@login_required
def retrospective(aid):
    a=get_activity(aid);manage_required(a['club_id'])
    if a['status']!='ended':raise ValidationError('活动结束后才能确认复盘。')
    ai_id=request.form.get('ai_record_id') or None
    if ai_id and not one("SELECT id FROM ai_records WHERE id=%s AND activity_id=%s AND kind='review' AND status='success'",(ai_id,aid)):raise ValidationError('请选择本活动的有效复盘生成记录。')
    execute('INSERT INTO retrospectives(activity_id,body,edited_by,ai_record_id) VALUES(%s,%s,%s,%s) ON DUPLICATE KEY UPDATE body=VALUES(body),edited_by=VALUES(edited_by),ai_record_id=VALUES(ai_record_id),updated_at=CURRENT_TIMESTAMP',
        (aid,field('body',20000),g.user['id'],ai_id));audit('保存活动复盘','activity',aid,a['club_id']);get_db().commit()
    return redirect(url_for('activities.detail',aid=aid))
