import subprocess, sys

result = subprocess.run(
    ['npx', 'vercel', 'logs', 'repon-bi-plataforma.vercel.app', '-n', '20', '--output', 'raw'],
    capture_output=True, text=True, cwd='C:/Users/negoc/.gemini/antigravity/scratch/powerbi_python'
)
print("STDOUT:", result.stdout[:3000])
print("STDERR:", result.stderr[:2000])
