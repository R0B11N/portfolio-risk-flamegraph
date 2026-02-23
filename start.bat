@echo off
echo ================================================
echo   Portfolio Risk Flamegraph - Starting Servers
echo ================================================
echo.

:: Start backend (FastAPI on port 8000)
echo [1/2] Starting backend API on http://localhost:8000 ...
start "RiskFlamegraph-Backend" cmd /k "cd /d %~dp0backend && py -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload"

:: Wait a moment for backend to initialize
timeout /t 2 /nobreak > nul

:: Start frontend (static server on port 3000)
echo [2/2] Starting frontend on http://localhost:3000 ...
start "RiskFlamegraph-Frontend" cmd /k "cd /d %~dp0frontend && py -m http.server 3000"

:: Wait a moment then open browser
timeout /t 2 /nobreak > nul
echo.
echo ================================================
echo   Both servers running. Opening browser...
echo   Backend:  http://localhost:8000
echo   Frontend: http://localhost:3000
echo ================================================
start http://localhost:3000
