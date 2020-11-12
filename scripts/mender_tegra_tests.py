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
    DEFAULT_BOOT_METHOD = 'cboot'
    args = None
    connection = None
    argparser = None
    
    def get_parser(self):
        if self.argparser is None:
            '''
            Argument parsing for new deployment and provisioning process
            '''
            argparser = argparse.ArgumentParser(prog='mender_tegra_tests.py',
                                                usage='%(prog)s [options]',
                                                description='Provisions Boulder AI devices')
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
            argparser.add_argument('-b',
                                   '--boot_method',
                                   help='Boot Method: uboot or cboot (default is cboot)')
 
            self.argparser = argparser 
        return self.argparser


    def get_args(self):
        if self.args is None:
            self.args = self.get_parser().parse_args()

            if self.args.user is None:
                print("No user specified, using {}".format(self.DEFAULT_USER))
                self.args.user=self.DEFAULT_USER
            if self.args.boot_method is None:
                print("No boot method specified, using {}".format(self.DEFAULT_BOOT_METHOD))
                self.args.boot_method=self.DEFAULT_BOOT_METHOD
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


    def do_single_mender_update(self):
        # Connecting to the device
        self.wait_for_device()
        # mender install 
        self.mender_install()
        # Make sure the sentinel file is present before reboot
        self.add_sentinel_file()
        # Check Partition Mismatch
        self.check_partition_mismatch()
        # Get current boot slot after mender update and before reboot
        prev_boot_slot = self.nvbootctrl_current_slot()
        # reboot the device
        self.reboot()
        # Getting current_boot_slot after reboot
        current_boot_slot = self.nvbootctrl_current_slot()
        # Check if update was successful after reboot
        if prev_boot_slot == current_boot_slot:
            raise RuntimeError("Mender Install successful but slot change not reflected after reboot")
        # mender commit (has no effect for cboot)
        if self.get_args().boot_method == 'cboot':
            self.mender_commit()
        
        return current_boot_slot 


    def check_rollback(self):
        print("****************************************")
        print("Starting test case")
        boot_slot = self.do_single_mender_update()
        for i in range(7):
            # Check Partition Mismatch
            self.check_partition_mismatch()
            # check the current boot_slot
            if boot_slot != self.nvbootctrl_current_slot():
                raise RuntimeError("Mender Rollback occurred earlier than expected")
            self.reboot()
        # Device expected to rollback here
        if boot_slot != self.nvbootctrl_current_slot():
            print("Success: Rollback after 7 reboots")
        else:
            raise RuntimeError("ERROR: No rollback after 7 reboots")

    def do_test(self):
        while 1:
            self.check_rollback()



if __name__ == '__main__':
    test = MenderStandaloneTests()
    test.do_test()


