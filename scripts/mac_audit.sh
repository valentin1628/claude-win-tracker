#!/usr/bin/env bash
# CI macOS : lance l'appli construite 60 s (au-delà des minuteries de 30 s) sous fs_usage,
# puis échoue si elle a touché un dossier protégé (Bureau, Documents, Photos, iCloud…).
# Ce sont ces accès qui déclenchent les demandes d'autorisation de macOS.
set -uo pipefail
cd "$(dirname "$0")/.."

# De faux journaux Claude Code, pour que l'analyse des coûts tourne aussi.
mkdir -p ~/.claude/projects/demo
echo '{"type":"assistant","timestamp":"2026-01-01T00:00:00Z","requestId":"r","message":{"id":"m","model":"claude-sonnet-4-5","usage":{"input_tokens":10,"output_tokens":5}}}' \
    > ~/.claude/projects/demo/a.jsonl

applog=~/Library/Logs/ClaudeTracker/claude-tracker.log
rm -f ~/Library/Logs/ClaudeTracker/*.log

# Lancée avec open, comme depuis le Finder (dossier courant /, LaunchServices), en mode
# démo pour avoir des chiffres, des notifications et l'historique comme en vrai.
sudo fs_usage -w -f filesys "Claude Usage Tra" > fs.log 2>&1 &
tracer=$!
sleep 2
open -n "dist/Claude Usage Tray.app" --args --demo --exit-after 60
clicks_ok=0
python scripts/mac_clicks.py "$applog" || clicks_ok=1

# CPU au repos (après les clics) : un widget ne doit presque rien consommer.
pid=$(pgrep -f "Claude Usage Tray.app/Contents/MacOS" | head -1)
if [ -n "$pid" ]; then
    # Temps CPU consommé pendant 15 s sans rien faire (ps donne m:ss.cc).
    to_s() { echo "$1" | awk -F: '{print $1 * 60 + $2}'; }
    t1=$(to_s "$(ps -p "$pid" -o time= | tr -d ' ')")
    sleep 15
    t2=$(to_s "$(ps -p "$pid" -o time= | tr -d ' ')")
    echo "CPU au repos sur 15 s : $(echo "scale=2; ($t2 - $t1) * 100 / 15" | bc) %"
fi

# L'appli doit s'être fermée toute seule (--exit-after) : sinon elle est figée.
status=0
for _ in $(seq 1 40); do
    pgrep -f "Claude Usage Tray.app/Contents/MacOS" > /dev/null || break
    sleep 1
done
if pgrep -f "Claude Usage Tray.app/Contents/MacOS" > /dev/null; then
    echo "::error::L'appli ne s'est pas fermée : elle est figée"
    sample "Claude Usage Tray" 3 2>/dev/null | head -80 || true
    pkill -9 -f "Claude Usage Tray.app/Contents/MacOS"
    status=1
fi
sudo kill -INT "$tracer" 2>/dev/null
sleep 1

echo "--- rapports de plantage macOS ---"
ls -la ~/Library/Logs/DiagnosticReports/ 2>/dev/null | grep -i claude && \
    head -60 ~/Library/Logs/DiagnosticReports/*Claude* 2>/dev/null && status=1
echo "--- journal ---"
cat ~/Library/Logs/ClaudeTracker/*.log 2>/dev/null || true
grep -q "Popup affiché" "$applog" || echo "::warning::Aucun clic n'a atteint l'appli (CGEventPost refusé ?)"
echo "--- dossiers ouverts sous \$HOME (aperçu) ---"
grep -oE "$HOME/[^ ]+" fs.log | awk -F/ '{print "/"$2"/"$3"/"$4"/"$5}' | sort | uniq -c | sort -rn | head -40

# Chemins en début de colonne : /System/Volumes/Preboot (frameworks système) n'est pas un disque externe.
protected="[[:space:]]($HOME/(Desktop|Documents|Downloads|Pictures|Movies|Music|Library/Mobile Documents)|/Volumes/)"
if grep -qE "$protected" fs.log; then
    echo "::error::L'appli accède à des dossiers protégés (demandes d'autorisation macOS) :"
    grep -E "$protected" fs.log | head -40
    exit 1
fi
if [ "$clicks_ok" -ne 0 ]; then
    echo "::error::Test des clics en échec"
    exit 1
fi
if [ "$status" -ne 0 ] || grep -q "Exception\|Erreur\|Fatal" ~/Library/Logs/ClaudeTracker/*.log 2>/dev/null; then
    echo "::error::L'appli a planté ou journalisé une erreur (code $status)"
    exit 1
fi
echo "OK : aucun accès à un dossier protégé, arrêt propre."
