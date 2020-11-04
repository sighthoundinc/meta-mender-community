#!/bin/sh

/etc/mender/verify-boot-rootfs-slot-alignment-uboot || exit 0

if [ -f /var/lib/mender/mender-install-success ]; then
    /usr/bin/mender -commit
    rc=$?
    if [ $rc -eq 0 ]; then
        rm /var/lib/mender/mender-install-success
    fi
fi
