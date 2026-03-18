import os

# المجلدات التي لا نريد دمجها (مثل البيئة الوهمية وقاعدة البيانات)
IGNORE_FOLDERS = ['venv', '__pycache__', '.git', 'instance', '.vscode']
# أنواع الملفات التي نريد دمجها
ALLOWED_EXTENSIONS = ['.py', '.html', '.js', '.css']

output_file = 'project_full_context.txt'

with open(output_file, 'w', encoding='utf-8') as outfile:
    for root, dirs, files in os.walk('.'):
        # استثناء المجلدات غير المرغوبة
        dirs[:] = [d for d in dirs if d not in IGNORE_FOLDERS]
        
        for file in files:
            if any(file.endswith(ext) for ext in ALLOWED_EXTENSIONS):
                filepath = os.path.join(root, file)
                outfile.write(f"\n{'='*60}\n")
                outfile.write(f"--- File: {filepath} ---\n")
                outfile.write(f"{'='*60}\n\n")
                
                try:
                    with open(filepath, 'r', encoding='utf-8') as infile:
                        outfile.write(infile.read())
                except Exception as e:
                    outfile.write(f"[تعذر قراءة الملف: {e}]\n")
                outfile.write("\n")

print(f"✅ تم تجميع كل أكواد المشروع بنجاح في ملف: {output_file}")