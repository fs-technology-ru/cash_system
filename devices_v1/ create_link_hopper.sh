#!/bin/bash

RULE_FILE="/etc/udev/rules.d/99-smart-hopper.rules"

echo "Создаю правило udev для SMART Hopper..."

sudo bash -c "cat > $RULE_FILE" <<EOF
SUBSYSTEM=="tty", ATTRS{idVendor}=="191c", ATTRS{idProduct}=="4104", SYMLINK+="smart_hopper"
EOF

echo "Правило записано в $RULE_FILE"

echo "Перезагружаю udev правила..."
sudo udevadm control --reload-rules

echo "Запускаю udev trigger..."
sudo udevadm trigger

echo "Готово! Проверь /dev/smart_hopper"
