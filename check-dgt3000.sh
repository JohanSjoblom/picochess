#!/bin/sh
set -eu

I2C_BUS="${I2C_BUS:-1}"
ADDRS="${ADDRS:-08 28}"

say() {
    echo "$1"
}

if [ ! -e "/dev/i2c-$I2C_BUS" ]; then
    say "I2C bus /dev/i2c-$I2C_BUS not found"
    exit 1
fi

if ! command -v i2cdetect >/dev/null 2>&1; then
    say "i2cdetect not found; install i2c-tools to probe I2C"
    exit 2
fi

probe_output=$(i2cdetect -y "$I2C_BUS" 2>/dev/null | tr -s ' ')

for addr in $ADDRS; do
    if echo "$probe_output" | grep -Eq "(^| )$addr( |$)"; then
        say "DGT3000 I2C address detected: 0x$addr"
        exit 0
    fi
done

say "No DGT3000 I2C address detected"
exit 1
