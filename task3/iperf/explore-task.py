#!/usr/bin/env python3

import socket
import os
import subprocess
import sys
import time
import getopt
import ipaddress
from queue import Queue
from threading import Thread
import netifaces as ni

# Adapted from https://stackoverflow.com/a/7257510
class Worker(Thread):
    """Thread executing tasks from a given tasks queue"""
    def __init__(self, tasks, retVal = None):
        Thread.__init__(self)
        self.tasks = tasks
        self.daemon = True
        self.start()

    def run(self):
        while True:
            func, args, kargs = self.tasks.get()
            try:
                spd = func(*args, **kargs)
                self.retVal = spd
            except Exception:
                print("exception silenced")
            finally:
                self.tasks.task_done()

class ThreadPool:
    """Pool of threads consuming tasks from a queue"""
    def __init__(self, num_threads):
        self.tasks = Queue(num_threads)
        self.workers = []
        for _ in range(num_threads):
            self.workers.append(Worker(self.tasks))
            # print(f'workers has {len(self.workers)} length')

    def add_task(self, func, *args, **kargs):
        """Add a task to the queue"""
        self.tasks.put((func, args, kargs))

    def wait_completion(self):
        """Wait for completion of all the tasks in the queue"""
        self.tasks.join()
        
    def wait_completion_and_return_sum(self) -> float: 
        sum = 0
        
        start = time.time()
        self.wait_completion()
        # print(f'took {time.time() - start} seconds.')
        for worker in self.workers:
            sum += worker.retVal
            prefix, normalizedSpeed = get_prefix(worker.retVal)
        
        return sum

PORT = 5201        # Port to listen on (non-privileged ports are > 1023)

def get_prefix(speed): 
    orderOfMagnitude = 0
    while speed > 1000:
        orderOfMagnitude += 3
        speed /= 1000

    prefix = 'bits'
    if orderOfMagnitude == 3:
        prefix = 'Kbits/s'
    if orderOfMagnitude == 6:
        prefix = 'Mbits/s'
    if orderOfMagnitude == 9:
        prefix = 'Gbits/s'
    if orderOfMagnitude == 12:
        prefix = 'Tbits/s'
    if orderOfMagnitude > 12:
        prefix = 'holybits/s'
    return prefix, speed

def create_client_socket(ip, port, buffer_length, duration) -> float:
    if isinstance(ip, ipaddress.IPv4Address):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    elif isinstance(ip, ipaddress.IPv6Address):
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, bytes('swissknife0'.encode()))
    s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, buffer_length)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, buffer_length)
    
    client_loop(s, ip, port, buffer_length, duration)

def start_server(host, port, buffer_length, connections) -> int:
    childpid = os.fork()
    if childpid != 0:
        return childpid
    ip = ipaddress.ip_address(host)
    
    global pool
    global speed
    
    if isinstance(ip, ipaddress.IPv4Address):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    elif isinstance(ip, ipaddress.IPv6Address):
        s = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, bytes('swissknife0'.encode()))
    s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, buffer_length)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, buffer_length)
    s.bind((str(ip), port))
    s.listen()
    
    if connections > 1:
        pool = ThreadPool(connections)
        speeds = []
        for _ in range(connections):
            pool.add_task(server_loop, s, buffer_length)
        speed = pool.wait_completion_and_return_sum()
        pool.wait_completion()
    else:
        speed = server_loop(s, buffer_length)
    prefix, normalizedSpeed = get_prefix(speed)
    print(f'Speed achieved is {normalizedSpeed} {prefix}')
    sys.exit(1)
    

def start_client(host, port, buffer_length, duration, connections) -> int:
    childpid = os.fork()
    if childpid != 0:
        return childpid
    ip = ipaddress.ip_address(host)
    if connections > 1:
        pool = ThreadPool(connections)
        for i in range(connections):
            pool.add_task(create_client_socket, ip, port, buffer_length, duration)
        pool.wait_completion()
    else:
        if isinstance(ip, ipaddress.IPv4Address):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, bytes('swissknife0'.encode()))
                s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, buffer_length)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, buffer_length)
                client_loop(s, host, port, buffer_length, duration)
                
        elif isinstance(ip, ipaddress.IPv6Address):
            with socket.socket(socket.AF_INET6, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_BINDTODEVICE, bytes('swissknife0'.encode()))
                s.setsockopt(socket.SOL_SOCKET, socket.SO_SNDBUF, buffer_length)
                s.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, buffer_length)
                client_loop(s, host, port, buffer_length, duration)
    sys.exit(1)

def server_loop(sock: socket.socket, buffer_length) -> float:
    conn, _ = sock.accept()
    received = 0
    firstReceive = True
    with conn:
        while True:
            data = conn.recv(buffer_length)
            if firstReceive:
                firstReceive = False
                start = time.time()
            if not data:
                end = time.time()
                break
            length = len(data)
            received += length
    return received / (end-start)
    
def client_loop(sock: socket.socket, host, port, buffer_length, duration): 
    buffer = [1] * buffer_length
    b = bytes(buffer)
    sock.connect((str(host), port))
    end_time = time.time() + duration
    while time.time() < end_time:
        sock.send(b)
    sock.close()
        
def open_port(port) -> None:
    # using fuser to remove blocking process from using determinated ports    
    portWithTcp = f'{str(port)}/tcp'
    process = subprocess.Popen(['fuser', '-k', portWithTcp],
                                stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE,
                                universal_newlines=True)
    while True:
            output = process.stdout.readline()
            stripped = output.strip()
            if not stripped.isspace():
                print(stripped)
            # Do something else
            return_code = process.poll()
            if return_code is not None:
                # Process has finished, read rest of the output
                for output in process.stdout.readlines():
                    stripped = output.strip()
                    if not stripped.isspace():
                        print(stripped)
                break

def main(argv) -> None:
    try:
        opts, args = getopt.getopt(argv, "p:f:d:c:t:l:u",
                                   ["port=" "plot_filename=" "data_filename=" "connections=" "time=" "length=" "udp"])
    except getopt.GetoptError:
        print("Syntax Error.")
        sys.exit(2)

    addrs = map(lambda ip: ip["addr"], ni.ifaddresses('swissknife0')[ni.AF_INET]) # IPv6 doesn't work yet
    addrsv6 = map(lambda ip: ip["addr"], ni.ifaddresses('swissknife0')[ni.AF_INET6]) # IPv6 doesn't work yet
    ip = list(filter(lambda ip: "swissknife0" in ip, list(addrs)+list(addrsv6))).pop()
    #ip = list(addrs).pop()
    #ip = '169.254.68.39'
    global port
    global plot_filename
    global data_filename
    port = PORT
    connections = 1
    duration = 10
    length=128
    udp = False
    for opt, arg in opts:
        if opt in ("-p", "--port"):
            port = arg
        elif opt in ("-c", "--connections"):
            connections = int(arg)
            print(f'benchmarking with {connections} connections, this might take a while...')
        elif opt in ("-t", "--time"):
            duration = int(arg)
            
        elif opt in ("-l", "--length"):
            length = int(arg)
        elif opt in ("-u", "--udp"):
            udp = True
            length = 1460
            
    print(f'ip: {ip}:{port}')
    
    port = int(port)
    open_port(port)
    #ip = 'fe80::e63d:1aff:fe72:f0'
    serverpid = start_server(ip, port, length, connections)
    clientpid = start_client(ip, port, length, duration, connections)

    try:
        os.waitpid(serverpid, 0)
        os.waitpid(clientpid, 0)
    except ChildProcessError:
        print()

if __name__ == "__main__":
    main(sys.argv[1:])