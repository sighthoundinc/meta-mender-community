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

        return subprocess.call(command) == 0

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

    def mender_commit(self):
        self.get_connection().run("mender -commit")

    def reboot(self):
        conn = self.get_connection()
        print("Rebooting device")
        result = conn.run("reboot", warn=True)
        self.wait_for_device_removal()
        self.wait_for_device()

    def do_single_mender_update(self):
        self.wait_for_device()
        self.mender_install()
        self.reboot()
        self.mender_commit()
        

    def do_test(self):
        self.do_single_mender_update()



if __name__ == '__main__':
    test = MenderStandaloneTests()
    test.do_test()


