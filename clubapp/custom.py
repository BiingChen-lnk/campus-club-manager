"""Editable recruitment questionnaires for newly created batches."""
import csv
import io
import json
from datetime import date
from decimal import Decimal, InvalidOperation
from flask import Blueprint, Response, abort, g, redirect, render_template, request, url_for
from .common import login_required, manage_required, field, integer, now, ValidationError
from .db import one, rows, execute, get_db, audit

bp = Blueprint('custom', __name__)
KINDS = {
    'short': '单行文本', 'long': '多行文本', 'single': '单选',
    'multiple': '多选', 'select': '下拉选择', 'number': '数字', 'date': '日期',
}
CHOICES = {'single', 'multiple', 'select'}
MAX_QUESTIONS = 30
MAX_OPTIONS = 30


def is_custom(bid):
    return bool(one('SELECT batch_id FROM batch_questionnaires WHERE batch_id=%s', (bid,)))


def get_custom_batch(bid):
    batch = one('SELECT b.*,c.name club_name FROM batches b JOIN clubs c ON c.id=b.club_id WHERE b.id=%s', (bid,), True)
    if not is_custom(bid):
        abort(404)
    return batch


def questions_for_batch(bid, locked=False):
    suffix = ' FOR UPDATE' if locked else ''
    questions = rows('SELECT * FROM questionnaire_questions WHERE batch_id=%s ORDER BY position,id' + suffix, (bid,))
    for question in questions:
        question['options'] = rows('SELECT * FROM questionnaire_options WHERE question_id=%s ORDER BY position,id' + suffix, (question['id'],))
    return questions


def display_answer(question, raw):
    if question['kind'] not in CHOICES:
        return raw
    try:
        chosen = json.loads(raw)
    except (TypeError, ValueError):
        return ''
    labels = {option['id']: option['label'] for option in question['options']}
    return '、'.join(labels[id] for id in chosen if id in labels)


def answers_for_application(application_id, bid):
    answers = {item['question_id']: item['answer_text'] for item in rows(
        'SELECT question_id,answer_text FROM questionnaire_answers WHERE application_id=%s', (application_id,))}
    questions = questions_for_batch(bid)
    for question in questions:
        question['answer'] = display_answer(question, answers.get(question['id'], ''))
    return questions


def validate_answers(questions):
    answer_values = []
    for question in questions:
        key = f"q_{question['id']}"
        if question['kind'] in CHOICES:
            values = request.form.getlist(key)
            if len(values) > MAX_OPTIONS or len(values) != len(set(values)):
                raise ValidationError('选项数量或内容不正确。')
            allowed = {str(option['id']) for option in question['options']}
            if any(value not in allowed for value in values):
                raise ValidationError('问卷中包含无效选项。')
            if question['kind'] != 'multiple' and len(values) > 1:
                raise ValidationError('这道题只能选择一个选项。')
            if question['required'] and not values:
                raise ValidationError(f"请填写「{question['title']}」。")
            value = json.dumps([int(item) for item in values], ensure_ascii=False)
        else:
            value = request.form.get(key, '').strip()
            maximum = 2000 if question['kind'] == 'long' else 255
            if len(value) > maximum:
                raise ValidationError(f"「{question['title']}」最多填写 {maximum} 字。")
            if question['required'] and not value:
                raise ValidationError(f"请填写「{question['title']}」。")
            if value and question['kind'] == 'number':
                try:
                    number = Decimal(value)
                    if not number.is_finite() or abs(number) > 1000000000:
                        raise ValueError()
                except (InvalidOperation, ValueError):
                    raise ValidationError(f"「{question['title']}」需要填写有效数字。")
            if value and question['kind'] == 'date':
                try:
                    parsed = date.fromisoformat(value)
                    if not 1900 <= parsed.year <= 2100:
                        raise ValueError()
                except ValueError:
                    raise ValidationError(f"「{question['title']}」需要填写有效日期。")
        answer_values.append((question['id'], value))
    return answer_values


