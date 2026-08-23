#!/bin/bash
# =============================================================================
# MicroBot - Instalador para Debian/Ubuntu
# Instala el bot como servicio systemd con permisos root (caja dedicada).
#
# Uso:  sudo bash install.sh
# Requisitos previos: python3, pip; config.json junto a este script ya cargado
# con tus credenciales (ver config.example.json).
# =============================================================================

set -e

INSTALL_DIR="/opt/microbot"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== MicroBot installer ==="

# 1. Dependencias minimas
echo "[1/6] Verificando dependencias..."
python3 -c "import requests" 2>/dev/null || pip3 install requests

# 2. Copiar codigo
echo "[2/6] Instalando codigo en ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}/data" /tmp/microbot-install
cp "${SCRIPT_DIR}/../bot.py"              "${INSTALL_DIR}/bot.py"
cp "${SCRIPT_DIR}/../requirements.txt"    "${INSTALL_DIR}/requirements.txt"

# 3. Configuracion (NUNCA sobreescribir una existente)
if [ -f "${SCRIPT_DIR}/../config.json" ]; then
    echo "[3/6] Instalando config.json..."
    cp "${SCRIPT_DIR}/../config.json"     "${INSTALL_DIR}/config.json"
else
    echo "[3/6] AVISO: no hay config.json local. Copia config.example.json como"
    echo "      ${INSTALL_DIR}/config.json y completa credenciales antes de arrancar."
fi
chmod 600 "${INSTALL_DIR}/config.json" 2>/dev/null || true
chmod +x "${INSTALL_DIR}/bot.py"

# 4. Migrar memoria vieja si existe (desde home del usuario que invoca)
echo "[4/6] Migrando memoria existente (si hay)..."
OLD_JSON="$HOME/.bot_memory.json"
OLD_DB="$HOME/.nexus_brain.db"
if [ -f "$OLD_JSON" ] || [ -f "$OLD_DB" ]; then
    python3 "${SCRIPT_DIR}/migrate_memory.py" "${INSTALL_DIR}/data/microbot.db" || echo "   migracion con warnings (continuo)"
else
    echo "   sin memoria previa que migrar"
fi
chown -R root:root "${INSTALL_DIR}"

# 5. Servicio systemd (root)
echo "[5/6] Instalando servicio systemd..."
cp "${SCRIPT_DIR}/microbot.service" /etc/systemd/system/microbot.service
systemctl daemon-reload
systemctl enable microbot

# 6. Comando global 'microbot' en PATH
ln -sf "${INSTALL_DIR}/bot.py" /usr/local/bin/microbot
chmod +x /usr/local/bin/microbot

echo "[6/6] Arrancando servicio..."
systemctl restart microbot
sleep 2
systemctl --no-pager status microbot | head -8 || true

echo ""
echo "=== Instalacion completa ==="
echo "  Logs:      journalctl -u microbot -f"
echo "  CLI:       microbot --status | microbot \"consulta\""
echo "  Telegram:  habla con tu bot (/help)"
