"""
PDF Generator - Genera PDFs en la raiz del proyecto
Lee los archivos enhanced.md de brain y genera PDFs en la raiz
"""

import os
import sys
import subprocess

def create_html_from_markdown(md_file, html_file):
    """Convierte Markdown a HTML"""
    try:
        import markdown2
    except ImportError:
        print("[*] Instalando markdown2...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "markdown2", "-q"])
        import markdown2
    
    with open(md_file, 'r', encoding='utf-8') as f:
        md_content = f.read()
    
    html_body = markdown2.markdown(
        md_content,
        extras=["fenced-code-blocks", "tables", "header-ids", "break-on-newline"]
    )
    
    html_template = """<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <title>AI-videoCreator Documentation</title>
    <style>
        @page { size: A4; margin: 2cm; }
        body {
            font-family: 'Segoe UI', Arial, sans-serif;
            line-height: 1.7;
            color: #2c3e50;
            max-width: 1000px;
            margin: 0 auto;
            padding: 20px;
        }
        h1 {
            color: #2980b9;
            border-bottom: 4px solid #3498db;
            padding-bottom: 12px;
            margin-top: 30px;
            font-size: 2.2em;
        }
        h2 {
            color: #16a085;
            border-bottom: 2px solid #1abc9c;
            padding-bottom: 8px;
            margin-top: 25px;
            font-size: 1.8em;
        }
        h3 { color: #8e44ad; margin-top: 20px; font-size: 1.4em; }
        code {
            background-color: #ecf0f1;
            padding: 3px 8px;
            border-radius: 4px;
            font-family: 'Consolas', monospace;
            font-size: 0.9em;
            color: #c0392b;
        }
        pre {
            background-color: #2c3e50;
            color: #ecf0f1;
            border-radius: 6px;
            padding: 18px;
            overflow-x: auto;
        }
        pre code { background-color: transparent; color: #ecf0f1; padding: 0; }
        table {
            border-collapse: collapse;
            width: 100%;
            margin: 25px 0;
            box-shadow: 0 2px 5px rgba(0,0,0,0.1);
        }
        th, td { border: 1px solid #bdc3c7; padding: 14px; text-align: left; }
        th {
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-weight: 600;
        }
        tr:nth-child(even) { background-color: #f8f9fa; }
        blockquote {
            border-left: 5px solid #3498db;
            background-color: #ebf5fb;
            padding: 15px 20px;
            margin: 20px 0;
            border-radius: 5px;
        }
        .note {
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            color: white;
            padding: 20px;
            border-radius: 8px;
            margin: 30px 0;
        }
        hr {
            border: none;
            height: 3px;
            background: linear-gradient(to right, #3498db, #9b59b6);
            margin: 40px 0;
        }
    </style>
</head>
<body>
""" + html_body + """
    <div class="note">
        <strong>Nota:</strong> Los diagramas Mermaid se muestran como codigo. 
        Para visualizarlos, abra el archivo .md en GitHub o VS Code.
    </div>
</body>
</html>
"""
    
    with open(html_file, 'w', encoding='utf-8') as f:
        f.write(html_template)
    
    return html_file

def convert_html_to_pdf_chrome(html_file, pdf_file):
    """Convierte HTML a PDF usando Chrome"""
    chrome_paths = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
    ]
    
    chrome_exe = None
    for path in chrome_paths:
        if os.path.exists(path):
            chrome_exe = path
            break
    
    if not chrome_exe:
        raise FileNotFoundError("Chrome no encontrado")
    
    html_abs = os.path.abspath(html_file)
    pdf_abs = os.path.abspath(pdf_file)
    
    cmd = [
        chrome_exe,
        "--headless",
        "--disable-gpu",
        "--print-to-pdf=" + pdf_abs,
        "--no-margins",
        html_abs
    ]
    
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    
    if result.returncode == 0 and os.path.exists(pdf_abs):
        return True
    else:
        raise Exception(f"Chrome fallo: {result.stderr}")

def main():
    # Rutas
    brain_dir = r"C:\Users\raulr\.gemini\antigravity\brain\4b3d4d52-ee66-406f-bc6a-2a65b32adafb"
    project_root = os.path.dirname(os.path.abspath(__file__))
    
    files = [
        ("implementation_plan_enhanced.md", "implementation_plan.pdf"),
        ("refactoring_comparison_enhanced.md", "refactoring_comparison.pdf")
    ]
    
    print("=" * 70)
    print("  GENERADOR DE PDFs - Guardando en raiz del proyecto")
    print("=" * 70)
    
    for md_name, pdf_name in files:
        md_path = os.path.join(brain_dir, md_name)
        pdf_path = os.path.join(project_root, pdf_name)
        html_path = os.path.join(project_root, md_name.replace('.md', '_temp.html'))
        
        if not os.path.exists(md_path):
            print(f"\n[!] No encontrado: {md_name}")
            continue
        
        print(f"\n[*] Procesando: {md_name}")
        print(f"    Origen: {md_path}")
        print(f"    Destino: {pdf_path}")
        
        try:
            # MD -> HTML
            create_html_from_markdown(md_path, html_path)
            print(f"[OK] HTML creado")
            
            # HTML -> PDF
            convert_html_to_pdf_chrome(html_path, pdf_path)
            print(f"[OK] PDF generado: {pdf_name}")
            
            # Limpiar HTML temporal
            if os.path.exists(html_path):
                os.remove(html_path)
            
        except Exception as e:
            print(f"[ERROR] {str(e)}")
    
    print(f"\n{'='*70}")
    print(f"[OK] PDFs guardados en: {project_root}")
    print("=" * 70)

if __name__ == "__main__":
    main()
