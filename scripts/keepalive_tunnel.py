import time
import urllib.request

URL = 'https://f4ece397dec203a9-106-195-71-196.serveousercontent.com/api/health'

def main():
    while True:
        try:
            req = urllib.request.Request(URL, headers={'User-Agent': 'TunnelKeepAlive/1.0'})
            with urllib.request.urlopen(req, timeout=10) as res:
                pass
        except Exception:
            pass
        time.sleep(30)

if __name__ == '__main__':
    main()
