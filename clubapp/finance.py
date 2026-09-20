import uuid
from pathlib import Path
from datetime import date
from flask import Blueprint, render_template, request, redirect, url_for, g, current_app, send_from_directory, flash
from werkzeug.utils import secure_filename
from .db import rows, one, execute, get_db, audit, notify
from .common import login_required, manage_required, admin_required, visible_clubs, field, integer, cents, ValidationError

bp=Blueprint('finance',__name__)

@bp.get('/finance')
@login_required
def index():
    clubs=visible_clubs();cid=integer(request.args.get('club_id') or (clubs[0]['id'] if clubs else 0),0)
    if not cid:return render_template('finance.html',clubs=clubs,club=None)
    manage_required(cid)
    funds=rows('SELECT f.*,(SELECT SUM(quantity*unit_cents) FROM budget_items WHERE fund_id=f.id) total FROM fund_applications f WHERE club_id=%s ORDER BY f.id DESC',(cid,))
    tx=rows('SELECT t.*,(SELECT count(*) FROM receipts r WHERE r.transaction_id=t.id) receipts FROM transactions t WHERE club_id=%s ORDER BY happened_on DESC,id DESC',(cid,))
    return render_template('finance.html',clubs=clubs,club=one('SELECT * FROM clubs WHERE id=%s',(cid,),True),funds=funds,transactions=tx,
        activities=rows('SELECT id,title FROM activities WHERE club_id=%s',(cid,)))

@bp.post('/finance/funds')
@login_required
def create_fund():
    cid=integer(request.form.get('club_id'));manage_required(cid)
    aid=request.form.get('activity_id') or None
    if aid and not one('SELECT id FROM activities WHERE id=%s AND club_id=%s',(aid,cid)):raise ValidationError('活动不属于该社团。')
    names=request.form.getlist('item_name');quantities=request.form.getlist('quantity');prices=request.form.getlist('unit_price')
    if len(names)!=len(quantities) or len(names)!=len(prices) or len(names)>30:raise ValidationError('预算项目格式不正确。')
    items=[]
    for name,quantity,price in zip(names,quantities,prices):
        if not name.strip() and not quantity.strip() and not price.strip():continue
        if not name.strip() or len(name)>120:raise ValidationError('请填写有效预算项目名称。')
        items.append((name.strip(),integer(quantity,1,10000),cents(price)))
    if not items:raise ValidationError('至少填写一个预算项目。')
    fid=execute('INSERT INTO fund_applications(club_id,activity_id,applicant_id,purpose) VALUES(%s,%s,%s,%s)',(cid,aid,g.user['id'],field('purpose',1000)))
    for name,q,p in items:execute('INSERT INTO budget_items(fund_id,name,quantity,unit_cents) VALUES(%s,%s,%s,%s)',(fid,name,q,p))
    audit('提交经费申请','fund',fid,cid);get_db().commit()
    return redirect(url_for('finance.fund',fid=fid))

@bp.route('/finance/funds/<int:fid>',methods=['GET','POST'])
@login_required
def fund(fid):
    f=one('SELECT f.*,c.name club_name,u.name applicant FROM fund_applications f JOIN clubs c ON c.id=f.club_id JOIN users u ON u.id=f.applicant_id WHERE f.id=%s',(fid,),True)
    manage_required(f['club_id'])
    if request.method=='POST':
        admin_required();locked=one('SELECT status FROM fund_applications WHERE id=%s FOR UPDATE',(fid,),True)
        if locked['status']!='pending':raise ValidationError('该经费申请已经审核过。')
        decision=field('decision')
        if decision not in ('approved','rejected'):raise ValidationError('无效审核结果。')
        execute('UPDATE fund_applications SET status=%s WHERE id=%s',(decision,fid))
        execute('INSERT INTO fund_approvals(fund_id,reviewer_id,decision,note) VALUES(%s,%s,%s,%s)',(fid,g.user['id'],decision,field('note',2000,False)))
        notify(f['applicant_id'],f'经费申请 #{fid} 已{"通过" if decision=="approved" else "驳回"}。')
        audit('经费审批','fund',fid,f['club_id'],decision);get_db().commit()
        return redirect(url_for('finance.fund',fid=fid))
    return render_template('fund.html',f=f,items=rows('SELECT * FROM budget_items WHERE fund_id=%s',(fid,)),approvals=rows('SELECT p.*,u.name FROM fund_approvals p JOIN users u ON u.id=p.reviewer_id WHERE p.fund_id=%s',(fid,)))

