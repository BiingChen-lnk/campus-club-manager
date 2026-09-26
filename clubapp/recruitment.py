from flask import Blueprint, render_template, request, redirect, url_for, g, flash, abort
from .db import rows, one, execute, get_db, audit, notify
from .common import login_required, can_manage, manage_required, owned_clubs, field, now, integer, ValidationError, is_admin
from .custom import is_custom, questions_for_batch, validate_answers, answers_for_application, batch_settings_from_form

bp=Blueprint('recruitment',__name__)
SLOTS=['周一至周五晚上','周六上午','周六下午','周六晚上','周日上午','周日下午','周日晚上']

@bp.get('/recruitment')
def index():
    batches=rows('SELECT b.*,c.name club_name,(SELECT count(*) FROM applications a WHERE a.batch_id=b.id) total FROM batches b JOIN clubs c ON c.id=b.club_id ORDER BY b.id DESC')
    batches=[b for b in batches if b['status']!='draft' or can_manage(b['club_id'])]
    mine=rows('SELECT a.*,b.title FROM applications a JOIN batches b ON b.id=a.batch_id WHERE a.user_id=%s ORDER BY a.id DESC',(g.user['id'],)) if g.user else []
    return render_template('recruitment.html',batches=batches,mine=mine,clubs=owned_clubs())

@bp.route('/recruitment/new',methods=['GET','POST'])
@login_required
def new():
    clubs=owned_clubs();cid=integer(request.values.get('club_id') or (clubs[0]['id'] if clubs else 0),0)
    if not cid:abort(403)
    manage_required(cid)
    if request.method=='POST':
        title, description, starts, ends, departments=batch_settings_from_form(cid)
        bid=execute("INSERT INTO batches(club_id,title,description,starts_at,ends_at,status,created_by) VALUES(%s,%s,%s,%s,%s,'draft',%s)",
                    (cid,title,description,starts,ends,g.user['id']))
        execute('INSERT INTO batch_questionnaires(batch_id) VALUES(%s)',(bid,))
        for dep in sorted(departments):execute('INSERT INTO batch_options(batch_id,department_id) VALUES(%s,%s)',(bid,dep))
        audit('创建招新问卷草稿','batch',bid,cid);get_db().commit()
        return redirect(url_for('custom.editor',bid=bid))
    return render_template('batch_form.html',clubs=clubs,cid=cid,departments=rows('SELECT * FROM departments WHERE club_id=%s',(cid,)))

@bp.route('/recruitment/<int:bid>',methods=['GET','POST'])
def batch(bid):
    b=one('SELECT b.*,c.name club_name FROM batches b JOIN clubs c ON c.id=b.club_id WHERE b.id=%s',(bid,),True)
    custom=is_custom(bid)
    if b['status']=='draft' and not can_manage(b['club_id']):abort(403)
    if request.method=='POST':
        if not g.user:return redirect(url_for('auth.login',next=request.path))
        if is_admin():abort(403)
        b=one('SELECT * FROM batches WHERE id=%s FOR UPDATE',(bid,),True)
        if b['status']!='published' or not b['starts_at']<=now()<=b['ends_at']:raise ValidationError('当前不在问卷填写时间内。')
        option=integer(request.form.get('option_id'))
        if not one('SELECT id FROM batch_options WHERE id=%s AND batch_id=%s',(option,bid)):raise ValidationError('请选择本轮开放的部门。')
        if custom:
            answers=validate_answers(questions_for_batch(bid,locked=True))
            values=(field('name',40),g.user['student_no'],field('major',80),field('grade',30),field('phone',40),'','','','')
        else:
            selected=set(request.form.getlist('slots'))
            if not selected or not selected.issubset(SLOTS):raise ValidationError('请选择有效的可参与时段。')
            skill_text=field('skill_text',1000,False)
            values=(field('name',40),g.user['student_no'],field('major',80),field('grade',30),field('phone',40),
                    field('experience',5000,False),field('reason',5000),field('interests',3000,False),skill_text)
        aid=execute('INSERT INTO applications(batch_id,user_id,option_id,name,student_no,major,grade,phone,experience,reason,interests,skill_text) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)',
            (bid,g.user['id'],option)+values)
        if custom:
            for qid,answer in answers:
                execute('INSERT INTO questionnaire_answers(application_id,question_id,answer_text) VALUES(%s,%s,%s)',(aid,qid,answer))
        else:
            for slot in selected:execute('INSERT INTO availability(application_id,slot) VALUES(%s,%s)',(aid,slot))
            for skill in {s.strip() for s in skill_text.replace('，',',').split(',') if s.strip()}:
                if len(skill)>40:raise ValidationError('每个技能名称最多 40 字，请用逗号分隔。')
                execute('INSERT INTO skills(name) VALUES(%s) ON DUPLICATE KEY UPDATE name=VALUES(name)',(skill,))
                sid=one('SELECT id FROM skills WHERE name=%s',(skill,))['id']
                execute("INSERT INTO application_skills(application_id,skill_id,source,confirmed) VALUES(%s,%s,'self',1)",(aid,sid))
        audit('提交招新问卷','application',aid,b['club_id']);get_db().commit();flash('问卷已提交。','success')
        return redirect(url_for('recruitment.application',aid=aid))
    options=rows('SELECT o.id,d.name FROM batch_options o JOIN departments d ON d.id=o.department_id WHERE o.batch_id=%s',(bid,))
    apps=rows('SELECT a.*,d.name department_name FROM applications a JOIN batch_options o ON o.id=a.option_id JOIN departments d ON d.id=o.department_id WHERE a.batch_id=%s ORDER BY a.id DESC',(bid,)) if can_manage(b['club_id']) else []
    mine=one('SELECT id FROM applications WHERE batch_id=%s AND user_id=%s',(bid,g.user['id'])) if g.user else None
    if custom:
        return render_template('batch_custom.html',batch=b,options=options,applications=apps,mine=mine,questions=questions_for_batch(bid),open=b['status']=='published' and b['starts_at']<=now()<=b['ends_at'])
    return render_template('batch.html',batch=b,options=options,applications=apps,mine=mine,slots=SLOTS,open=b['status']=='published' and b['starts_at']<=now()<=b['ends_at'])

