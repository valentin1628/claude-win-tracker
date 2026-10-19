#!/usr/bin/env bash
# Construit l'appli macOS (dist/Claude Usage Tray.app) puis le disque d'installation
# (dist/ClaudeTracker-<version>-macOS-arm64.dmg). À lancer sur un Mac Apple Silicon.
# Usage : ./build_mac.sh [python]
set -euo pipefail
cd "$(dirname "$0")"
PY="${1:-python3}"
APP_NAME="Claude Usage Tray"

"$PY" -m pip install --upgrade pip --quiet
"$PY" -m pip install -e ".[dev]" --quiet

echo "Tests..."
"$PY" -m pytest -q

version=$("$PY" -c "import claude_tracker; print(claude_tracker.__version__)")
echo "Version $version"

echo "Icône..."
"$PY" -m claude_tracker.render --icns assets/app.icns

echo "Construction de l'appli (PyInstaller)..."
"$PY" -m PyInstaller --noconfirm --clean --windowed \
    --name "$APP_NAME" \
    --icon assets/app.icns \
    --osx-bundle-identifier com.valentin1628.claudeusagetray \
    --paths src \
    --collect-data customtkinter \
    --hidden-import pystray._darwin \
    launcher.py

app="dist/$APP_NAME.app"
plist="$app/Contents/Info.plist"
# Appli de barre de menus : pas d'icône dans le Dock.
/usr/libexec/PlistBuddy -c "Add :LSUIElement bool true" "$plist" 2>/dev/null \
    || /usr/libexec/PlistBuddy -c "Set :LSUIElement true" "$plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $version" "$plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $version" "$plist"
# Info.plist modifié : on refait la signature ad hoc (obligatoire sur Apple Silicon).
codesign --force --deep --sign - "$app"
codesign --verify --deep "$app"

echo "Test de démarrage..."
"$app/Contents/MacOS/$APP_NAME" --demo --exit-after 8

echo "Disque d'installation..."
staging=$(mktemp -d)
cp -R "$app" "$staging/"
ln -s /Applications "$staging/Applications"
dmg="dist/ClaudeTracker-$version-macOS-arm64.dmg"
rm -f "$dmg"
hdiutil create -volname "$APP_NAME" -srcfolder "$staging" -ov -format UDZO "$dmg"
rm -rf "$staging"

echo "OK -> $dmg"
