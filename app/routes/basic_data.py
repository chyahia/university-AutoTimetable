from flask import Blueprint, request, jsonify
from app.database import get_db_connection, query_db

# إنشاء Blueprint خاص بهذه المرحلة
basic_data_bp = Blueprint('basic_data', __name__)

# ====== مسارات جلب البيانات (GET) ======
@basic_data_bp.route('/teachers', methods=['GET'])
def get_teachers():
    return jsonify(query_db('SELECT id, name FROM teachers'))

@basic_data_bp.route('/rooms', methods=['GET'])
def get_rooms():
    return jsonify(query_db('SELECT id, name, type FROM rooms'))

@basic_data_bp.route('/api/levels', methods=['GET'])
def get_levels():
    levels = query_db('SELECT name FROM levels ORDER BY name')
    return jsonify([lvl['name'] for lvl in levels])

@basic_data_bp.route('/api/courses', methods=['GET'])
def get_courses():
    from app.database import query_db
    # جلب المواد مع المستويات المرتبطة بها كنص واحد
    courses = query_db('''
        SELECT c.id, c.name, c.room_type, group_concat(l.name, '، ') as levels
        FROM courses c
        LEFT JOIN course_levels cl ON c.id = cl.course_id
        LEFT JOIN levels l ON cl.level_id = l.id
        GROUP BY c.id
    ''')
    return jsonify(courses)

# ====== مسارات إضافة البيانات (POST) ======
@basic_data_bp.route('/api/teachers', methods=['POST'])
def add_teachers():
    names = request.json.get('names', [])
    if not names: return jsonify({"error": "قائمة الأساتذة فارغة"}), 400
    conn = get_db_connection()
    added = 0
    for name in names:
        conn.execute('INSERT OR IGNORE INTO teachers (name) VALUES (?)', (name,))
        if conn.total_changes > 0: added += 1
    conn.commit()
    return jsonify({"success": True, "message": f"تمت إضافة {added} أساتذة."})

@basic_data_bp.route('/api/rooms', methods=['POST'])
def add_rooms():
    names = request.json.get('names', [])
    room_type = request.json.get('type')
    if not names or not room_type: return jsonify({"error": "البيانات غير مكتملة"}), 400
    conn = get_db_connection()
    added = 0
    for name in names:
        conn.execute('INSERT OR IGNORE INTO rooms (name, type) VALUES (?, ?)', (name, room_type))
        if conn.total_changes > 0: added += 1
    conn.commit()
    return jsonify({"success": True, "message": f"تمت إضافة {added} قاعات."})

@basic_data_bp.route('/api/levels', methods=['POST'])
def add_levels():
    levels = request.json.get('levels', [])
    if not levels: return jsonify({"error": "قائمة المستويات فارغة"}), 400
    conn = get_db_connection()
    added = 0
    for level in levels:
        conn.execute('INSERT OR IGNORE INTO levels (name) VALUES (?)', (level,))
        if conn.total_changes > 0: added += 1
    conn.commit()
    return jsonify({"success": True, "message": f"تمت إضافة {added} مستويات."})

@basic_data_bp.route('/api/students/bulk', methods=['POST'])
def add_courses_bulk():
    courses = request.json
    if not courses: return jsonify({"error": "لا توجد بيانات"}), 400
    conn = get_db_connection()
    cursor = conn.cursor()
    added = 0
    for c in courses:
        cursor.execute('INSERT INTO courses (name, room_type) VALUES (?, ?)', (c['name'], c['room_type']))
        course_id = cursor.lastrowid
        for level_name in c.get('levels', []):
            level_row = cursor.execute('SELECT id FROM levels WHERE name = ?', (level_name,)).fetchone()
            if level_row:
                cursor.execute('INSERT INTO course_levels (course_id, level_id) VALUES (?, ?)', (course_id, level_row['id']))
        added += 1
    conn.commit()
    return jsonify({"success": True, "message": f"تمت إضافة {added} مقررات بنجاح."})