from flask import Blueprint, request, jsonify
from app.database import get_db_connection, execute_db, query_db
import json

conditions_bp = Blueprint('conditions', __name__)

# مسار المرحلة 5 (القيود)
@conditions_bp.route('/api/conditions', methods=['GET', 'POST'])
def manage_conditions():
    if request.method == 'POST':
        execute_db('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', 
                   ('schedule_conditions', json.dumps(request.json)))
        return jsonify({'success': True})
    else:
        setting = query_db('SELECT value FROM settings WHERE key = ?', ('schedule_conditions',), one=True)
        saved_conditions = json.loads(setting['value']) if setting and setting['value'] else {}
        return jsonify(saved_conditions)

# مسار المرحلة 6 (إعدادات الخوارزميات)
@conditions_bp.route('/api/algorithm-settings', methods=['GET', 'POST'])
def manage_algo_settings():
    if request.method == 'POST':
        execute_db('INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)', 
                   ('algorithm_settings', json.dumps(request.json)))
        return jsonify({'success': True})
    else:
        setting = query_db('SELECT value FROM settings WHERE key = ?', ('algorithm_settings',), one=True)
        saved_settings = json.loads(setting['value']) if setting and setting['value'] else {}
        return jsonify(saved_settings)