from flask import Blueprint, request, jsonify
from app.database import get_db_connection, execute_db, query_db
import json

structure_bp = Blueprint('structure', __name__)

# جلب هيكل الجدول المحفوظ مسبقاً
@structure_bp.route('/api/structure', methods=['GET'])
def get_structure():
    setting = query_db('SELECT value FROM settings WHERE key = ?', ('schedule_structure',), one=True)
    if setting:
        return jsonify(json.loads(setting['value']))
    return jsonify([])

# حفظ هيكل الجدول
@structure_bp.route('/api/structure', methods=['POST'])
def save_structure():
    structure_data = request.json
    # تخزين الهيكل كملف JSON داخل جدول الإعدادات
    execute_db('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', 
               ('schedule_structure', json.dumps(structure_data)))
    return jsonify({'success': True})

# جلب أسماء المدرجات فقط (لاستخدامها في قيود القاعات المحددة)
@structure_bp.route('/api/halls', methods=['GET'])
def get_halls():
    halls = query_db('SELECT id, name FROM rooms WHERE type = ?', ('مدرج',))
    return jsonify([dict(h) for h in halls])