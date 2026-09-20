import csv
import io
from flask import Blueprint, render_template, request, redirect, url_for, g, flash, Response
from .db import rows, one, execute, get_db, audit
from .common import login_required, is_admin, admin_required, can_manage, manage_required, visible_clubs, field, integer, ValidationError, now

bp=Blueprint('main',__name__)

@bp.get('/')
@login_required
def dashboard():
    clubs=rows('SELECT c.*, (SELECT count(*) FROM memberships m WHERE m.club_id=c.id AND m.status=\'active\') members FROM clubs c')
    mine=rows('SELECT m.*,c.name FROM memberships m JOIN clubs c ON c.id=m.club_id WHERE m.user_id=%s',(g.user['id'],))
    activities=rows("SELECT a.*,c.name club_name FROM activities a JOIN clubs c ON c.id=a.club_id WHERE a.status='published' AND a.ends_at >= %s ORDER BY a.starts_at LIMIT 5",(now(),))
    notices=rows('SELECT * FROM notifications WHERE recipient_id=%s ORDER BY id DESC LIMIT 4',(g.user['id'],))
    return render_template('dashboard.html',clubs=clubs,mine=mine,activities=activities,notices=notices)

@bp.route('/clubs',methods=['GET','POST'])
@login_required
def clubs():
    if request.method=='POST':
        admin_required()
        owner=one('SELECT id FROM users WHERE student_no=%s',(field('owner_no'),))
        if not owner:raise ValidationError('负责人学号不存在，请先注册该用户。')
        cid=execute('INSERT INTO clubs(name,description) VALUES(%s,%s)',(field('name',80),field('description',4000,False)))
        execute("INSERT INTO memberships(club_id,user_id,role) VALUES(%s,%s,'owner')",(cid,owner['id']))
        audit('创建社团','club',cid,cid);get_db().commit();flash('社团已创建。','success')
        return redirect(url_for('main.club',club_id=cid))
    return render_template('clubs.html',clubs=rows('SELECT * FROM clubs'))

@bp.route('/clubs/<int:club_id>',methods=['GET','POST'])
@login_required
def club(club_id):
    c=one('SELECT * FROM clubs WHERE id=%s',(club_id,),True)
    if request.method=='POST':
        manage_required(club_id)
        action=field('action')
        if action=='department':
            execute('INSERT INTO departments(club_id,name) VALUES(%s,%s)',(club_id,field('name',60)))
        elif action=='edit':
            execute('UPDATE clubs SET name=%s,description=%s WHERE id=%s',(field('name',80),field('description',4000,False),club_id))
        else:raise ValidationError('无效操作。')
        audit('维护社团','club',club_id,club_id,action);get_db().commit()
        return redirect(url_for('main.club',club_id=club_id))
    members=rows('SELECT m.*,u.name,u.student_no,d.name department_name FROM memberships m JOIN users u ON u.id=m.user_id LEFT JOIN departments d ON d.id=m.department_id WHERE m.club_id=%s ORDER BY m.status,m.id',(club_id,)) if can_manage(club_id) else []
    return render_template('club.html',club=c,departments=rows('SELECT * FROM departments WHERE club_id=%s',(club_id,)),members=members)

@bp.post('/members/<int:mid>')
@login_required
def update_member(mid):
    m=one('SELECT * FROM memberships WHERE id=%s',(mid,),True)
    manage_required(m['club_id'])
    # Serialize changes within a club so two owners cannot remove each other concurrently.
    one('SELECT id FROM clubs WHERE id=%s FOR UPDATE',(m['club_id'],),True)
    m=one('SELECT * FROM memberships WHERE id=%s FOR UPDATE',(mid,),True)
    role=field('role');status=field('status');dep=request.form.get('department_id') or None
    if role not in ('member','owner') or status not in ('active','left'):raise ValidationError('无效成员状态。')
    if dep and not one('SELECT id FROM departments WHERE id=%s AND club_id=%s',(dep,m['club_id'])):raise ValidationError('部门不属于该社团。')
    if m['role']=='owner' and m['status']=='active' and (role!='owner' or status!='active'):
        if one("SELECT count(*) n FROM memberships WHERE club_id=%s AND role='owner' AND status='active'",(m['club_id'],))['n']<=1:
            raise ValidationError('社团至少需要保留一位负责人。')
    execute('UPDATE memberships SET role=%s,status=%s,department_id=%s WHERE id=%s',(role,status,dep,mid))
    audit('调整成员','membership',mid,m['club_id']);get_db().commit()
    return redirect(url_for('main.club',club_id=m['club_id']))

@bp.route('/notifications',methods=['GET','POST'])
@login_required
def notifications():
    if request.method=='POST':
        execute('UPDATE notifications SET read_at=%s WHERE recipient_id=%s AND read_at IS NULL',(now(),g.user['id']))
        get_db().commit();return redirect(url_for('main.notifications'))
    return render_template('notifications.html',items=rows('SELECT * FROM notifications WHERE recipient_id=%s ORDER BY id DESC',(g.user['id'],)))

