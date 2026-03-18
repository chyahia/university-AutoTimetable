from app import create_app

app = create_app()

if __name__ == '__main__':
    # تشغيل السيرفر في وضع التطوير (Debug Mode) ليسهل علينا تتبع الأخطاء
    app.run(debug=True, port=5000)