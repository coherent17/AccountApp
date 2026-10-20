#!/bin/sh
# 將原始碼同步到 Windows 建置資料夾
B=/mnt/c/Users/User/accountApp_build/src
mkdir -p "$B"
cd /home/coherent/accountApp && cp -r app tools tests run.py "$B"/ 2>/dev/null; rm -rf "$B"/tools/__pycache__
[ -f accountApp.spec ] && cp accountApp.spec "$B"/
for f in build.bat version_info.txt requirements.txt; do [ -f $f ] && cp $f "$B"/; done
exit 0
