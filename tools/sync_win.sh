#!/bin/sh
# 將原始碼同步到 Windows 建置資料夾（Qt、WebView2 與打包都只能在 Windows 執行）
B=/mnt/c/Users/User/accountApp_build/src
mkdir -p "$B"
cd /home/coherent/accountApp || exit 1
for d in app v3 tools tests; do
  rm -rf "$B/$d" && cp -r "$d" "$B/"
done
mkdir -p "$B/packaging" && cp -r packaging/. "$B/packaging/"      # 保留 packaging/build、dist（打包結果）
find "$B" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null
cp requirements.txt requirements-v2.txt "$B"/
exit 0
