import os
import sys
import time
import fdb
from fdb import ISOLATION_LEVEL_READ_COMMITED_LEGACY

try:
    import tools
except ImportError:
    from indexer import tools


def timing(f):
    """
    A decorator that measures and prints the execution time of the decorated function.

    Args:
        f (callable): The function to be decorated.

    Returns:
        callable: The wrapped function that includes timing functionality.
    """
    def wrap(*args, **kwargs):
        """
        The wrapper function that measures execution time.

        Args:
            *args: Variable length argument list passed to the decorated function.
            **kwargs: Arbitrary keyword arguments passed to the decorated function.

        Returns:
            Any: The return value from the decorated function.
        """
        time1 = time.time()
        ret = f(*args, **kwargs)
        time2 = time.time()
        print('{:s} function took {:.3f} ms'.format(f.__name__, (time2-time1)*1000.0))

        return ret
    return wrap

import socket
import re
import sys

def check_server(address, port):
    # Create a TCP socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.connect((address, port))

            return True
        except socket.error as e:

            return False

class Connector:
    """
    A class that manages connections to up to three Firebird databases.

    This class reads configuration from an INI file and establishes connections
    to primary, secondary, and tertiary Firebird databases as specified in the
    configuration. It provides methods to retrieve these connections, ensuring
    they are reopened if closed.
    """
    # timing
    def __init__(self):
        """
        Initialize the Connector with database connection settings from an INI file.

        Args:
            inifile (str, optional): Path to the configuration INI file. 
                                     Defaults to 'iceshake.ini'.

        Note:
            The INI file should contain sections for 'Connection', and optionally
            'Connection2' and 'Connection3', each with host, database, fb_library_name,
            user, and password settings.
        """

        config = tools.get_config()

        # Primary connection settings
        self.host = config.get('Connection', 'host')
        self.database = config.get('Connection', 'database')
        self.fb_library_name = config.get('Connection', 'fb_library_name_w32' if sys.platform == 'win32' else 'fb_library_name')
        self.user = config.get('Connection', 'user')
        self.password = config.get('Connection', 'password')
        try:
             self.port = config.getint ('Connection', 'port')
        except:
            self.port = 3050
        # Initialize primary connection
        try:
            counter = 0
            while not check_server(self.host, self.port) and not counter> 120:
                print(f"Waiting for primary database on {self.host}:{self.port} to start...")
                counter += 1
                time.sleep(10)
            self.con = fdb.connect(host=self.host, port=self.port, database=self.database, user=self.user, password=self.password,
                                  fb_library_name=self.fb_library_name, charset='UTF-8')
        except Exception as e:
            print(f"Error connecting to primary database: {e}")
            self.con = None


    #timing
    def getconnection(self):
        """
        Get the primary database connection, reopening it if closed.

        Returns:
            fdb.Connection: An active connection to the primary Firebird database.

        Note:
            If the connection is closed, it will be reopened with the same
            connection parameters that were specified in the configuration file.
        """
        if self.con.closed:
            self.con = fdb.connect(host=self.host, database=self.database, user=self.user, password=self.password,
                                   fb_library_name=self.fb_library_name, isolation_level=ISOLATION_LEVEL_READ_COMMITED_LEGACY, charset='UTF-8')
        return self.con



if __name__ == '__main__':
    c=Connector()
    print(c.getconnection().database_name)
    print(c.getconnection().site_name)
    c.con.close()
