#!/bin/zsh
# Auf dem Mac als Administrator im Terminal ausführen (Solad liegt beim Benutzer "solad"):
#   zsh /Users/solad/Solad/deploy/installieren.sh
set -e
ZIEL=/Library/LaunchDaemons/de.solad.app.plist
sudo cp /Users/solad/Solad/deploy/de.solad.app.daemon.plist $ZIEL
sudo chown root:wheel $ZIEL
sudo chmod 644 $ZIEL
sudo launchctl bootout system/de.solad.app 2>/dev/null || true
sudo launchctl bootstrap system $ZIEL
sleep 5
curl -s localhost:8000/api/status | head -c 200; echo
echo "Fertig: http://<IP-des-Mac>:8000"
