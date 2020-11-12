import fabric2
from fabric2 import Connection
import argparse
import time
import traceback
import sys
import re
import subprocess
import platform

class MenderStandaloneTests:
    DEFAULT_USER = 'root'
    args = None
    connection = None
    argparser = None
    count = 0
    
    def get_parser(self):
        if self.argparser is None:
            '''
            Argument parsing for new deployment and provisioning process
            '''
            argparser = argparse.ArgumentParser(prog='mender_tegra_tests.py',
                                                usage='%(prog)s [options]',
                                                description='Script to test mender install and rollback extensively')
            argparser.add_argument('-d',
                                   '--device',
                                   help='The IP address or name of the device')

            argparser.add_argument('-u',
                                   '--user',
                                   help="The SSH username (default is {})".format(self.DEFAULT_USER))

            argparser.add_argument('-p',
                                   '--password',
                                   help='The SSH password (default is no password)')

            argparser.add_argument('-k',
                                   '--key',
                                   help='The SSH key file (used instead of password if specified)')

            argparser.add_argument('-i',
                                   '--install',
                                   help='The mender install argument to use with standalone install' +
                                        ' (http://mylocalserver:8000/path/to/mender/file') 
            self.argparser = argparser 
        return self.argparser


    def get_args(self):
        if self.args is None:
            self.args = self.get_parser().parse_args()

            if self.args.user is None:
                print("No user specified, using {}".format(self.DEFAULT_USER))
                self.args.user=self.DEFAULT_USER
        return self.args

    def get_connection(self):
        args = self.get_args()
        if self.connection is None:
            if args.key is not None:
                self.connection = Connection(
                    host='{}@{}'.format(args.user, args.device),
                    connect_kwargs={
                        "key_filename": args.key,
                        "password": args.password
                    })
            elif args.password is not None:
                self.connection = Connection(
                    host='{}@{}'.format(args.user, args.device),
                    connect_kwargs={
                        "password": args.password
                    })
            else:
                self.connection = Connection(
                    host='{}@{}'.format(args.user, args.device),
                    connect_kwargs={
                        "password": "",
                        "look_for_keys": False
                    })
        return self.connection

    def wait_for_device(self):
        conn = self.get_connection()
        print('Trying to connect to {}....'.format(self.get_args().device))
        success = False
        while not success:
            try:
                conn.open()
                success = True
            except Exception as e:
                print('Exception connecting, retrying in 3 seconds..')
                print(e)
                traceback.print_exc(file=sys.stdout)
            time.sleep(3)

    def ping(self):
        args=self.get_args()
        """
        Returns True if host (str) responds to a ping request.
        Remember that a host may not respond to a ping (ICMP) request even if the host name is valid.
        See https://stackoverflow.com/a/32684938/1446624
        """

        # Option for the number of packets as a function of
        param = '-n' if platform.system().lower() == 'windows' else '-c'

        # Building the command. Ex: "ping -c 1 google.com"
        command = ['ping', param, '1', args.device]

        return subprocess.call(command, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT) == 0

    def wait_for_device_removal(self):
        while self.ping():
            pass

    def mender_install(self):
        args = self.get_args()
        conn = self.get_connection()
        if args.install is None:
            self.get_parser().print_help()
            print("Missing argument install")
            raise RuntimeError("Missing argument install")
        result = conn.run("mender -install {}".format(args.install))
        # Mender doesn't return error states, so we can't check return codes here
        match = re.search(r' level=error ', result.stderr, re.MULTILINE)
        if match is not None:
            raise RuntimeError("Mender install failed with error messages in the logs")

    def add_sentinel_file(self):
        conn = self.get_connection()
        conn.run("mkdir -p /var/lib/mender")
        conn.run("touch /var/lib/mender/dont-mark-next-boot-successful")

    def remove_sentinel_file(self):
        conn = self.get_connection()
        conn.run("rm -f /var/lib/mender/dont-mark-next-boot-successful")

    def mender_commit(self):
        self.get_connection().run("mender -commit")

    def reboot(self):
        conn = self.get_connection()
        print("Rebooting device")
        result = conn.run("reboot", warn=True)
        self.wait_for_device_removal()
        self.wait_for_device()

    def nvbootctrl_current_slot(self):
        conn = self.get_connection()
        result = conn.run("nvbootctrl get-current-slot")
        return result.stdout.strip()

    def check_partition_mismatch(self):
        conn = self.get_connection()
        boot_slot = self.nvbootctrl_current_slot()
        rootfs_part = None
        if boot_slot == '0':
            rootfs_part = 'A'
        elif boot_slot == '1':
            rootfs_part = 'B'

        if rootfs_part != None:
            result = conn.run(f'grep -h {rootfs_part} /etc/mender/mender.conf /var/lib/mender/mender.conf | cut -d: -f2 | cut -d, -f1 | tr -d \'" \'')
            result = conn.run(f'df -h | grep {result.stdout.strip()}')
            if result.return_code != 0:
                raise RuntimeError("Boot and Rootfs Partition Mismatch detected")
        else:
            raise RuntimeError("Cannot Identify Rootfs Partition Slot")

    def verify_slot_change_across_reboots(self):
        prev_boot_slot = self.nvbootctrl_current_slot()
        self.reboot()
        boot_slot = self.nvbootctrl_current_slot()
        if boot_slot != prev_boot_slot:
           raise RuntimeError("Boot slot changed from {} to {} across reboots".format(prev_boot_slot,boot_slot))

    def verify_slot_change_across_mender_update(self):
        prev_boot_slot = self.nvbootctrl_current_slot()
        self.reboot()
        boot_slot = self.nvbootctrl_current_slot()
        if boot_slot == prev_boot_slot:
           raise RuntimeError("Boot slot not changed from {} to {} after mender update reboot".format(prev_boot_slot,boot_slot))

    def do_single_mender_update(self, rollback_flag):
        # Connecting to the device
        self.wait_for_device()
        # mender install 
        self.mender_install()
        # Make sure the sentinel file is not present before reboot for successful boot cases.
        # sentinel file required for rollback cases
        if rollback_flag:
            self.add_sentinel_file()
        else:
            self.remove_sentinel_file()

        # Check Partition Mismatch
        self.check_partition_mismatch()
        # Check slot changed after a mender update followed by reboot.
        self.verify_slot_change_across_mender_update()

        # rollback_flag is set true to replicate rollback case, false to replicate successful mender update case.
        # Mender commit is redundant in case of cboot(no harm in commiting or not), but we need to make sure we don't mender commit when testing rollback case for uboot.
        # Since that would lead to partition mismatch.
        # In conclusion for uboot, mender commit is required for a successful mender update and not required to test the rollback case.
        if not rollback_flag:
            self.mender_commit()

    def check_rollback(self):
        boot_slot = self.nvbootctrl_current_slot()

        # nvidia gives 7 retries before switching boot partition
        for i in range(7):
            print(f'Starting reboot {i} to test rollback case')
            # Check Partition Mismatch
            self.check_partition_mismatch()
            # check the current boot_slot
            if boot_slot != self.nvbootctrl_current_slot():
                self.count += 1 
            self.reboot()
        # Device expected to rollback here
        if boot_slot != self.nvbootctrl_current_slot():
            print("Success: Rollback after 7 reboots")
        else:
            raise RuntimeError("ERROR: No rollback after 7 reboots")
        self.remove_sentinel_file()

    def do_test(self):
        # Passing true parameter to replicate rollback case
        self.do_single_mender_update(True)
        self.check_rollback()
        self.do_single_mender_update(False)
        # Rebooting 16 times to make sure it stays in the correct parttion and does not rollback
        for loop in range(16):
            print(f'Starting reboot {loop} after successful mender update')
            self.check_partition_mismatch()
            self.verify_slot_change_across_reboots()

    def do_mender_torture(self):
        # Successive mender updates 20 times.
        for i in range(20):
            self.do_single_mender_update(False)
        # Basic test case
        for loop in range(20):
            self.do_test()
  
    def do_reboot_torture(self):
        """
        Do 100 reboots, making sure boot slot doesn't change and partition mismatch does not occur.
        """
        for i in range (100):
            print("Starting plain reboot {}".format(i))
            self.check_partition_mismatch()
            self.verify_slot_change_across_reboots()

if __name__ == '__main__':
    test = MenderStandaloneTests()
    test.do_mender_torture()
    test.do_reboot_torture()
    print(f'Number of times Rollback happened earlier that expected = {test.count}')