def draft_for_edit(bid):
    batch = get_custom_batch(bid)
    manage_required(batch['club_id'])
    locked = one('SELECT status FROM batches WHERE id=%s FOR UPDATE', (bid,), True)
    if locked['status'] != 'draft':
        raise ValidationError('问卷发布后不能修改题目或选项，以免历史答卷失去对应关系。')
    return batch


@bp.get('/recruitment/<int:bid>/questions')
@login_required
def editor(bid):
    batch = get_custom_batch(bid)
    manage_required(batch['club_id'])
    return render_template('question_editor.html', batch=batch,
                           questions=questions_for_batch(bid), kinds=KINDS, choices=CHOICES)


@bp.post('/recruitment/<int:bid>/questions/<int:qid>')
@login_required
def save_question(bid, qid):
    batch = draft_for_edit(bid)
    existing = one('SELECT * FROM questionnaire_questions WHERE id=%s AND batch_id=%s', (qid, bid)) if qid else None
    if qid and not existing:
        abort(404)
    if not qid and one('SELECT COUNT(*) n FROM questionnaire_questions WHERE batch_id=%s', (bid,))['n'] >= MAX_QUESTIONS:
        raise ValidationError(f'每份问卷最多 {MAX_QUESTIONS} 道题。')
    kind = field('kind', 20)
    if kind not in KINDS:
        raise ValidationError('不支持的题型。')
    title = field('title', 120)
    description = field('description', 500, False)
    required = int(request.form.get('required') == 'on')
    option_labels = []
    if kind in CHOICES:
        lines = request.form.get('options', '').splitlines()
        option_labels = [line.strip() for line in lines if line.strip()]
        if not 2 <= len(option_labels) <= MAX_OPTIONS or any(len(label) > 120 for label in option_labels):
            raise ValidationError(f'选择题需要 2～{MAX_OPTIONS} 个选项，每项最多 120 字。')
        if len({label.casefold() for label in option_labels}) != len(option_labels):
            raise ValidationError('选项不能重复。')
    if existing:
        execute('UPDATE questionnaire_questions SET title=%s,description=%s,kind=%s,required=%s WHERE id=%s',
                (title, description, kind, required, qid))
        execute('DELETE FROM questionnaire_options WHERE question_id=%s', (qid,))
    else:
        position = one('SELECT COALESCE(MAX(position),0)+1 n FROM questionnaire_questions WHERE batch_id=%s', (bid,))['n']
        qid = execute('INSERT INTO questionnaire_questions(batch_id,position,title,description,kind,required) VALUES(%s,%s,%s,%s,%s,%s)',
                      (bid, position, title, description, kind, required))
    for position, label in enumerate(option_labels, 1):
        execute('INSERT INTO questionnaire_options(question_id,position,label) VALUES(%s,%s,%s)', (qid, position, label))
    audit('编辑招新题目', 'batch', bid, batch['club_id'])
    get_db().commit()
    return redirect(url_for('custom.editor', bid=bid))


@bp.post('/recruitment/<int:bid>/questions/<int:qid>/delete')
@login_required
def delete_question(bid, qid):
    batch = draft_for_edit(bid)
    question = one('SELECT id FROM questionnaire_questions WHERE id=%s AND batch_id=%s', (qid, bid), True)
    execute('DELETE FROM questionnaire_questions WHERE id=%s', (question['id'],))
    remaining = rows('SELECT id FROM questionnaire_questions WHERE batch_id=%s ORDER BY position,id FOR UPDATE', (bid,))
    for position, item in enumerate(remaining, 1):
        execute('UPDATE questionnaire_questions SET position=%s WHERE id=%s', (position, item['id']))
    audit('删除招新题目', 'batch', bid, batch['club_id'])
    get_db().commit()
    return redirect(url_for('custom.editor', bid=bid))


