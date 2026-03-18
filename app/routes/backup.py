from flask import Blueprint, send_file, request, jsonify
import os
from app.database import DATABASE_FILE

backup_bp = Blueprint('backup', __name__)

# مسار تصدير (تحميل) النسخة الاحتياطية
@backup_bp.route('/api/backup/export', methods=['GET'])
def export_db():
    if os.path.exists(DATABASE_FILE):
        return send_file(DATABASE_FILE, as_attachment=True, download_name='schedule_backup.db')
    return jsonify({"error": "قاعدة البيانات غير موجودة"}), 404

# مسار استيراد (رفع) النسخة الاحتياطية
@backup_bp.route('/api/backup/import', methods=['POST'])
def import_db():
    if 'file' not in request.files:
        return jsonify({"error": "لم يتم إرفاق ملف"}), 400
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({"error": "لم يتم اختيار ملف"}), 400
    
    if file and file.filename.endswith('.db'):
        # استبدال قاعدة البيانات الحالية بالملف المرفوع
        file.save(DATABASE_FILE)
        return jsonify({"success": True, "message": "تم استعادة النسخة الاحتياطية بنجاح. سيتم إعادة تحميل النظام."})
    else:
        return jsonify({"error": "صيغة الملف غير صالحة. يجب أن يكون ملف بصيغة .db"}), 400