@bp.post('/recruitment/<int:bid>/close')
@login_required
def close(bid):
    b=one('SELECT * FROM batches WHERE id=%s FOR UPDATE',(bid,),True);manage_required(b['club_id'])
    execute("UPDATE batches SET status='closed' WHERE id=%s",(bid,));audit('关闭招新','batch',bid,b['club_id']);get_db().commit()
    return redirect(url_for('recruitment.batch',bid=bid))

def get_application(aid):
    if is_admin():abort(403)
    a=one('SELECT a.*,b.club_id,b.title batch_title,d.name department_name,o.department_id FROM applications a JOIN batches b ON b.id=a.batch_id JOIN batch_options o ON o.id=a.option_id JOIN departments d ON d.id=o.department_id WHERE a.id=%s',(aid,),True)
    if a['user_id']!=g.user['id'] and not can_manage(a['club_id']):abort(403)
    return a

@bp.get('/applications/<int:aid>')
@login_required
def application(aid):
    a=get_application(aid)
    return render_template('application.html',a=a,skills=rows('SELECT x.*,s.name FROM application_skills x JOIN skills s ON s.id=x.skill_id WHERE x.application_id=%s',(aid,)),
        slots=rows('SELECT slot FROM availability WHERE application_id=%s',(aid,)),records=rows('SELECT * FROM ai_records WHERE application_id=%s ORDER BY id DESC',(aid,)),
        custom=is_custom(a['batch_id']),answers=answers_for_application(aid,a['batch_id']) if is_custom(a['batch_id']) else [])

@bp.post('/applications/<int:aid>/review')
@login_required
def review(aid):
    a=get_application(aid);manage_required(a['club_id'])
    locked=one('SELECT status FROM applications WHERE id=%s FOR UPDATE',(aid,),True)
    if locked['status']!='pending':raise ValidationError('该申请已经审核过。')
    decision=field('decision')
    if decision not in ('accepted','rejected'):raise ValidationError('无效审核结果。')
    execute('UPDATE applications SET status=%s,reviewed_by=%s,review_note=%s,reviewed_at=%s WHERE id=%s',
            (decision,g.user['id'],field('note',2000,False),now(),aid))
    if decision=='accepted':
        execute("INSERT INTO memberships(club_id,user_id,department_id) VALUES(%s,%s,%s) ON DUPLICATE KEY UPDATE department_id=VALUES(department_id),status='active'",(a['club_id'],a['user_id'],a['department_id']))
    notify(a['user_id'],f"你的招新申请「{a['batch_title']}」已{'录取' if decision=='accepted' else '驳回'}。")
    audit('审核招新','application',aid,a['club_id'],decision);get_db().commit()
    return redirect(url_for('recruitment.application',aid=aid))

@bp.post('/applications/<int:aid>/skills')
@login_required
def confirm_skills(aid):
    a=get_application(aid)
    if a['user_id']!=g.user['id']:abort(403)
    selected={integer(v) for v in request.form.getlist('skills')}
    valid={r['id'] for r in rows("SELECT id FROM application_skills WHERE application_id=%s AND source='ai'",(aid,))}
    if not selected.issubset(valid):raise ValidationError('技能记录不正确。')
    execute("UPDATE application_skills SET confirmed=0 WHERE application_id=%s AND source='ai'",(aid,))
    for sid in selected:execute('UPDATE application_skills SET confirmed=1 WHERE id=%s',(sid,))
    audit('确认提取技能','application',aid,a['club_id']);get_db().commit();flash('技能确认已保存。','success')
    return redirect(url_for('recruitment.application',aid=aid))
