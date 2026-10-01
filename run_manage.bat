@echo off
REM A-SOUL 挂机进程管理器 —— 由 Windows 计划任务每 5 分钟调用一次
REM 用法：schtasks /Run /TN "ASOUL_Heartbeat_Manage"

cd /d "%~dp0"
if not exist "logs" mkdir "logs"
"G:\fqq13\miniconda3\pythonw.exe" "%~dp0manage_asoul_heartbeat.py" >> "%~dp0logs\manage.log" 2>&1