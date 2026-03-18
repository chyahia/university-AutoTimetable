import sqlite3
from flask import g
import os
import sys

def get_base_path():
    """يحدد مسار قاعدة البيانات أينما كان التطبيق يعمل."""
    if getattr(sys, 'frozen', False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

DATABASE_FILE = os.path.join(get_base_path(), 'schedule_database.db')

def get_db_connection():
    """تنشئ أو تجلب الاتصال الحالي بقاعدة البيانات."""
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE_FILE)
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.row_factory = sqlite3.Row
    return g.db

def close_db(e=None):
    """إغلاق قاعدة البيانات بعد انتهاء الطلب."""
    db = g.pop('db', None)
    if db is not None:
        db.close()

def query_db(query, args=(), one=False):
    """دالة مساعدة لجلب البيانات (SELECT)"""
    conn = get_db_connection()
    cur = conn.execute(query, args)
    rv = [dict(row) for row in cur.fetchall()]
    return (rv[0] if rv else None) if one else rv

def execute_db(query, args=()):
    """دالة مساعدة لتنفيذ التعديلات (INSERT, UPDATE, DELETE)"""
    conn = get_db_connection()
    conn.execute(query, args)
    conn.commit()

def init_db(app):
    """إنشاء الجداول الأساسية عند بدء تشغيل الخادم."""
    with app.app_context():
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # إنشاء الجداول الأساسية تماماً كما في مشروعك القديم
        cursor.execute('''CREATE TABLE IF NOT EXISTS levels (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS teachers (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS rooms (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE, type TEXT NOT NULL)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS courses (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, room_type TEXT NOT NULL, teacher_id INTEGER, FOREIGN KEY (teacher_id) REFERENCES teachers (id) ON DELETE SET NULL)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS course_levels (course_id INTEGER, level_id INTEGER, PRIMARY KEY (course_id, level_id), FOREIGN KEY (course_id) REFERENCES courses (id) ON DELETE CASCADE, FOREIGN KEY (level_id) REFERENCES levels (id) ON DELETE CASCADE)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)''')
        
        conn.commit()