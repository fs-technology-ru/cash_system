sudo dmesg | grep tty - найти порты последовательных устройств  
udevadm info -a -n /dev/ttyS1 - информация об устройстве на порту  

sudo nano /etc/udev/rules.d/99-myserial.rules
SUBSYSTEM=="tty", KERNEL=="ttyS*", ATTRS{id}=="PNP0501", SYMLINK+="myserial"
sudo udevadm control --reload-rules
sudo udevadm trigger
ls -l /dev/myserial