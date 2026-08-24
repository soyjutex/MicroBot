#!/bin/bash
# =============================================================================
# MicroBot - Instalador para Debian/Ubuntu
# Instala el bot como servicio systemd.
#
# Uso:  sudo bash install.sh
# Requisitos previos: python3, pip; config.json ya cargado con tus
# credenciales (ver config.example.json).
# =============================================================================

set -e

INSTALL_DIR="/opt/microbot"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== MicroBot installer ==="

# 1. Dependencias minimas
echo "[1/5] Verificando dependencias..."
python3 -c "import requests" 2>/dev/null || pip3 install requests

# 2. Copiar codigo
echo "[2/5] Instalando codigo en ${INSTALL_DIR}..."
mkdir -p "${INSTALL_DIR}/data"
cp "${SCRIPT_DIR}/../bot.py"           "${INSTALL_DIR}/bot.py"
cp "${SCRIPT_DIR}/../test_harness.py"  "${INSTALL_DIR}/test_harness.py"
cp "${SCRIPT_DIR}/../requirements.txt" "${INSTALL_DIR}/requirements.txt"

# 3. Configuracion (NUNCA sobreescribir una existente)
if [ -f "${SCRIPT_DIR}/../config.json" ]; then
    echo "[3/5] Instalando config.json..."
    cp "${SCRIPT_DIR}/../config.json" "${INSTALL_DIR}/config.json"
else
    echo "[3/5] AVISO: no hay config.json local. Copia config.example.json como"
    echo "      ${INSTALL_DIR}/config.json y completa credenciales antes de arrancar."
fi
chmod 600 "${INSTALL_DIR}/config.json" 2>/dev/null || true

# 4. Servicio systemd
echo "[4/5] Instalando servicio systemd..."
cp "${SCRIPT_DIR}/microbot.service" /etc/systemd/system/microbot.service
systemctl daemon-reload
systemctl enable microbot

# Comando global 'microbot' en PATH
ln -sf "${INSTALL_DIR}/bot.py" /usr/local/bin/microbot
chmod +x /usr/local/bin/microbot

# 5. Verificar y arrancar
echo "[5/5] Prueba offline (harness) y arranque..."
cd "${INSTALL_DIR}" && python3 test_harness.py || echo "   AVISO: harness con fallos, revisar antes de confiar"
systemctl restart microbot
sleep 2
systemctl --no-pager status microbot | head -8 || true

echo ""
echo "=== Instalacion completa ==="
echo "  Logs:      journalctl -u microbot -f"
echo "  CLI:       microbot --status | microbot \"consulta\""
echo "  Telegram:  habla con tu bot (/help)"
