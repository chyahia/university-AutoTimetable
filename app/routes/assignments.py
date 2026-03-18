from flask import Blueprint, jsonify, request
from app.database import get_db_connection, execute_db, query_db

assignments_bp = Blueprint('assignments', __name__)

# جلب كافة الأساتذة والمواد مع حالة الإسناد الحالية
@assignments_bp.route('/api/assignments/data', methods=['GET'])
def get_assignments_data():
    teachers = query_db('SELECT * FROM teachers')
    # نجلب المواد مع اسم الأستاذ المسندة إليه (إن وُجد)
    courses = query_db('''
        SELECT c.id, c.name, c.room_type, c.teacher_id, t.name as teacher_name, group_concat(l.name, '، ') as levels
        FROM courses c
        LEFT JOIN teachers t ON c.teacher_id = t.id
        LEFT JOIN course_levels cl ON c.id = cl.course_id
        LEFT JOIN levels l ON cl.level_id = l.id
        GROUP BY c.id
    ''')
    return jsonify({'teachers': teachers, 'courses': courses})

# تخصيص (إسناد) مجموعة مواد لأستاذ
@assignments_bp.route('/api/assignments/assign', methods=['POST'])
def assign_courses():
    data = request.json
    teacher_id = data.get('teacher_id')
    course_ids = data.get('course_ids', [])
    
    if not teacher_id or not course_ids:
        return jsonify({'error': 'بيانات مفقودة'}), 400
        
    conn = get_db_connection()
    for cid in course_ids:
        conn.execute('UPDATE courses SET teacher_id = ? WHERE id = ?', (teacher_id, cid))
    conn.commit()
    return jsonify({'success': True})

# إلغاء إسناد مادة واحدة (للنقر المزدوج على المادة)
@assignments_bp.route('/api/assignments/unassign_course/<int:course_id>', methods=['POST'])
def unassign_course(course_id):
    execute_db('UPDATE courses SET teacher_id = NULL WHERE id = ?', (course_id,))
    return jsonify({'success': True})

# إلغاء إسناد كل المواد لأستاذ (للنقر المزدوج على الأستاذ)
@assignments_bp.route('/api/assignments/unassign_teacher/<int:teacher_id>', methods=['POST'])
def unassign_teacher(teacher_id):
    execute_db('UPDATE courses SET teacher_id = NULL WHERE teacher_id = ?', (teacher_id,))
    return jsonify({'success': True})