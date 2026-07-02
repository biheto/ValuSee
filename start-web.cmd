@echo off
cd /d "%~dp0web"
"C:\nvm4w\nodejs\node.exe" "%~dp0web\node_modules\vite\bin\vite.js" --host 127.0.0.1 --port 5173
