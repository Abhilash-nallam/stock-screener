import os, requests
from dotenv import load_dotenv
load_dotenv()
TIMEOUT=20

class BrokerAPIError(RuntimeError): pass

def _get(url, headers, params=None):
    r=requests.get(url,headers=headers,params=params,timeout=TIMEOUT)
    if r.status_code != 200:
        raise BrokerAPIError(f"HTTP {r.status_code}: {r.text[:250]}")
    data=r.json()
    if isinstance(data,dict) and data.get("status")=="FAILURE":
        raise BrokerAPIError(str(data.get("error","Broker API returned FAILURE"))[:250])
    return data

def dhan_readonly():
    token=os.getenv("DHAN_ACCESS_TOKEN","").strip()
    if not token: raise BrokerAPIError("DHAN_ACCESS_TOKEN missing in .env")
    h={"access-token":token,"Content-Type":"application/json","Accept":"application/json"}
    holdings=_get("https://api dhan.co/v2/holdings".replace(" ",""),h)
    positions=_get("https://api.dhan.co/v2/positions".replace(" ",""),h)
    funds=_get("https://api.dhan.co/v2/fundlimit".replace(" ",""),h)
    return {"broker":"Dhan","holdings":holdings if isinstance(holdings,list) else [],
            "positions":positions if isinstance(positions,list) else [],
            "funds":funds}

def groww_readonly():
    token=os.getenv("GROWW_ACCESS_TOKEN","").strip()
    if not token: raise BrokerAPIError("GROWW_ACCESS_TOKEN missing in .env")
    h={"Authorization":f"Bearer {token}","Accept":"application/json","X-API-VERSION":"1.0"}
    def payload(path,params=None):
        data=_get("https://api.groww.in"+path,h,params)
        if isinstance(data,dict): return data.get("payload",data)
        return data
    holdings=payload("/v1/holdings/user")
    positions=payload("/v1/positions/user",{"segment":"CASH"})
    margin=payload("/v1/margins/detail/user")
    return {"broker":"Groww","holdings":holdings.get("holdings",[]) if isinstance(holdings,dict) else [],
            "positions":positions.get("positions",[]) if isinstance(positions,dict) else [],
            "funds":margin}

def fetch_broker_accounts():
    results={}
    for name,fn in [("Dhan",dhan_readonly),("Groww",groww_readonly)]:
        try: results[name]={"ok":True,"data":fn()}
        except Exception as e: results[name]={"ok":False,"error":str(e)}
    return results
