import json
from unittest.mock import patch, MagicMock
from scripts.collect_kioxia_dex import fetch

def test_fetch_builds_hip3_coin_request():
    payload=[{"t":1,"T":2,"s":"xyz:KIOXIA","i":"1m","o":"1","h":"2","l":"1","c":"2","v":"3","n":4}]
    cm=MagicMock(); cm.__enter__.return_value=MagicMock()
    cm.__enter__.return_value.read.return_value=json.dumps(payload).encode()
    cm.__enter__.return_value.__iter__.return_value=iter([])
    with patch("urllib.request.urlopen") as u:
        u.return_value=cm
        # json.load expects file-like; easier response object:
        cm.__enter__.return_value.read.side_effect=None
        cm.__enter__.return_value.read.return_value=json.dumps(payload).encode()
        with patch("json.load", return_value=payload):
            got=fetch("xyz:KIOXIA","1m",1000,2000)
    assert got==payload
    req=u.call_args.args[0]
    body=json.loads(req.data.decode())
    assert body["type"]=="candleSnapshot"
    assert body["req"]=={"coin":"xyz:KIOXIA","interval":"1m","startTime":1000,"endTime":2000}
