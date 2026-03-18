from flask import Flask, render_template, jsonify
import os
import signal
from app.database import init_db, close_db
from app.routes.basic_data import basic_data_bp
from app.routes.manage_data import manage_data_bp
from app.routes.assignments import assignments_bp
from app.routes.structure import structure_bp
from app.routes.conditions import conditions_bp
from app.routes.generation import generation_bp
from app.routes.backup import backup_bp
from app.routes.export import export_bp

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = 'chy_secret_key_2026'
    
    # تهيئة قاعدة البيانات وإنشاء الجداول
    init_db(app)
    
    # إغلاق قاعدة البيانات تلقائياً عند انتهاء الطلبات
    app.teardown_appcontext(close_db)
    
    @app.route('/')
    def index():
        return render_template('index.html')    

    @app.route('/shutdown', methods=['POST'])
    def shutdown():
        print("جاري إيقاف الخادم بناءً على طلب المستخدم...")
        os.kill(os.getpid(), signal.SIGINT)
        return jsonify({"message": "تم إيقاف الخادم بنجاح"})

    # تسجيل مسارات المرحلة الأولى (Basic Data)
    app.register_blueprint(basic_data_bp)
    app.register_blueprint(manage_data_bp)
    app.register_blueprint(assignments_bp)
    app.register_blueprint(structure_bp)
    app.register_blueprint(conditions_bp)
    app.register_blueprint(generation_bp)
    app.register_blueprint(backup_bp)
    app.register_blueprint(export_bp)

    return app