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
    
    def get_parser(self):
        '''
        Argument parsing for testing mender deployment
        '''  
        if self.argparser is None:
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
        '''
        Sets the default values to arguments not provided 
        '''
        if self.args is None:
            self.args = self.get_parser().parse_args()

            if self.args.user is None:
                print("No user specified, using {}".format(self.DEFAULT_USER))
                self.args.user=self.DEFAULT_USER
        return self.args

    def get_connection(self):
        '''
        Set the connection parameters based on the command line arguments for ssh connection
        @return returns the connection object to run commands on target.
        '''
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
        '''
        Function to retry creating an ssh connection to the device 
        '''
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
        """
        Returns True if host (str) responds to a ping request.
        Remember that a host may not respond to a ping (ICMP) request even if the host name is valid.
        See https://stackoverflow.com/a/32684938/1446624
        """
        args=self.get_args()
        # Option for the number of packets as a function of
        param = '-n' if platform.system().lower() == 'windows' else '-c'

        # Building the command. Ex: "ping -c 1 google.com"
        command = ['ping', param, '1', args.device]

        return subprocess.call(command, stdout=subprocess.DEVNULL, stderr=subprocess.STDOUT) == 0

    def wait_for_device_removal(self):
        '''
        Checks to see if the device is off the network
        '''
        while self.ping():
            pass

    def mender_install(self):
        '''
        Mender install the image passed as commandline argument in standalone mode
        '''
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
        """
        Generate a sentinel file signifying not to mark the boot as successful to test rollback cases.
        The meta-mender-tegra layer has a service which does not mark the boot as successful if the file exists.
        This is used to test rollback scenarios.
        """
        conn = self.get_connection()
        conn.run("mkdir -p /var/lib/mender")
        conn.run("touch /var/lib/mender/dont-mark-next-boot-successful")

    def remove_sentinel_file(self):
        '''
        Remove the sentinel file for normal operation i.e successful boot.
        '''
        conn = self.get_connection()
        conn.run("rm -f /var/lib/mender/dont-mark-next-boot-successful")

    def mender_commit(self):
        '''
        Commit changes for mender updates after a reboot.
        '''
        self.get_connection().run("mender -commit")

    def reboot(self):
        '''
        Function reboot the device and establish ssh connection
        '''
        conn = self.get_connection()
        print("Rebooting device")
        result = conn.run("reboot", warn=True)
        self.wait_for_device_removal()
        self.wait_for_device()

    def nvbootctrl_current_slot(self):
        '''
        Returns the current boot slot value
        '''
        conn = self.get_connection()
        result = conn.run("nvbootctrl get-current-slot")
        return result.stdout.strip()

    def check_partition_mismatch(self):
        '''
        Function to check boot and rootfs partition mismatch after reboot.
        To be used after every reboot.
        '''
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

    def reboot_and_verify_slot(self):
        '''
        Verifies if the boot slot has not changed after a reboot.
        Function to be used when we want to verify if simple reboots do not lead to boot slot change.
        '''
        prev_boot_slot = self.nvbootctrl_current_slot()
        self.reboot()
        boot_slot = self.nvbootctrl_current_slot()
        if boot_slot != prev_boot_slot:
           raise RuntimeError("Boot slot changed from {} to {} across reboots".format(prev_boot_slot,boot_slot))

    def mender_reboot_and_verify_slot(self):
        '''
        Verifies if the boot slot has changed on a reboot after a mender update.
        Function to be used when we want to verify if reboots after mender updates leads to boot slot change.
        '''
        prev_boot_slot = self.nvbootctrl_current_slot()
        self.reboot()
        boot_slot = self.nvbootctrl_current_slot()
        if boot_slot == prev_boot_slot:
           raise RuntimeError("Boot slot not changed from {} to {} after mender update reboot".format(prev_boot_slot,boot_slot))

    def do_single_mender_update(self, rollback_flag):
        '''
        Function to mender update a device, check partition mismatch, boot slot change and mender commit.
        To use when testing single mender update followed by a reboot.
        @rollback_flag This parameter expects a bool value. False would replicate successful mender update and boot case.
                        True would replicate rollback test case. This is achieved by creating the sentinel file which prevents
                        the boot to be marked successful.
        Note: do_single_mender_update(True) should be followed by do_rollback_after_mender_update() method to test rollback scenario
        '''
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
        self.mender_reboot_and_verify_slot()

        # rollback_flag is set true to replicate rollback case, false to replicate successful mender update case.
        # Mender commit is redundant in case of cboot(no harm in commiting or not), but we need to make sure we don't mender commit when testing rollback case for uboot.
        # Since that would lead to partition mismatch.
        # In conclusion for uboot, mender commit is required for a successful mender update and not required to test the rollback case.
        if not rollback_flag:
            self.mender_commit()

        # Remove the installed file that forces to replicate rollback scenario
        self.remove_sentinel_file()

    def do_rollback_after_mender_update(self):
        '''
        Function to check if the device roll backs to the previous partition after a mender update with the sentinel file added.
        This function needs to be called after the do_single_mender_update(True) function to replicate and verify rollback scenario.
        '''
        # Add the sentinel file to replicate rollback scenario
        self.add_sentinel_file()
        boot_slot = self.nvbootctrl_current_slot()
        loop = 7
        # nvidia gives 7 retries before switching boot partition. For uboot rollback requires less than 7 retries
        for i in range(7):
            print(f'Starting reboot {i} to test rollback case')
            # Check Partition Mismatch
            self.check_partition_mismatch()
            # check the current boot_slot
            if boot_slot != self.nvbootctrl_current_slot():
                loop = i
                break
            self.reboot()
        # Device expected to rollback here
        if boot_slot != self.nvbootctrl_current_slot():
            print(f'Success: Rollback after {loop} reboots')
        else:
            raise RuntimeError(f'ERROR: No rollback after {loop} reboots')
        self.remove_sentinel_file()

    def do_test_rollback(self):
        '''
        Function to test rollback scenario after a mender update
        '''
        self.do_single_mender_update(True)
        self.do_rollback_after_mender_update()

    def do_test(self):
        '''
        Function to execute test case with a rollback scenario, followed by a successful mender update scenario
        and checking if the successful mender update persist across several reboots
        '''
        # Passing true parameter to replicate rollback case
        self.do_test_rollback()
        self.do_single_mender_update(False)
        # Rebooting 16 times to make sure it stays in the correct parttion and does not rollback
        for loop in range(16):
            print(f'Starting reboot {loop} after successful mender update')
            self.check_partition_mismatch()
            self.reboot_and_verify_slot()

    def do_mender_torture(self):
        '''
        Function to test successive mender updates followed by the basic test case of roll back and mender update on both the partitions.
        '''
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
            self.reboot_and_verify_slot()

if __name__ == '__main__':
    test = MenderStandaloneTests()
    test.do_mender_torture()
    test.do_reboot_torture()