@bp.post('/recruitment/<int:bid>/questions/<int:qid>/move')
@login_required
def move_question(bid, qid):
    batch = draft_for_edit(bid)
    direction = field('direction', 4)
    if direction not in ('up', 'down'):
        raise ValidationError('无效的排序方向。')
    questions = rows('SELECT id,position FROM questionnaire_questions WHERE batch_id=%s ORDER BY position,id FOR UPDATE', (bid,))
    ids = [question['id'] for question in questions]
    if qid not in ids:
        abort(404)
    index = ids.index(qid)
    other = index + (-1 if direction == 'up' else 1)
    if 0 <= other < len(ids):
        left, right = questions[index], questions[other]
        execute('UPDATE questionnaire_questions SET position=%s WHERE id=%s', (right['position'], left['id']))
        execute('UPDATE questionnaire_questions SET position=%s WHERE id=%s', (left['position'], right['id']))
        audit('调整招新题目顺序', 'batch', bid, batch['club_id'])
        get_db().commit()
    return redirect(url_for('custom.editor', bid=bid))


@bp.post('/recruitment/<int:bid>/publish')
@login_required
def publish(bid):
    batch = draft_for_edit(bid)
    if not one('SELECT id FROM questionnaire_questions WHERE batch_id=%s LIMIT 1', (bid,)):
        raise ValidationError('请至少添加一道题目再发布。')
    if batch['ends_at'] <= now():
        raise ValidationError('招新截止时间已过，请重新创建批次。')
    execute("UPDATE batches SET status='published' WHERE id=%s", (bid,))
    audit('发布自定义招新问卷', 'batch', bid, batch['club_id'])
    get_db().commit()
    return redirect(url_for('recruitment.batch', bid=bid))


@bp.get('/recruitment/<int:bid>/results')
@login_required
def results(bid):
    batch = get_custom_batch(bid)
    manage_required(batch['club_id'])
    questions = questions_for_batch(bid)
    applications = rows('SELECT id,name,student_no,major,grade,status,created_at FROM applications WHERE batch_id=%s ORDER BY id DESC', (bid,))
    answers = rows('SELECT qa.application_id,qa.question_id,qa.answer_text FROM questionnaire_answers qa JOIN applications a ON a.id=qa.application_id WHERE a.batch_id=%s', (bid,))
    by_application = {(item['application_id'], item['question_id']): item['answer_text'] for item in answers}
    if request.args.get('export') == 'csv':
        output = io.StringIO()
        writer = csv.writer(output)
        departments = {item['id']: item['department'] for item in rows(
            'SELECT a.id,d.name department FROM applications a JOIN batch_options o ON o.id=a.option_id JOIN departments d ON d.id=o.department_id WHERE a.batch_id=%s', (bid,))}
        def safe(value):
            value = str(value or '')
            return "'" + value if value.startswith(('=', '+', '-', '@', '\t', '\r', '\n')) else value
        writer.writerow(['姓名', '学号', '专业', '年级', '状态', '提交时间', '意向部门'] + [safe(question['title']) for question in questions])
        for application in applications:
            writer.writerow([safe(application[key]) for key in ('name','student_no','major','grade','status','created_at')] +
                            [safe(departments.get(application['id']))] +
                            [safe(display_answer(question, by_application.get((application['id'], question['id']), ''))) for question in questions])
        return Response('\ufeff' + output.getvalue(), mimetype='text/csv',
                        headers={'Content-Disposition': 'attachment; filename=recruitment-results.csv'})
    for question in questions:
        question['answered'] = 0
        question['counts'] = {option['id']: 0 for option in question['options']}
        for application in applications:
            raw = by_application.get((application['id'], question['id']), '')
            if question['kind'] in CHOICES:
                try: chosen = json.loads(raw)
                except ValueError: chosen = []
                if chosen: question['answered'] += 1
                for id in chosen:
                    if id in question['counts']: question['counts'][id] += 1
            elif raw:
                question['answered'] += 1
    return render_template('question_results.html', batch=batch, questions=questions, applications=applications)
