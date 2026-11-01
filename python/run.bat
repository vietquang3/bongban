@echo off
cd /d %~dp0
python -m pip install -r requirements.txt
python pingpong_game.py
pause