@bp.post('/finance/transactions')
@login_required
def create_transaction():
    cid=integer(request.form.get('club_id'));manage_required(cid)
    direction=field('direction');amount=cents(field('amount'));fid=request.form.get('fund_id') or None
    if direction not in ('income','expense'):raise ValidationError('收支类型不正确。')
    aid=request.form.get('activity_id') or None
    if aid and not one('SELECT id FROM activities WHERE id=%s AND club_id=%s',(aid,cid)):raise ValidationError('活动不属于该社团。')
    if direction=='expense':
        if not fid:raise ValidationError('支出需要关联已批准的经费申请。')
        f=one('SELECT * FROM fund_applications WHERE id=%s FOR UPDATE',(fid,),True)
        if f['club_id']!=cid or f['status']!='approved':raise ValidationError('该经费申请不属于本社团或尚未批准。')
        if aid and str(f['activity_id'])!=str(aid):raise ValidationError('支出活动与经费申请不一致。')
        aid=f['activity_id']
        budget=one('SELECT SUM(quantity*unit_cents) n FROM budget_items WHERE fund_id=%s',(fid,))['n']
        spent=one("SELECT COALESCE(SUM(amount_cents),0) n FROM transactions WHERE fund_id=%s AND direction='expense'",(fid,))['n']
        if spent+amount>budget:raise ValidationError('本次支出超过该申请的剩余预算。')
    else:fid=None
    happened=field('happened_on')
    try:
        if date.fromisoformat(happened)>date.today():raise ValueError()
    except ValueError:raise ValidationError('收支日期应为有效日期，且不能晚于今天。')
    tid=execute('INSERT INTO transactions(club_id,activity_id,fund_id,recorded_by,direction,amount_cents,category,happened_on,note) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)',
        (cid,aid,fid,g.user['id'],direction,amount,field('category',60),happened,field('note',2000,False)))
    audit('登记收支','transaction',tid,cid);get_db().commit()
    return redirect(url_for('finance.transaction',tid=tid))

@bp.route('/finance/transactions/<int:tid>',methods=['GET','POST'])
@login_required
def transaction(tid):
    t=one('SELECT * FROM transactions WHERE id=%s',(tid,),True);manage_required(t['club_id'])
    if request.method=='POST':
        f=request.files.get('receipt')
        if not f or not f.filename:raise ValidationError('请选择凭证文件。')
        ext=Path(f.filename).suffix.lower();data=f.read()
        signatures={'.pdf':data.startswith(b'%PDF-'),'.png':data.startswith(b'\x89PNG\r\n\x1a\n'),'.jpg':data.startswith(b'\xff\xd8\xff'),'.jpeg':data.startswith(b'\xff\xd8\xff')}
        if not signatures.get(ext):raise ValidationError('凭证仅支持内容正确的 PDF、PNG 和 JPG 文件。')
        name=uuid.uuid4().hex+ext;path=Path(current_app.config['UPLOAD_FOLDER'])/name
        original=Path(f.filename.replace('\\','/')).name[:200]
        try:
            path.write_bytes(data)
            rid=execute('INSERT INTO receipts(transaction_id,uploaded_by,filename,storage_name) VALUES(%s,%s,%s,%s)',(tid,g.user['id'],original,name))
            audit('上传凭证','receipt',rid,t['club_id']);get_db().commit()
        except Exception:
            path.unlink(missing_ok=True);raise
        return redirect(url_for('finance.transaction',tid=tid))
    return render_template('transaction.html',t=t,receipts=rows('SELECT * FROM receipts WHERE transaction_id=%s',(tid,)))

@bp.get('/receipts/<int:rid>')
@login_required
def receipt(rid):
    r=one('SELECT r.*,t.club_id FROM receipts r JOIN transactions t ON t.id=r.transaction_id WHERE r.id=%s',(rid,),True);manage_required(r['club_id'])
    return send_from_directory(current_app.config['UPLOAD_FOLDER'],r['storage_name'],as_attachment=True,download_name=r['filename'])
