import socket
import sys

def check_mongo_port():
    host = '127.0.0.1'
    port = 27017
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)
    try:
        s.connect((host, port))
        print("✅ MongoDB port (27017) is OPEN and accepting connections!")
        s.close()
        sys.exit(0)
    except Exception as e:
        print(f"❌ MongoDB port (27017) is CLOSED or unreachable: {e}")
        sys.exit(1)

if __name__ == '__main__':
    check_mongo_port()