@bp.get('/reports')
@login_required
def reports():
    clubs=visible_clubs()
    cid=integer(request.args.get('club_id') or (clubs[0]['id'] if clubs else 0),0)
    if not cid:return render_template('reports.html',clubs=clubs,club=None)
    manage_required(cid);club=one('SELECT * FROM clubs WHERE id=%s',(cid,),True)
    bid=request.args.get('batch_id','');start=request.args.get('start','');end=request.args.get('end','')
    args=[cid];where='b.club_id=%s'
    if bid:where+=' AND b.id=%s';args.append(integer(bid))
    distributions={}
    for key,title in [('major','专业'),('grade','年级')]:
        distributions[title]=rows(f'SELECT a.{key} label,count(*) n FROM applications a JOIN batches b ON b.id=a.batch_id WHERE {where} GROUP BY a.{key}',args)
    distributions['意向部门']=rows(f'SELECT d.name label,count(*) n FROM applications a JOIN batches b ON b.id=a.batch_id JOIN batch_options o ON o.id=a.option_id JOIN departments d ON d.id=o.department_id WHERE {where} GROUP BY d.id,d.name',args)
    distributions['已确认技能']=rows(f'SELECT s.name label,count(*) n FROM application_skills x JOIN skills s ON s.id=x.skill_id JOIN applications a ON a.id=x.application_id JOIN batches b ON b.id=a.batch_id WHERE {where} AND x.confirmed=1 GROUP BY s.id,s.name',args)
    acts=rows("SELECT a.id,a.title,a.status,count(CASE WHEN r.status='registered' THEN 1 END) registrations,count(CASE WHEN r.status='registered' AND r.checked_at IS NOT NULL THEN 1 END) attended FROM activities a LEFT JOIN registrations r ON r.activity_id=a.id WHERE a.club_id=%s GROUP BY a.id,a.title,a.status",(cid,))
    tw='club_id=%s';ta=[cid]
    from datetime import date
    for value in (start,end):
        if value:
            try:date.fromisoformat(value)
            except ValueError:raise ValidationError('日期格式不正确。')
    if start and end and start>end:raise ValidationError('开始日期不能晚于结束日期。')
    if start:tw+=' AND happened_on >= %s';ta.append(start)
    if end:tw+=' AND happened_on <= %s';ta.append(end)
    totals=one(f"SELECT COALESCE(SUM(CASE WHEN direction='income' THEN amount_cents ELSE 0 END),0) income,COALESCE(SUM(CASE WHEN direction='expense' THEN amount_cents ELSE 0 END),0) expense FROM transactions WHERE {tw}",ta)
    budgets=rows("SELECT f.id,f.purpose,(SELECT COALESCE(sum(quantity*unit_cents),0) FROM budget_items WHERE fund_id=f.id) budget,(SELECT COALESCE(sum(amount_cents),0) FROM transactions WHERE fund_id=f.id AND direction='expense') spent FROM fund_applications f WHERE f.club_id=%s AND f.status='approved'",(cid,))
    if request.args.get('export')=='csv':
        stream=io.StringIO();writer=csv.writer(stream);writer.writerow(['类别','项目','数量或金额'])
        def safe(v):
            value=str(v)
            return "'"+value if value.startswith(('=','+','-','@','\t','\r')) else value
        for title,data in distributions.items():
            for item in data:writer.writerow([title,safe(item['label']),item['n']])
        writer.writerow(['经费','收入',f"{totals['income']/100:.2f}"]);writer.writerow(['经费','支出',f"{totals['expense']/100:.2f}"])
        for a in acts:writer.writerow(['活动报名',safe(a['title']),a['registrations']]);writer.writerow(['活动到场',safe(a['title']),a['attended']])
        return Response('\ufeff'+stream.getvalue(),mimetype='text/csv',headers={'Content-Disposition':'attachment; filename=club-report.csv'})
    return render_template('reports.html',clubs=clubs,club=club,distributions=distributions,activities=acts,totals=totals,budgets=budgets,
        count=one("SELECT count(*) n FROM memberships WHERE club_id=%s AND status='active'",(cid,))['n'],batches=rows('SELECT * FROM batches WHERE club_id=%s',(cid,)))

@bp.get('/audit')
@login_required
def logs():
    clubs=visible_clubs()
    cid=request.args.get('club_id') or (clubs[0]['id'] if clubs else None)
    if not cid:return render_template('logs.html',items=[],clubs=clubs)
    manage_required(cid)
    return render_template('logs.html',clubs=clubs,items=rows('SELECT l.*,u.name actor FROM audit_logs l LEFT JOIN users u ON u.id=l.actor_id WHERE l.club_id=%s ORDER BY l.id DESC LIMIT 300',(cid,)))
