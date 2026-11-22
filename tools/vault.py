#!/usr/bin/env python3
"""Plants Atlas private vault.

Personal data (application statuses, notes, events found in Gmail, career profile, added skills) lives
encrypted in data.json under "vault". Adding records needs only the public key, so updates never need the
PIN. Reading needs the PIN, which only the app (and `read`) uses. Nothing secret is ever written in plain text.

  python3 tools/vault.py add batch.json        encrypt a batch {track?, events?, profile?, skills?, seen?} and append it
  python3 tools/vault.py seen ID [ID ...]       print the Gmail message ids that were NOT processed before
  python3 tools/vault.py jid URL                the app's job id for a job URL
  PA_PIN=... python3 tools/vault.py init        one-off: create keys, move plain track/profile/skills into the vault
  PA_PIN=... python3 tools/vault.py read        decrypt and print the merged vault (for checking only)
  PA_PIN=old PA_NEWPIN=new python3 tools/vault.py repin   change the PIN
"""
import base64, hashlib, json, os, sys, datetime
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data.json")
INFO = b"plants-atlas-v1"
ITER = 600_000
b64 = lambda b: base64.b64encode(b).decode()
ub64 = base64.b64decode

def load(): return json.load(open(DATA))
def save(d):
    json.dump(d, open(DATA, "w"), indent=1, ensure_ascii=False); json.load(open(DATA))

def jid(u):
    h = 7
    for ch in u: h = (h * 31 + ord(ch)) & 0xffffffff
    s, D = "", "0123456789abcdefghijklmnopqrstuvwxyz"
    while h: s = D[h % 36] + s; h //= 36
    return s or "0"

def seen_hash(mid): return hashlib.sha256(("pa-seen:" + mid).encode()).hexdigest()[:20]

def pin_key(pin, salt, it=ITER):
    return PBKDF2HMAC(hashes.SHA256(), 32, salt, it).derive(pin.encode())

def seal(pub_raw, obj):
    pub = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), pub_raw)
    eph = ec.generate_private_key(ec.SECP256R1())
    shared = eph.exchange(ec.ECDH(), pub)
    key = HKDF(hashes.SHA256(), 32, b"\0" * 32, INFO).derive(shared)
    iv = os.urandom(12)
    ct = AESGCM(key).encrypt(iv, json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode(), None)
    e = eph.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return {"e": b64(e), "iv": b64(iv), "ct": b64(ct)}

def unwrap(v, pin):
    k = pin_key(pin, ub64(v["kdf"]["salt"]), v["kdf"]["iter"])
    der = AESGCM(k).decrypt(ub64(v["wrapped"]["iv"]), ub64(v["wrapped"]["ct"]), None)
    return serialization.load_der_private_key(der, None)

def open_rec(priv, r):
    eph = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), ub64(r["e"]))
    key = HKDF(hashes.SHA256(), 32, b"\0" * 32, INFO).derive(priv.exchange(ec.ECDH(), eph))
    return json.loads(AESGCM(key).decrypt(ub64(r["iv"]), ub64(r["ct"]), None))

def now(): return datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=11))).isoformat(timespec="seconds")

def wrap(priv, pin):
    salt, iv = os.urandom(16), os.urandom(12)
    der = priv.private_bytes(serialization.Encoding.DER, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    return {"salt": b64(salt), "iter": ITER}, {"iv": b64(iv), "ct": b64(AESGCM(pin_key(pin, salt)).encrypt(iv, der, None))}

def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "jid": print(jid(sys.argv[2])); return
    d = load()
    if cmd == "init":
        pin = os.environ["PA_PIN"]
        if d.get("vault"): sys.exit("vault already exists")
        priv = ec.generate_private_key(ec.SECP256R1())
        pub = priv.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        kdf, wrapped = wrap(priv, pin)
        first = {"at": now()}
        for k in ("track", "profile", "skills"):
            if d.get(k): first[k] = d[k]
            d.pop(k, None)
        d["vault"] = {"v": 1, "pub": b64(pub), "kdf": kdf, "wrapped": wrapped, "recs": [seal(pub, first)], "seen": []}
        save(d); print("vault created; moved:", [k for k in first if k != "at"]); return
    v = d["vault"]
    if cmd == "add":
        b = json.load(open(sys.argv[2]))
        ids = b.pop("seen", [])
        b.setdefault("at", now())
        v["recs"].append(seal(ub64(v["pub"]), b))
        hs = set(v.get("seen", []))
        v["seen"] = list(hs | {seen_hash(m) for m in ids})
        save(d); print("added record", len(v["recs"]), "events", len(b.get("events", [])), "track", len(b.get("track", {}))); return
    if cmd == "seen":
        hs = set(v.get("seen", []))
        print("\n".join(m for m in sys.argv[2:] if seen_hash(m) not in hs)); return
    if cmd == "read":
        priv = unwrap(v, os.environ["PA_PIN"])
        for r in v["recs"]: print(json.dumps(open_rec(priv, r), ensure_ascii=False))
        return
    if cmd == "repin":
        priv = unwrap(v, os.environ["PA_PIN"])
        v["kdf"], v["wrapped"] = wrap(priv, os.environ["PA_NEWPIN"]); save(d); print("PIN changed"); return
    print(__doc__)

if __name__ == "__main__": main()
