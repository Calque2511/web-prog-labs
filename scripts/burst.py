# запуск: python scripts/burst.py https://localhost:8443/health 100
import collections
import concurrent.futures as cf
import ssl
import sys
import urllib.error
import urllib.request

url, n = sys.argv[1], int(sys.argv[2])
ctx = ssl.create_default_context()
ctx.check_hostname, ctx.verify_mode = False, ssl.CERT_NONE


def hit(_: int) -> int:
    try:
        return urllib.request.urlopen(url, context=ctx).status
    except urllib.error.HTTPError as e:
        return e.code


with cf.ThreadPoolExecutor(50) as pool:
    print(dict(collections.Counter(pool.map(hit, range(n)))))
