RDEPENDS_${PN}_append_tegra = "${@' tegra-bup-payload libubootenv-fake' if d.getVar('PREFERRED_PROVIDER_virtual/bootloader').startswith('cboot') else ''}"

FILESEXTRAPATHS_prepend := "${THISDIR}/files:"
SRC_URI_append_mender-uboot = " \
    file://mender \
    file://mender-client-commit.service \
    file://mender-client-commit.sh \
    file://verify-boot-rootfs-slot-alignment-uboot \
"

FILES_${PN}_append_mender-uboot = " ${systemd_system_unitdir}/mender-client-commit.service"
FILES_${PN}_append_mender-uboot = " ${sysconfdir}/mender/mender-client-commit.sh"
FILES_${PN}_append_mender-uboot = " ${bindir}/mender"
FILES_${PN}_append_mender-uboot = " ${sysconfdir}/mender/verify-boot-rootfs-slot-alignment-uboot"

SYSTEMD_SERVICE_${PN}_append_mender-uboot = " mender-client-commit.service"

do_install_append_mender-uboot() {
    mv ${D}${bindir}/mender ${D}${bindir}/mender_override
    install -m 0755 ${WORKDIR}/mender ${D}${bindir}/mender
    install -d ${D}${sysconfdir}/mender/scripts
    install -m 0755 ${WORKDIR}/mender-client-commit.sh ${D}${sysconfdir}/mender/mender-client-commit.sh 
    install -m 0644 ${WORKDIR}/mender-client-commit.service ${D}${systemd_system_unitdir}/mender-client-commit.service
    install -m 0755 ${WORKDIR}/verify-boot-rootfs-slot-alignment-uboot ${D}${sysconfdir}/mender/verify-boot-rootfs-slot-alignment-uboot
}
