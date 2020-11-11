RDEPENDS_${PN}_append_tegra = "${@' tegra-bup-payload libubootenv-fake' if d.getVar('PREFERRED_PROVIDER_virtual/bootloader').startswith('cboot') else ''}"

FILESEXTRAPATHS_prepend := "${THISDIR}/files:"
SRC_URI_append = " \
    file://mender \
    file://mender-client-commit.service \
    file://mender-client-commit.sh \
    file://mender-tegra-verify-boot-rootfs-slot-alignment-uboot \
    file://mender-tegra-verify-boot-rootfs-slot-alignment-cboot \
    file://mender-tegra-verify-boot-rootfs-slot-alignment-no-redundant-bootloader \
"

FILES_${PN} += " \
                    ${systemd_system_unitdir}/mender-client-commit.service \
                    ${bindir}/mender-client-commit.sh \
                    ${bindir}/mender_base \
                    ${bindir}/mender-tegra-verify-boot-rootfs-slot-alignment \
"

SYSTEMD_SERVICE_${PN} += "mender-client-commit.service"

install_commit_service() {
    # Rename the mender binary as mender_override.  We'll override with a script that records how it's used
    mv ${D}${bindir}/mender ${D}${bindir}/mender_override
    install -m 0755 ${WORKDIR}/mender ${D}${bindir}/mender
    install -d ${D}${sysconfdir}/mender/scripts
    install -m 0755 ${WORKDIR}/mender-client-commit.sh ${D}${bindir}/mender-client-commit.sh 
    install -m 0644 ${WORKDIR}/mender-client-commit.service ${D}${systemd_system_unitdir}/mender-client-commit.service
}

# By default, install the cboot version of the slot alignment verify script
install_slot_align_verify() {
    install -m 0755 ${WORKDIR}/mender-tegra-verify-boot-rootfs-slot-alignment-cboot ${D}${bindir}/mender-tegra-verify-boot-rootfs-slot-alignment
}


# When mender-uboot override is defined, install the u-boot version.  This one is important for ensuring slots are aligned
# between uboot and the rootfs before taking actions like update
install_slot_align_verify_mender-uboot() {
    install -m 0755 ${WORKDIR}/mender-tegra-verify-boot-rootfs-slot-alignment-uboot ${D}${bindir}/mender-tegra-verify-boot-rootfs-slot-alignment
}

# This verify script is a no-op, since there's nothing to do if redundant bootloader is not supported
install_slot_align_verify_no_redundant_bootloader() {
    install -m 0755 ${WORKDIR}/mender-tegra-verify-boot-rootfs-slot-alignment-no-redundant-bootloader ${D}${bindir}/mender-tegra-verify-boot-rootfs-slot-alignment
}

# Tegra 210 (nano) platforms don't support redundant bootloader today
# Use the version of the slot alignment verify script which doesn't use redundant bootloader
do_install_append_tegra210() {
    install_commit_service
    install_slot_align_verify_no_redundant_bootloader
}

do_install_append_tegra194() {
    install_commit_service
    install_slot_align_verify
}

do_install_append_tegra186() {
    install_commit_service
    # If building the uboot build, the slot alignment verify script will be installed by override here
    install_slot_align_verify
}

PACKAGE_ARCH = "${MACHINE_ARCH}"
