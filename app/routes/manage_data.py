from flask import Blueprint, jsonify
from app.database import execute_db
from flask import Blueprint, jsonify, request

# إنشاء Blueprint خاص بإدارة البيانات
manage_data_bp = Blueprint('manage_data', __name__)

@manage_data_bp.route('/api/teachers/<int:id>', methods=['DELETE'])
def delete_teacher(id):
    execute_db('DELETE FROM teachers WHERE id = ?', (id,))
    return jsonify({"success": True})

@manage_data_bp.route('/api/rooms/<int:id>', methods=['DELETE'])
def delete_room(id):
    execute_db('DELETE FROM rooms WHERE id = ?', (id,))
    return jsonify({"success": True})

@manage_data_bp.route('/api/levels/<name>', methods=['DELETE'])
def delete_level(name):
    execute_db('DELETE FROM levels WHERE name = ?', (name,))
    return jsonify({"success": True})

@manage_data_bp.route('/api/courses/<int:id>', methods=['DELETE'])
def delete_course(id):
    execute_db('DELETE FROM courses WHERE id = ?', (id,))
    return jsonify({"success": True})

# ====== مسارات التعديل (PUT) ======

@manage_data_bp.route('/api/teachers/<int:id>', methods=['PUT'])
def update_teacher(id):
    new_name = request.json.get('name')
    if not new_name: return jsonify({"error": "الاسم مطلوب"}), 400
    execute_db('UPDATE teachers SET name = ? WHERE id = ?', (new_name, id))
    return jsonify({"success": True})

@manage_data_bp.route('/api/rooms/<int:id>', methods=['PUT'])
def update_room(id):
    new_name = request.json.get('name')
    if not new_name: return jsonify({"error": "الاسم مطلوب"}), 400
    execute_db('UPDATE rooms SET name = ? WHERE id = ?', (new_name, id))
    return jsonify({"success": True})

@manage_data_bp.route('/api/levels/<old_name>', methods=['PUT'])
def update_level(old_name):
    new_name = request.json.get('name')
    if not new_name: return jsonify({"error": "الاسم مطلوب"}), 400
    execute_db('UPDATE levels SET name = ? WHERE name = ?', (new_name, old_name))
    return jsonify({"success": True})

@manage_data_bp.route('/api/courses/<int:id>', methods=['PUT'])
def update_course(id):
    new_name = request.json.get('name')
    if not new_name: return jsonify({"error": "الاسم مطلوب"}), 400
    execute_db('UPDATE courses SET name = ? WHERE id = ?', (new_name, id))
    return jsonify({"success": True})