
# Adapter to sit between the servers and relay, so that servers can hook to the relay as-is.
#
# Set these values for your relay and servers.  (Really gotta make these command-line args.)


import argparse
import string

parser = argparse.ArgumentParser(description='Connect existing servers to a relay (or to this).')
parser.add_argument('--no-relay', '-n', action='store_true',
                   help='do not connect to a relay; connect to and expose one server')
parser.add_argument('relayHostPort', default='localhost:8080',
                   help='the host:port for the relay (or just the port if using no relay)')
parser.add_argument('serverHostPorts', nargs='+', default='localhost:8081',
                   help='the host:port combinations for all servers')
parser.add_argument('--verbose', '-v', action='count')

args = parser.parse_args()


def splitColon(str):
    [host, port] = string.split(str, ":")
    return (host, port)
def portToInt((host, port)):
    return (host, int(port))


NO_RELAY = args.no_relay
if args.relayHostPort.find(":") > -1:
    RELAY_SERVER = portToInt(splitColon(args.relayHostPort))
else:
    RELAY_SERVER = (int(args.relayHostPort),)

SERVERS = map(portToInt, map(splitColon, args.serverHostPorts))

VERBOSE = args.verbose




# BEWARE: a blank request (eg. only a newline) signals an end to that whole cilent-server conversation

import socket
import threading
import time
import SocketServer

SHUTDOWN_COMMAND = "shutdown adapter"

# Read from the sockets, looking for "\n" (one character at a time).
# GOTTA LOOK AT ALL USES OF THIS AND ELIMINATE IT NOW THAT RELAYING ISN'T BOUND TO NEWLINES.
def readLine(s):
    return s.makefile().readline().rstrip("\n")
'''
    # another approach
    ret = ''
    while True:
        c = s.recv(1)
        if c == '\n' or c == '':
            break
        else:
            ret += c
    return ret
'''


def hostAndPortTuple(hostAndPort):
    hostPortList = hostAndPort.split(":")
    return (hostPortList[0], int(hostPortList[1]))


# ugly and often gets errors, but it allows us to kill it (or get into a state where Ctrl-C works)
socketsToShutdown = []
def shutdownAllSockets():
    print "Shutting it all down."
    for sock in socketsToShutdown:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        finally:
            pass # don't care about errors; just want to close them all
    exit(0)






#
# base handler for line-oriented server request/response
#
class NewlineProxyHandler(SocketServer.BaseRequestHandler):
    def handle(self):
        serverSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        serverSock.connect(SERVERS[0])
        socketsToShutdown.append(serverSock)

        data = readLine(self.request)
        while (data != ''):
            if (data == SHUTDOWN_COMMAND):
                shutdownAllSockets()
            else:
                serverSock.sendall(data + "\n")
                response = readLine(serverSock)
                self.request.sendall(response + "\n")
                data = readLine(self.request)

class ThreadedTCPServer(SocketServer.ThreadingMixIn, SocketServer.TCPServer):
    pass







class CopyFromSockToSock(threading.Thread):
    def __init__(self, clientSock, serverSock):
        super(CopyFromSockToSock, self).__init__()
        self.clientSock = clientSock
        self.serverSock = serverSock
    def run(self):
        try:
            request = readLine(self.clientSock)
            while (request != ''):
               if (request == SHUTDOWN_COMMAND):
                   shutdownAllSockets()
               else:
                    self.serverSock.sendall(request + "\n")
                    response = readLine(self.serverSock)
                    self.clientSock.sendall(response + "\n")
                    request = readLine(self.clientSock)
        finally:
            self.clientSock.close()
            self.serverSock.close()





#
# This protocol fits my relay server.
#
class RouteThroughRelay(threading.Thread):
    def __init__(self, publicHostAndPort, relaySock, serverHostAndPort):
        super(RouteThroughRelay, self).__init__()
        self.publicHostAndPort = publicHostAndPort
        self.serverHostAndPort = serverHostAndPort
        self.relaySock = relaySock
    def run(self):

        # This is the part of the program where you'll want to customize behavior for this server.

        newClientHostPortStr = readLine(self.relaySock)
        while (newClientHostPortStr != ''):
            if (VERBOSE):
                print "New client now available at {} going to {}".format(newClientHostPortStr,
                                                                          self.serverHostAndPort)
            newClientHostAndPort = hostAndPortTuple(newClientHostPortStr)
            
            clientRelaySock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            clientRelaySock.connect(newClientHostAndPort)
            socketsToShutdown.append(clientRelaySock)
            
            serverSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            serverSock.connect(self.serverHostAndPort)
            socketsToShutdown.append(serverSock)
            
            CopyFromSockToSock(clientRelaySock, serverSock).start()

            newClientHostPortStr = readLine(self.relaySock)



#
# Note that this protocol does not work.  (Try it with long-running requests from different clients.)
#
class RouteThroughOldRelay(threading.Thread):
    def __init__(self, publicHostAndPort, relaySock, serverHostAndPort):
        super(RouteThroughOldRelay, self).__init__()
        self.publicHostAndPort = publicHostAndPort
        self.serverHostAndPort = serverHostAndPort
        self.relaySock = relaySock
    def run(self):

        # This is the part of the program where you'll want to customize behavior for this server.

        serverSock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        serverSock.connect(self.serverHostAndPort)
        socketsToShutdown.append(serverSock)
            
        CopyFromSockToSock(self.relaySock, serverSock).start()









# Now for the main event.

print "To shutdown, connect to any public port and enter:", SHUTDOWN_COMMAND

if len(RELAY_SERVER) < 2:
    # We're a simple proxy in front of the first server
    server = ThreadedTCPServer(('localhost', RELAY_SERVER[0]), NewlineProxyHandler)
    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()
    print "listening on port", RELAY_SERVER[0]
    while (True):
        time.sleep(10)
        


else:
    # For each server, get a connection to the relay.
    for idx, serverHostAndPort in enumerate(SERVERS):
        relaySock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        relaySock.connect(RELAY_SERVER)
        socketsToShutdown.append(relaySock)
            
        # get the HOST:PORT for this server's public address
        publicHostAndPort = hostAndPortTuple(readLine(relaySock))
        print "server {}={} is public at {}".format(idx, serverHostAndPort, publicHostAndPort)

        RouteThroughRelay(publicHostAndPort, relaySock, serverHostAndPort).start()
        #RouteThroughOldRelay(publicHostAndPort, relaySock, serverHostAndPort).start()
    
